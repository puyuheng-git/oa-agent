"""/v1/admin/employees：员工目录与会话 Tab（设"M4 / Task G2–G3）"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.chat import memory_store as ms
from oa_agent.chat import threads as th
from oa_agent.chat.service import _skills_with_tools, visible_skills_for
from oa_agent.db.models import ChatThread, ConversationMessage, EmployeeMemory, Run, Skill
from oa_agent.errors import AppError
from oa_agent.executor.visibility import PrincipalContext, VisibilityService

router = APIRouter(prefix="/v1/admin/employees", tags=["admin-employees"])

VIEW = "ops.employee.view"
SENSITIVE = "ops.employee.sensitive"
MANAGE = "ops.employee.manage"

_ALL_THREAD_STATUSES = {th.STATUS_ACTIVE, th.STATUS_ARCHIVED, th.STATUS_DELETED}


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def _oa_union(tenant_id: str) -> sa.Subquery:
    T, M, R = ChatThread, EmployeeMemory, Run
    tid = T.tenant_id == tenant_id
    return sa.union(
        sa.select(T.oa.label("oa")).where(tid),
        sa.select(M.oa.label("oa")).where(M.tenant_id == tenant_id),
        sa.select(R.oa.label("oa")).where(R.tenant_id == tenant_id),
    ).subquery()


def _last_active_subq(tenant_id: str) -> sa.Subquery:
    T, M, R = ChatThread, EmployeeMemory, Run
    tid = T.tenant_id == tenant_id
    activity = sa.union_all(
        sa.select(T.oa.label("oa"), sa.func.coalesce(T.last_message_at, T.updated_at).label("ts")).where(tid),
        sa.select(M.oa, M.updated_at).where(M.tenant_id == tenant_id),
        sa.select(R.oa, sa.func.coalesce(R.last_event_at, R.started_at)).where(R.tenant_id == tenant_id),
    ).subquery()
    return (
        sa.select(activity.c.oa, sa.func.max(activity.c.ts).label("last_active_at"))
        .group_by(activity.c.oa)
        .subquery()
    )


def _thread_counts(tenant_id: str) -> sa.Subquery:
    T = ChatThread
    return (
        sa.select(T.oa, sa.func.count().label("thread_count"))
        .where(T.tenant_id == tenant_id)
        .group_by(T.oa)
        .subquery()
    )


def _memory_active_counts(tenant_id: str) -> sa.Subquery:
    M = EmployeeMemory
    return (
        sa.select(M.oa, sa.func.count().label("memory_active_count"))
        .where(M.tenant_id == tenant_id, M.status == "active")
        .group_by(M.oa)
        .subquery()
    )


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


class ThreadPatchIn(ReasonIn):
    title: str | None = Field(default=None, max_length=200)
    status: Literal["active", "archived"] | None = None


class RestoreIn(ReasonIn):
    status: Literal["active", "archived"] = "active"


class BatchIn(ReasonIn):
    action: Literal["archive", "soft_delete"]
    thread_ids: list[str] = Field(min_length=1, max_length=100)


class MemoryCreateIn(ReasonIn):
    kind: Literal["preference", "constraint", "note"]
    text: str = Field(min_length=1, max_length=200)


class MemoryPatchIn(ReasonIn):
    kind: Literal["preference", "constraint", "note"] | None = None
    text: str | None = Field(default=None, min_length=1, max_length=200)


class MemoryClearIn(ReasonIn):
    confirm: Literal[True]


class VisibilityGrantIn(ReasonIn):
    skill_name: str = Field(min_length=1, max_length=128)
    effect: Literal["allow", "deny"]


class VisibilityGrantDeleteIn(ReasonIn):
    skill_name: str = Field(min_length=1, max_length=128)
    effect: Literal["allow", "deny"] | None = None


class VisibilityGrantBatchIn(ReasonIn):
    skill_names: list[str] = Field(min_length=1, max_length=50)
    effect: Literal["allow", "deny"]


def _get_skill(ctx: AdminCtx, name: str) -> Skill:
    skill = ctx.db.scalar(
        sa.select(Skill).where(Skill.tenant_id == ctx.runtime.tenant_id, Skill.name == name)
    )
    if skill is None:
        raise AppError(404, "NOT_FOUND", "Skill 不存")
    return skill


def _employee_visibility_preview(ctx: AdminCtx, oa: str) -> dict:
    oa = oa.strip()
    skills = _skills_with_tools(ctx.runtime)
    visible_states = visible_skills_for(ctx.runtime, oa, office_token="")
    visible_names = {s.name for s in visible_states}
    by_name = {s.name: s for s in skills}
    principal = PrincipalContext(oa=oa, tags=[])
    tenant_id = ctx.runtime.tenant_id

    name_to_id: dict[str, int] = {}
    if skills:
        rows = ctx.db.scalars(
            sa.select(Skill).where(
                Skill.tenant_id == tenant_id,
                Skill.name.in_([s.name for s in skills]),
            )
        ).all()
        name_to_id = {row.name: row.id for row in rows}

    visible = [
        {"name": s.name, "display_name": s.display_name}
        for s in visible_states
    ]
    hidden: list[dict] = []
    for name, state in sorted(by_name.items()):
        if name in visible_names:
            continue
        sid = name_to_id.get(name)
        reason = (
            VisibilityService.hidden_reason(
                ctx.db, tenant_id=tenant_id, skill_id=sid, principal=principal
            )
            if sid is not None
            else "no_allow"
        )
        hidden.append({"name": name, "reason": reason or "no_allow"})

    return {"visible": visible, "hidden": hidden}


def _require_thread(ctx: AdminCtx, oa: str, thread_id: str) -> ChatThread:
    row = th.get_owned(
        ctx.db,
        thread_id=thread_id,
        oa=oa,
        tenant_id=ctx.runtime.tenant_id,
        allow_statuses=_ALL_THREAD_STATUSES,
    )
    if row is None:
        raise AppError(404, "THREAD_NOT_FOUND", "会话不存")
    return row


def _audit_sensitive(ctx: AdminCtx, *, oa: str, thread_id: str) -> None:
    detail = {"oa": oa, "thread_id": thread_id}
    ctx.audit(
        "employee.sensitive.read",
        "employee",
        thread_id,
        after=json.dumps(detail, ensure_ascii=False),
    )
    ctx.db.commit()


def _audit_sensitive_memory(ctx: AdminCtx, *, oa: str) -> None:
    detail = {"oa": oa, "scope": "memory"}
    ctx.audit(
        "employee.sensitive.read",
        "employee",
        oa,
        after=json.dumps(detail, ensure_ascii=False),
    )
    ctx.db.commit()


def _memory_view(row: EmployeeMemory, *, include_text: bool) -> dict:
    item = {
        "memory_id": row.memory_id,
        "kind": row.kind,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "text": row.text if include_text else None,
    }
    return item


def _memory_detail(row: EmployeeMemory) -> dict:
    return {
        "memory_id": row.memory_id,
        "kind": row.kind,
        "status": row.status,
        "text": row.text,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _memory_audit_summary(row: EmployeeMemory) -> dict:
    return {"memory_id": row.memory_id, "kind": row.kind, "status": row.status}


def _message_item(m: ConversationMessage) -> dict:
    ts = m.created_at
    if ts is not None and getattr(ts, "tzinfo", None) is None:
        created_at = ts.isoformat() + "Z"
    else:
        created_at = ts.isoformat() if ts else None
    return {
        "message_id": m.message_id,
        "role": m.role,
        "content": m.content,
        "reply_type": m.reply_type,
        "data": m.data_json,
        "error_code": m.error_code,
        "created_at": created_at,
        "run_id": m.run_id,
    }


@router.get("")
def list_employees(
    q: str = Query("", max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    """列出本租户有痕迹"oa；`q` 非空时按 oa 前缀匹配（SQL `LIKE q%`）"""
    tenant_id = ctx.runtime.tenant_id
    oas = _oa_union(tenant_id)
    last_active = _last_active_subq(tenant_id)
    threads = _thread_counts(tenant_id)
    memories = _memory_active_counts(tenant_id)

    base = (
        sa.select(
            oas.c.oa,
            last_active.c.last_active_at,
            sa.func.coalesce(threads.c.thread_count, 0).label("thread_count"),
            sa.func.coalesce(memories.c.memory_active_count, 0).label("memory_active_count"),
        )
        .select_from(oas)
        .outerjoin(last_active, last_active.c.oa == oas.c.oa)
        .outerjoin(threads, threads.c.oa == oas.c.oa)
        .outerjoin(memories, memories.c.oa == oas.c.oa)
    )
    needle = q.strip()
    if needle:
        base = base.where(oas.c.oa.startswith(needle))

    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(base.subquery()))
    order = (sa.desc(sa.func.coalesce(last_active.c.last_active_at, datetime.min.replace(tzinfo=UTC))),
             oas.c.oa.asc())
    rows = ctx.db.execute(base.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [{"oa": r.oa, "last_active_at": _iso(r.last_active_at), "thread_count": int(r.thread_count),
                   "memory_active_count": int(r.memory_active_count)} for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{oa}/threads")
def list_employee_threads(
    oa: str,
    status: Literal["active", "archived", "deleted"] = Query("active"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    offset = (page - 1) * page_size
    rows, total = th.list_threads(
        ctx.db,
        oa=oa,
        status=status,
        tenant_id=ctx.runtime.tenant_id,
        limit=page_size,
        offset=offset,
    )
    return {
        "items": [th.thread_view(t) for t in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{oa}/threads/{thread_id}/messages")
def list_employee_thread_messages(
    oa: str,
    thread_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AdminCtx = Depends(admin_read(SENSITIVE)),
):
    _require_thread(ctx, oa, thread_id)
    offset = (page - 1) * page_size
    base = sa.select(ConversationMessage).where(
        ConversationMessage.tenant_id == ctx.runtime.tenant_id,
        ConversationMessage.thread_id == thread_id,
        ConversationMessage.oa == oa,
    )
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = ctx.db.scalars(
        base.order_by(ConversationMessage.id.asc()).offset(offset).limit(page_size)
    ).all()
    _audit_sensitive(ctx, oa=oa, thread_id=thread_id)
    return {
        "items": [_message_item(m) for m in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.patch("/{oa}/threads/{thread_id}")
def patch_employee_thread(
    oa: str,
    thread_id: str,
    body: ThreadPatchIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        row = _require_thread(ctx, oa, thread_id)
        before = th.thread_view(row)
        if body.title is None and body.status is None:
            raise AppError(422, "VALIDATION_ERROR", "至少提供 title 或 status")
        th.patch_thread(ctx.db, row, title=body.title, status=body.status)
        after = th.thread_view(row)
        ctx.audit(
            "employee.thread.update",
            "employee",
            thread_id,
            before=before,
            after=after,
            reason=body.reason,
        )
    return after


@router.delete("/{oa}/threads/{thread_id}")
def delete_employee_thread(
    oa: str,
    thread_id: str,
    body: ReasonIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        row = _require_thread(ctx, oa, thread_id)
        before = th.thread_view(row)
        th.soft_delete(ctx.db, row)
        after = th.thread_view(row)
        ctx.audit(
            "employee.thread.delete",
            "employee",
            thread_id,
            before=before,
            after=after,
            reason=body.reason,
        )
    return {"ok": True, "thread_id": thread_id, "status": after["status"]}


@router.post("/{oa}/threads/{thread_id}/restore")
def restore_employee_thread(
    oa: str,
    thread_id: str,
    body: RestoreIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        row = _require_thread(ctx, oa, thread_id)
        before = th.thread_view(row)
        th.restore_thread(ctx.db, row, status=body.status)
        after = th.thread_view(row)
        ctx.audit(
            "employee.thread.restore",
            "employee",
            thread_id,
            before=before,
            after=after,
            reason=body.reason,
        )
    return after


@router.post("/{oa}/threads/batch")
def batch_employee_threads(
    oa: str,
    body: BatchIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    seen: set[str] = set()
    for tid in body.thread_ids:
        if tid in seen:
            raise AppError(422, "VALIDATION_ERROR", "thread_ids 不可重复")
        seen.add(tid)

    updated: list[str] = []
    with ctx.db.begin():
        for tid in body.thread_ids:
            row = _require_thread(ctx, oa, tid)
            if body.action == "archive":
                th.patch_thread(ctx.db, row, status=th.STATUS_ARCHIVED)
            else:
                th.soft_delete(ctx.db, row)
            updated.append(tid)
        ctx.audit(
            "employee.thread.batch",
            "employee",
            oa,
            after={"action": body.action, "thread_ids": updated, "count": len(updated)},
            reason=body.reason,
        )
    return {"ok": True, "action": body.action, "count": len(updated), "thread_ids": updated}


@router.get("/{oa}/memory")
def list_employee_memory(
    oa: str,
    status: Literal["active", "deleted"] = Query("active"),
    include_text: int = Query(0, ge=0, le=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    if include_text and SENSITIVE not in ctx.perms:
        raise AppError(403, "FORBIDDEN", f"无权限：{SENSITIVE}")
    offset = (page - 1) * page_size
    rows, total = ms.list_by_status(
        ctx.db,
        tenant_id=ctx.runtime.tenant_id,
        oa=oa,
        status=status,
        limit=page_size,
        offset=offset,
    )
    if include_text:
        _audit_sensitive_memory(ctx, oa=oa)
    return {
        "items": [_memory_view(r, include_text=bool(include_text)) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/{oa}/memory")
def create_employee_memory(
    oa: str,
    body: MemoryCreateIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        row = ms.add_memory(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            kind=body.kind,
            text=body.text,
        )
        detail = _memory_detail(row)
        ctx.audit(
            "employee.memory.create",
            "employee",
            row.memory_id,
            after=_memory_audit_summary(row),
            reason=body.reason,
        )
    return detail


@router.patch("/{oa}/memory/{memory_id}")
def patch_employee_memory(
    oa: str,
    memory_id: str,
    body: MemoryPatchIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        before_row = ms.get_memory(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            memory_id=memory_id,
            statuses=frozenset({ms.STATUS_ACTIVE}),
        )
        if before_row is None:
            raise AppError(404, "MEMORY_NOT_FOUND", "记忆不存")
        row = ms.update_memory(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            memory_id=memory_id,
            kind=body.kind,
            text=body.text,
        )
        detail = _memory_detail(row)
        ctx.audit(
            "employee.memory.update",
            "employee",
            memory_id,
            before=_memory_audit_summary(before_row),
            after=_memory_audit_summary(row),
            reason=body.reason,
        )
    return detail


@router.delete("/{oa}/memory/{memory_id}")
def delete_employee_memory(
    oa: str,
    memory_id: str,
    body: ReasonIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        before_row = ms.get_memory(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            memory_id=memory_id,
            statuses=frozenset({ms.STATUS_ACTIVE}),
        )
        if before_row is None:
            raise AppError(404, "MEMORY_NOT_FOUND", "记忆不存")
        ms.soft_delete(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            memory_id=memory_id,
        )
        ctx.audit(
            "employee.memory.delete",
            "employee",
            memory_id,
            before=_memory_audit_summary(before_row),
            after={**_memory_audit_summary(before_row), "status": ms.STATUS_DELETED},
            reason=body.reason,
        )
    return {"ok": True, "memory_id": memory_id, "status": ms.STATUS_DELETED}


@router.post("/{oa}/memory/{memory_id}/restore")
def restore_employee_memory(
    oa: str,
    memory_id: str,
    body: ReasonIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        before_row = ms.get_memory(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            memory_id=memory_id,
            statuses=frozenset({ms.STATUS_DELETED}),
        )
        if before_row is None:
            raise AppError(404, "MEMORY_NOT_FOUND", "记忆不存")
        row = ms.restore_memory(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            oa=oa,
            memory_id=memory_id,
        )
        assert row is not None
        detail = _memory_detail(row)
        ctx.audit(
            "employee.memory.restore",
            "employee",
            memory_id,
            before=_memory_audit_summary(before_row),
            after=_memory_audit_summary(row),
            reason=body.reason,
        )
    return detail


@router.delete("/{oa}/memory")
def clear_employee_memory(
    oa: str,
    body: MemoryClearIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    with ctx.db.begin():
        deleted = ms.clear_all(ctx.db, tenant_id=ctx.runtime.tenant_id, oa=oa)
        ctx.audit(
            "employee.memory.clear",
            "employee",
            oa,
            after={"oa": oa, "deleted": deleted},
            reason=body.reason,
        )
    return {"ok": True, "deleted": deleted}


@router.get("/{oa}/visibility")
def get_employee_visibility(oa: str, ctx: AdminCtx = Depends(admin_read(VIEW))):
    if not oa.strip():
        raise AppError(422, "VALIDATION_ERROR", "oa 不能为空")
    return _employee_visibility_preview(ctx, oa)


@router.post("/{oa}/visibility/grants/batch")
def batch_employee_visibility_grants(
    oa: str,
    body: VisibilityGrantBatchIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    path_oa = oa.strip()
    if not path_oa:
        raise AppError(422, "VALIDATION_ERROR", "oa 不能为空")
    seen: set[str] = set()
    for name in body.skill_names:
        if name in seen:
            raise AppError(422, "VALIDATION_ERROR", "skill_names 不可重复")
        seen.add(name)

    created = 0
    with ctx.db.begin():
        for skill_name in body.skill_names:
            skill = _get_skill(ctx, skill_name)
            try:
                if VisibilityService.add_oa_grant(
                    ctx.db,
                    tenant_id=ctx.runtime.tenant_id,
                    skill_id=skill.id,
                    oa=path_oa,
                    effect=body.effect,
                    created_by=ctx.user.username,
                ):
                    created += 1
            except ValueError as exc:
                raise AppError(422, "VALIDATION_ERROR", str(exc)) from None
        ctx.audit(
            "employee.visibility.grant",
            "employee",
            path_oa,
            after={
                "oa": path_oa,
                "effect": body.effect,
                "skill_names": list(body.skill_names),
                "created": created,
            },
            reason=body.reason,
        )
    return {"ok": True, "oa": path_oa, "effect": body.effect, "created": created}


@router.post("/{oa}/visibility/grants")
def add_employee_visibility_grant(
    oa: str,
    body: VisibilityGrantIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    path_oa = oa.strip()
    if not path_oa:
        raise AppError(422, "VALIDATION_ERROR", "oa 不能为空")
    with ctx.db.begin():
        skill = _get_skill(ctx, body.skill_name)
        try:
            inserted = VisibilityService.add_oa_grant(
                ctx.db,
                tenant_id=ctx.runtime.tenant_id,
                skill_id=skill.id,
                oa=path_oa,
                effect=body.effect,
                created_by=ctx.user.username,
            )
        except ValueError as exc:
            raise AppError(422, "VALIDATION_ERROR", str(exc)) from None
        ctx.audit(
            "employee.visibility.grant",
            "employee",
            path_oa,
            after={
                "oa": path_oa,
                "skill_name": body.skill_name,
                "effect": body.effect,
                "inserted": inserted,
            },
            reason=body.reason,
        )
    return {
        "ok": True,
        "oa": path_oa,
        "skill_name": body.skill_name,
        "effect": body.effect,
        "inserted": inserted,
    }


@router.delete("/{oa}/visibility/grants")
def remove_employee_visibility_grant(
    oa: str,
    body: VisibilityGrantDeleteIn,
    ctx: AdminCtx = Depends(admin_write(MANAGE)),
):
    path_oa = oa.strip()
    if not path_oa:
        raise AppError(422, "VALIDATION_ERROR", "oa 不能为空")
    with ctx.db.begin():
        skill = _get_skill(ctx, body.skill_name)
        try:
            removed = VisibilityService.remove_oa_grant(
                ctx.db,
                tenant_id=ctx.runtime.tenant_id,
                skill_id=skill.id,
                oa=path_oa,
                effect=body.effect,
            )
        except ValueError as exc:
            raise AppError(422, "VALIDATION_ERROR", str(exc)) from None
        ctx.audit(
            "employee.visibility.grant",
            "employee",
            path_oa,
            after={
                "oa": path_oa,
                "skill_name": body.skill_name,
                "effect": body.effect,
                "removed": removed,
            },
            reason=body.reason,
        )
    return {
        "ok": True,
        "oa": path_oa,
        "skill_name": body.skill_name,
        "removed": removed,
    }
