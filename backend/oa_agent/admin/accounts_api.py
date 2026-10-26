"""/v1/admin/accounts/*、/v1/admin/roles/*、/v1/admin/perms：账号、角色、权限点。"""

from __future__ import annotations

import json
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from oa_agent.auth.passwords import check_strength, hash_password
from oa_agent.auth.perms import PERMISSIONS, SUPER_ADMIN_ROLE
from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import AdminRole, AdminRolePerm, AdminUser, AdminUserRole
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError

router = APIRouter(prefix="/v1/admin", tags=["admin-accounts"])

PERM = "sys.account.manage"


class AccountCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(default="", max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role_ids: list[int] = Field(default_factory=list)


class AccountUpdateIn(BaseModel):
    display_name: str = Field(default="", max_length=64)
    status: Literal["active", "disabled"] = "active"
    role_ids: list[int] = Field(default_factory=list)


class ResetPasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class RoleIn(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)
    perm_codes: list[str] = Field(default_factory=list)


# ---- helpers ----

def _roles_of(ctx: AdminCtx, user_ids: list[int]) -> dict[int, list[dict]]:
    if not user_ids:
        return {}
    rows = ctx.db.execute(
        sa.select(AdminUserRole.user_id, AdminRole.id, AdminRole.code, AdminRole.name)
        .join(AdminRole, AdminRole.id == AdminUserRole.role_id)
        .where(AdminUserRole.user_id.in_(user_ids))
    ).all()
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r.user_id, []).append({"id": r.id, "code": r.code, "name": r.name})
    return out


def _user_view(u: AdminUser, roles: list[dict]) -> dict:
    now = utcnow()
    return {
        "id": u.id, "username": u.username, "display_name": u.display_name, "status": u.status,
        "locked": bool(u.locked_until and u.locked_until > now), "locked_until": u.locked_until,
        "last_login_at": u.last_login_at, "created_at": u.created_at, "roles": roles,
    }


def _user_summary(u: AdminUser, roles: list[dict]) -> str:
    return json.dumps({"username": u.username, "display_name": u.display_name, "status": u.status,
                       "roles": sorted(r["code"] for r in roles)}, ensure_ascii=False)


def _get_user(ctx: AdminCtx, user_id: int) -> AdminUser:
    u = ctx.db.get(AdminUser, user_id)
    if u is None or u.tenant_id != ctx.runtime.tenant_id:
        raise AppError(404, "NOT_FOUND", "账号不存在")
    return u


def _validate_roles(ctx: AdminCtx, role_ids: list[int]) -> list[int]:
    ids = sorted(set(role_ids))
    if not ids:
        return []
    found = ctx.db.scalars(
        sa.select(AdminRole.id).where(AdminRole.id.in_(ids), AdminRole.tenant_id == ctx.runtime.tenant_id)
    ).all()
    missing = set(ids) - set(found)
    if missing:
        raise AppError(422, "VALIDATION_ERROR", f"角色不存在：{sorted(missing)}")
    return ids


def _set_roles(ctx: AdminCtx, user_id: int, role_ids: list[int]) -> None:
    ctx.db.execute(sa.delete(AdminUserRole).where(AdminUserRole.user_id == user_id))
    for rid in role_ids:
        ctx.db.add(AdminUserRole(user_id=user_id, role_id=rid))
    ctx.db.flush()


def _active_super_admins(ctx: AdminCtx) -> int:
    return ctx.db.scalar(
        sa.select(sa.func.count(sa.distinct(AdminUser.id)))
        .join(AdminUserRole, AdminUserRole.user_id == AdminUser.id)
        .join(AdminRole, AdminRole.id == AdminUserRole.role_id)
        .where(AdminRole.code == SUPER_ADMIN_ROLE, AdminUser.status == "active",
               AdminUser.tenant_id == ctx.runtime.tenant_id)
    ) or 0


# ---- accounts ----

@router.get("/accounts")
def list_accounts(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  ctx: AdminCtx = Depends(admin_read(PERM))):
    base = sa.select(AdminUser).where(AdminUser.tenant_id == ctx.runtime.tenant_id)
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(base.subquery()))
    users = ctx.db.scalars(base.order_by(AdminUser.id).offset((page - 1) * page_size).limit(page_size)).all()
    roles = _roles_of(ctx, [u.id for u in users])
    return {"items": [_user_view(u, roles.get(u.id, [])) for u in users], "total": total,
            "page": page, "page_size": page_size}


@router.post("/accounts")
def create_account(body: AccountCreateIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    check_strength(body.password, body.username, ctx.runtime.setting("security", "password_min_length"))
    with ctx.db.begin():
        exists = ctx.db.scalar(sa.select(AdminUser.id).where(
            AdminUser.tenant_id == ctx.runtime.tenant_id, AdminUser.username == body.username))
        if exists:
            raise AppError(409, "USERNAME_EXISTS", "用户名已存在")
        role_ids = _validate_roles(ctx, body.role_ids)
        u = AdminUser(tenant_id=ctx.runtime.tenant_id, username=body.username,
                      display_name=body.display_name or body.username, password_hash=hash_password(body.password))
        ctx.db.add(u)
        ctx.db.flush()
        _set_roles(ctx, u.id, role_ids)
        roles = _roles_of(ctx, [u.id]).get(u.id, [])
        ctx.audit("account.create", "admin_user", u.id, after=_user_summary(u, roles))
    return _user_view(u, roles)


@router.put("/accounts/{user_id}")
def update_account(user_id: int, body: AccountUpdateIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    with ctx.db.begin():
        u = _get_user(ctx, user_id)
        before_roles = _roles_of(ctx, [u.id]).get(u.id, [])
        before = _user_summary(u, before_roles)
        if u.id == ctx.user.id and body.status != "active":
            raise AppError(409, "CANNOT_DISABLE_SELF", "不能停用自己的账号")
        role_ids = _validate_roles(ctx, body.role_ids)
        u.display_name = body.display_name or u.username
        u.status = body.status
        _set_roles(ctx, u.id, role_ids)
        if _active_super_admins(ctx) == 0:
            raise AppError(409, "LAST_SUPER_ADMIN", "必须至少保留一个启用的超级管理员")
        roles = _roles_of(ctx, [u.id]).get(u.id, [])
        ctx.audit("account.update", "admin_user", u.id, before=before, after=_user_summary(u, roles))
    return _user_view(u, roles)


@router.post("/accounts/{user_id}/reset-password")
def reset_password(user_id: int, body: ResetPasswordIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    min_length = ctx.runtime.setting("security", "password_min_length")
    with ctx.db.begin():
        u = _get_user(ctx, user_id)
        check_strength(body.password, u.username, min_length)
        u.password_hash = hash_password(body.password)
        u.password_changed_at = utcnow()
        u.failed_count, u.locked_until = 0, None
        ctx.audit("account.password.reset", "admin_user", u.id, after="已变更")
    return {"ok": True}


@router.post("/accounts/{user_id}/unlock")
def unlock_account(user_id: int, ctx: AdminCtx = Depends(admin_write(PERM))):
    with ctx.db.begin():
        u = _get_user(ctx, user_id)
        u.failed_count, u.locked_until = 0, None
        ctx.audit("account.unlock", "admin_user", u.id)
    return {"ok": True}


# ---- roles & perms ----

@router.get("/perms")
def list_perms(ctx: AdminCtx = Depends(admin_read(PERM))):
    return {"items": [{"code": c, "label": label} for c, label in PERMISSIONS.items()]}


def _role_view(ctx: AdminCtx, r: AdminRole) -> dict:
    perms = sorted(PERMISSIONS) if r.code == SUPER_ADMIN_ROLE else sorted(
        ctx.db.scalars(sa.select(AdminRolePerm.perm_code).where(AdminRolePerm.role_id == r.id)).all())
    users = ctx.db.scalar(sa.select(sa.func.count()).where(AdminUserRole.role_id == r.id))
    return {"id": r.id, "code": r.code, "name": r.name, "description": r.description,
            "is_builtin": r.is_builtin, "perm_codes": perms, "user_count": users}


def _role_summary(view: dict) -> str:
    return json.dumps({k: view[k] for k in ("code", "name", "perm_codes")}, ensure_ascii=False)


def _get_role(ctx: AdminCtx, role_id: int) -> AdminRole:
    r = ctx.db.get(AdminRole, role_id)
    if r is None or r.tenant_id != ctx.runtime.tenant_id:
        raise AppError(404, "NOT_FOUND", "角色不存在")
    return r


def _check_perm_codes(codes: list[str]) -> list[str]:
    unknown = set(codes) - set(PERMISSIONS)
    if unknown:
        raise AppError(422, "VALIDATION_ERROR", f"未知权限点：{sorted(unknown)}")
    return sorted(set(codes))


def _set_perms(ctx: AdminCtx, role_id: int, codes: list[str]) -> None:
    ctx.db.execute(sa.delete(AdminRolePerm).where(AdminRolePerm.role_id == role_id))
    for c in codes:
        ctx.db.add(AdminRolePerm(role_id=role_id, perm_code=c))
    ctx.db.flush()


@router.get("/roles")
def list_roles(ctx: AdminCtx = Depends(admin_read(PERM))):
    rows = ctx.db.scalars(sa.select(AdminRole).where(AdminRole.tenant_id == ctx.runtime.tenant_id)
                          .order_by(AdminRole.id)).all()
    return {"items": [_role_view(ctx, r) for r in rows]}


@router.post("/roles")
def create_role(body: RoleIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    codes = _check_perm_codes(body.perm_codes)
    with ctx.db.begin():
        if ctx.db.scalar(sa.select(AdminRole.id).where(AdminRole.tenant_id == ctx.runtime.tenant_id,
                                                       AdminRole.code == body.code)):
            raise AppError(409, "CODE_EXISTS", "角色编码已存在")
        r = AdminRole(tenant_id=ctx.runtime.tenant_id, code=body.code, name=body.name, description=body.description)
        ctx.db.add(r)
        ctx.db.flush()
        _set_perms(ctx, r.id, codes)
        view = _role_view(ctx, r)
        ctx.audit("role.create", "admin_role", r.id, after=_role_summary(view))
    return view


@router.put("/roles/{role_id}")
def update_role(role_id: int, body: RoleIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    codes = _check_perm_codes(body.perm_codes)
    with ctx.db.begin():
        r = _get_role(ctx, role_id)
        if r.is_builtin:
            raise AppError(409, "BUILTIN_ROLE", "内置角色不可修改")
        before = _role_summary(_role_view(ctx, r))
        r.name, r.description = body.name, body.description
        _set_perms(ctx, r.id, codes)
        view = _role_view(ctx, r)
        ctx.audit("role.update", "admin_role", r.id, before=before, after=_role_summary(view))
    return view


@router.delete("/roles/{role_id}")
def delete_role(role_id: int, ctx: AdminCtx = Depends(admin_write(PERM))):
    with ctx.db.begin():
        r = _get_role(ctx, role_id)
        if r.is_builtin:
            raise AppError(409, "BUILTIN_ROLE", "内置角色不可删除")
        view = _role_view(ctx, r)
        if view["user_count"]:
            raise AppError(409, "ROLE_IN_USE", "仍有账号使用该角色，请先解除分配")
        ctx.db.execute(sa.delete(AdminRolePerm).where(AdminRolePerm.role_id == r.id))
        ctx.db.delete(r)
        ctx.audit("role.delete", "admin_role", role_id, before=_role_summary(view))
    return {"ok": True}
