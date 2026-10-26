"""/v1/admin/audit：审计查询（只读）。"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query

from oa_agent.auth.rbac import AdminCtx, admin_read
from oa_agent.db.models import AuditLog

router = APIRouter(prefix="/v1/admin", tags=["admin-audit"])


@router.get("/audit")
def query_audit(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    actor_id: str | None = None,
    resource_type: str | None = None,
    result: str | None = None,
    start: datetime | None = Query(None, description="ISO8601，含时区"),
    end: datetime | None = None,
    ctx: AdminCtx = Depends(admin_read("ops.audit.view")),
):
    q = sa.select(AuditLog).where(AuditLog.tenant_id == ctx.runtime.tenant_id)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if resource_type:
        q = q.where(AuditLog.resource_type == resource_type)
    if result:
        q = q.where(AuditLog.result == result)
    if start:
        q = q.where(AuditLog.occurred_at >= (start if start.tzinfo else start.replace(tzinfo=UTC)))
    if end:
        q = q.where(AuditLog.occurred_at < (end if end.tzinfo else end.replace(tzinfo=UTC)))
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [
        {c: getattr(r, c) for c in (
            "audit_id", "actor_type", "actor_id", "action", "resource_type", "resource_id", "before_summary",
            "after_summary", "result", "reason", "occurred_at", "request_id", "source_ip")}
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
