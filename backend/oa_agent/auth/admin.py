"""/v1/admin/auth/*：本地账号登录、登出、改密（设计 §6.3）。"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from oa_agent.auth.passwords import burn_verify, check_strength, hash_password, verify_password
from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write, load_perms, request_meta
from oa_agent.auth.sessions import COOKIE_NAME, AdminSessionStore
from oa_agent.db.models import AdminUser
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.runtime_state import get_runtime

router = APIRouter(prefix="/v1/admin/auth", tags=["admin-auth"])

MAX_FAILURES = 5
LOCK_MINUTES = 15
IP_WINDOW = 15 * 60
IP_MAX_FAILURES = 30
BAD_CREDENTIALS = "用户名或密码错误"


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def _me(ctx: AdminCtx) -> dict:
    return {
        "user": {"id": ctx.user.id, "username": ctx.user.username, "display_name": ctx.user.display_name},
        "roles": ctx.roles,
        "perms": sorted(ctx.perms),
        "csrf_token": ctx.csrf,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    rt = get_runtime(request)
    meta = request_meta(request)
    cfg = rt.group_settings("security")
    max_failures = int(cfg.get("login_max_failures") or MAX_FAILURES)
    lock_minutes = int(cfg.get("login_lock_minutes") or LOCK_MINUTES)
    ip_window = int(cfg.get("ip_window_minutes") or IP_WINDOW // 60) * 60
    ip_max_failures = int(cfg.get("ip_max_failures") or IP_MAX_FAILURES)
    ip_key = f"adm:loginfail:{meta.source_ip}"
    if int(rt.kv.current.get(ip_key) or 0) >= ip_max_failures:
        raise AppError(429, "TOO_MANY_ATTEMPTS", "登录失败次数过多，请稍后再试")

    now = utcnow()
    with rt.session() as db, db.begin():
        user = db.scalar(
            sa.select(AdminUser).where(AdminUser.tenant_id == rt.tenant_id, AdminUser.username == body.username)
        )

        def fail(reason: str, status: int = 401, code: str = "BAD_CREDENTIALS", message: str = BAD_CREDENTIALS):
            rt.kv.current.incr(ip_key, ip_window)
            rt.audit.record(db, actor_type="admin", actor_id=body.username, action="admin.login",
                            resource_type="admin_user", resource_id=str(user.id) if user else "",
                            result="failure", reason=reason, meta=meta)
            return AppError(status, code, message)

        if user is None:
            burn_verify(body.password)
            err = fail("用户不存在")
        elif user.locked_until and user.locked_until > now:
            minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
            err = fail("账号锁定中", 423, "ACCOUNT_LOCKED", f"账号已锁定，请约 {minutes} 分钟后再试")
        elif not verify_password(user.password_hash, body.password):
            user.failed_count += 1
            if user.failed_count >= max_failures:
                user.locked_until = now + timedelta(minutes=lock_minutes)
                user.failed_count = 0
                err = fail("密码错误，已锁定", 423, "ACCOUNT_LOCKED", f"连续失败 {max_failures} 次，账号锁定 {lock_minutes} 分钟")
            else:
                err = fail("密码错误")
        elif user.status != "active":
            err = fail("账号已停用", 403, "ACCOUNT_DISABLED", "账号已停用")
        else:
            err = None
            user.failed_count = 0
            user.locked_until = None
            user.last_login_at = now
            rt.audit.record(db, actor_type="admin", actor_id=user.username, action="admin.login",
                            resource_type="admin_user", resource_id=str(user.id), meta=meta)
            user_id = user.id
    if err is not None:
        raise err

    store = AdminSessionStore.for_runtime(rt)
    sid, csrf = store.create(user_id)
    response.set_cookie(
        COOKIE_NAME,
        sid,
        max_age=store.absolute_ttl,
        httponly=True,
        secure=rt.settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    with rt.session() as db:
        user = db.get(AdminUser, user_id)
        perms, roles = load_perms(db, user_id)
    return _me(AdminCtx(rt, user, perms, roles, sid, csrf, meta))


@router.get("/me")
def me(ctx: AdminCtx = Depends(admin_read())):
    return _me(ctx)


@router.post("/logout")
def logout(response: Response, ctx: AdminCtx = Depends(admin_write())):
    with ctx.db.begin():
        ctx.audit("admin.logout", "admin_user", ctx.user.id)
    AdminSessionStore.for_runtime(ctx.runtime).delete(ctx.sid)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordIn, ctx: AdminCtx = Depends(admin_write())):
    min_length = ctx.runtime.setting("security", "password_min_length")
    with ctx.db.begin():
        user = ctx.db.get(AdminUser, ctx.user.id)
        if not verify_password(user.password_hash, body.old_password):
            raise AppError(400, "BAD_CREDENTIALS", "原密码错误")
        check_strength(body.new_password, user.username, min_length)
        user.password_hash = hash_password(body.new_password)
        user.password_changed_at = utcnow()
        ctx.audit("admin.password.change", "admin_user", user.id, after="已变更")
    return {"ok": True}
