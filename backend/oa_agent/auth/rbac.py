"""管理端鉴权依赖：会话 → 权限点 → CSRF → Idempotency-Key。"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field

import sqlalchemy as sa
from fastapi import Request
from sqlalchemy.orm import Session

from oa_agent.auth.perms import PERMISSIONS, SUPER_ADMIN_ROLE
from oa_agent.auth.sessions import COOKIE_NAME, AdminSessionStore
from oa_agent.db.models import AdminRole, AdminRolePerm, AdminUser, AdminUserRole
from oa_agent.errors import AppError
from oa_agent.observability.audit import AuditMeta
from oa_agent.runtime_state import AppRuntime, get_runtime

IDEMPOTENCY_TTL = 3


def request_meta(request: Request) -> AuditMeta:
    rid = getattr(request.state, "request_id", "")
    return AuditMeta(
        request_id=rid,
        source_ip=request.client.host if request.client else "",
        correlation_id=rid,
    )


def load_perms(db: Session, user_id: int) -> tuple[set[str], list[str]]:
    rows = db.execute(
        sa.select(AdminRole.code, AdminRolePerm.perm_code)
        .join(AdminUserRole, AdminUserRole.role_id == AdminRole.id)
        .outerjoin(AdminRolePerm, AdminRolePerm.role_id == AdminRole.id)
        .where(AdminUserRole.user_id == user_id)
    ).all()
    roles = sorted({r.code for r in rows})
    if SUPER_ADMIN_ROLE in roles:
        return set(PERMISSIONS), roles
    return {r.perm_code for r in rows if r.perm_code}, roles


@dataclass
class AdminCtx:
    runtime: AppRuntime
    user: AdminUser
    perms: set[str]
    roles: list[str]
    sid: str
    csrf: str
    meta: AuditMeta
    db: Session = field(default=None)  # type: ignore[assignment]

    def audit(self, action: str, resource_type: str = "", resource_id: str = "", *, before=None, after=None,
              result: str = "success", reason: str = "") -> str:
        return self.runtime.audit.record(
            self.db,
            actor_type="admin",
            actor_id=self.user.username,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            before=before,
            after=after,
            result=result,
            reason=reason,
            meta=self.meta,
        )


def authenticate(request: Request) -> AdminCtx:
    rt = get_runtime(request)
    sid = request.cookies.get(COOKIE_NAME)
    store = AdminSessionStore.for_runtime(rt)
    data = store.get(sid)
    if data is None:
        raise AppError(401, "UNAUTHENTICATED", "未登录或会话已过期")
    with rt.session() as db:
        user = db.get(AdminUser, data["user_id"])
        if user is None or user.status != "active":
            store.delete(sid)
            raise AppError(401, "UNAUTHENTICATED", "账号不可用，请重新登录")
        perms, roles = load_perms(db, user.id)
    return AdminCtx(rt, user, perms, roles, sid, data["csrf"], request_meta(request))


def _deny(ctx: AdminCtx, request: Request, missing: list[str]) -> None:
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        with ctx.runtime.session() as db, db.begin():
            ctx.db = db
            ctx.audit("access.denied", "api", request.url.path, result="denied", reason=",".join(missing))
    raise AppError(403, "FORBIDDEN", f"无权限：{', '.join(missing)}")


def _check_csrf(ctx: AdminCtx, request: Request) -> None:
    token = request.headers.get("X-CSRF-Token", "")
    if not token or not hmac.compare_digest(token, ctx.csrf):
        raise AppError(403, "CSRF_FAILED", "CSRF 校验失败，请刷新页面后重试")


def _check_idempotency(ctx: AdminCtx, request: Request) -> None:
    key = request.headers.get("Idempotency-Key", "")
    if not key or len(key) > 128:
        raise AppError(400, "IDEMPOTENCY_KEY_REQUIRED", "缺少或非法的 Idempotency-Key")
    ttl = int(ctx.runtime.setting("security", "idempotency_seconds")) if hasattr(ctx.runtime, "setting") \
        else IDEMPOTENCY_TTL
    if not ctx.runtime.kv.current.set_nx(f"idem:{ctx.user.id}:{key}", "1", ttl):
        raise AppError(409, "DUPLICATE_REQUEST", "重复提交，请稍后再试")


def _guard(perms: tuple[str, ...], write: bool):
    def dependency(request: Request):
        ctx = authenticate(request)
        missing = [p for p in perms if p not in ctx.perms]
        if missing:
            _deny(ctx, request, missing)
        if write:
            _check_csrf(ctx, request)
            _check_idempotency(ctx, request)
        db = ctx.runtime.session()
        ctx.db = db
        try:
            yield ctx
        finally:
            db.close()

    return dependency


def admin_read(*perms: str):
    return _guard(perms, write=False)


def admin_read_any(*perms: str):
    """只读接口拥有任一权限即可访问。"""
    def dependency(request: Request):
        ctx = authenticate(request)
        if perms and ctx.perms.isdisjoint(perms):
            _deny(ctx, request, [" 或 ".join(perms)])
        db = ctx.runtime.session()
        ctx.db = db
        try:
            yield ctx
        finally:
            db.close()

    return dependency


def admin_write(*perms: str):
    return _guard(perms, write=True)
