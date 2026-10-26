"""/v1/admin/conversations：完整对话记录查看与训练导出。

内容只去掉了密钥类信息，含员工原话与业务数据，因此查看需要 ops.run.view_sensitive、
导出需要 ops.conversation.export，且每次访问都写审计（审计失败则请求失败）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from oa_agent.auth.rbac import AdminCtx, admin_read
from oa_agent.db.models import ConversationMessage, ModelCallLog, Run
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError

router = APIRouter(prefix="/v1/admin/conversations", tags=["admin-conversations"])

VIEW = "ops.run.view_sensitive"
EXPORT = "ops.conversation.export"
EXPORT_MAX_RANGE = timedelta(days=92)
EXPORT_MAX_MESSAGES = 50000


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def _message_view(m: ConversationMessage) -> dict:
    return {"message_id": m.message_id, "run_id": m.run_id, "role": m.role, "content": m.content,
            "reply_type": m.reply_type, "data": m.data_json, "error_code": m.error_code,
            "created_at": _iso(m.created_at)}


def _model_call_view(c: ModelCallLog) -> dict:
    return {"call_id": c.call_id, "run_id": c.run_id, "node_name": c.node_name, "provider": c.provider,
            "model": c.model, "messages": c.messages_json, "output_text": c.output_text, "parsed": c.parsed_json,
            "usage": c.usage_json, "status": c.status, "error_summary": c.error_summary,
            "duration_ms": c.duration_ms, "created_at": _iso(c.created_at)}


def _audit(ctx: AdminCtx, action: str, resource_id: str = "", **after) -> None:
    """查询已自动开启事务，审计随之提交；提交失败抛错，请求整体失败。"""
    detail = {k: v for k, v in after.items() if v is not None}
    ctx.audit(action, "conversation", resource_id,
              after=json.dumps(detail, ensure_ascii=False) if detail else None)
    ctx.db.commit()


@router.get("")
def list_threads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    oa: str | None = None,
    keyword: str | None = Query(None, max_length=100),
    start: datetime | None = None,
    end: datetime | None = None,
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    M = ConversationMessage
    cond = [M.tenant_id == ctx.runtime.tenant_id]
    if oa:
        cond.append(M.oa == oa.strip())
    if start:
        cond.append(M.created_at >= _aware(start))
    if end:
        cond.append(M.created_at < _aware(end))
    if keyword and keyword.strip():
        hits = sa.select(M.thread_id).where(M.tenant_id == ctx.runtime.tenant_id,
                                            M.content.contains(keyword.strip(), autoescape=True))
        cond.append(M.thread_id.in_(hits))
    grouped = (sa.select(M.thread_id, sa.func.max(M.oa).label("oa"), sa.func.max(M.channel).label("channel"),
                         sa.func.min(M.created_at).label("first_at"), sa.func.max(M.created_at).label("last_at"),
                         sa.func.count(M.id).label("message_count"))
               .where(*cond).group_by(M.thread_id))
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(grouped.subquery()))
    rows = ctx.db.execute(grouped.order_by(sa.desc("last_at")).offset((page - 1) * page_size).limit(page_size)).all()
    ids = [r.thread_id for r in rows]
    first_user: dict[str, str] = {}
    if ids:
        for m in ctx.db.scalars(sa.select(M).where(M.thread_id.in_(ids), M.role == "user").order_by(M.id)):
            first_user.setdefault(m.thread_id, m.content)
    _audit(ctx, "conversation.list", oa=oa, keyword=keyword, page=page, count=len(rows))
    return {"items": [{"thread_id": r.thread_id, "oa": r.oa, "channel": r.channel, "first_at": _iso(r.first_at),
                       "last_at": _iso(r.last_at), "message_count": r.message_count,
                       "first_message": (first_user.get(r.thread_id) or "")[:200]} for r in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/export")
def export(
    start: datetime,
    end: datetime,
    oa: str | None = None,
    ctx: AdminCtx = Depends(admin_read(EXPORT)),
):
    """按会话导出 JSONL：每行一个会话，含按时间排列的对话消息与模型调用原文。"""
    start, end = _aware(start), _aware(end)
    if start >= end:
        raise AppError(422, "VALIDATION_ERROR", "开始时间必须早于结束时间")
    cfg = ctx.runtime.settings_svc.effective(ctx.db, "runtime")
    max_days = int(cfg.get("export_max_days") or EXPORT_MAX_RANGE.days)
    max_messages = int(cfg.get("export_max_messages") or EXPORT_MAX_MESSAGES)
    if end - start > timedelta(days=max_days):
        raise AppError(422, "VALIDATION_ERROR", f"导出时间范围不能超过 {max_days} 天")
    M, C = ConversationMessage, ModelCallLog
    cond = [M.tenant_id == ctx.runtime.tenant_id, M.created_at >= start, M.created_at < end]
    if oa:
        cond.append(M.oa == oa.strip())
    count = ctx.db.scalar(sa.select(sa.func.count()).where(*cond))
    if count > max_messages:
        raise AppError(422, "EXPORT_TOO_LARGE", f"该范围内有 {count} 条消息，超过单次上限 {max_messages}，请缩小时间范围")
    threads: dict[str, dict] = {}
    for m in ctx.db.scalars(sa.select(M).where(*cond).order_by(M.id)):
        t = threads.setdefault(m.thread_id, {"thread_id": m.thread_id, "oa": m.oa, "channel": m.channel,
                                             "messages": [], "model_calls": []})
        t["messages"].append(_message_view(m))
    if threads:
        run_ids = {msg["run_id"] for t in threads.values() for msg in t["messages"]}
        for c in ctx.db.scalars(sa.select(C).where(C.run_id.in_(run_ids)).order_by(C.id)):
            if c.thread_id in threads:
                threads[c.thread_id]["model_calls"].append(_model_call_view(c))
    _audit(ctx, "conversation.export", start=start.isoformat(), end=end.isoformat(), oa=oa,
           threads=len(threads), messages=count)
    body = "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in threads.values())
    name = f"conversations_{start:%Y%m%d}_{end:%Y%m%d}.jsonl"
    return Response(body, media_type="application/x-ndjson; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/{thread_id}")
def thread_detail(thread_id: str, ctx: AdminCtx = Depends(admin_read(VIEW))):
    M, C = ConversationMessage, ModelCallLog
    messages = ctx.db.scalars(sa.select(M).where(M.tenant_id == ctx.runtime.tenant_id, M.thread_id == thread_id)
                              .order_by(M.id)).all()
    calls = ctx.db.scalars(sa.select(C).where(C.tenant_id == ctx.runtime.tenant_id, C.thread_id == thread_id)
                           .order_by(C.id)).all()
    if not messages and not calls:
        raise AppError(404, "NOT_FOUND", "没有该会话的对话记录")
    run_ids = {m.run_id for m in messages} | {c.run_id for c in calls}
    statuses = dict(ctx.db.execute(sa.select(Run.run_id, Run.run_status).where(Run.run_id.in_(run_ids))).all())
    _audit(ctx, "conversation.view", thread_id)
    first = messages[0] if messages else None
    return {"thread_id": thread_id, "oa": first.oa if first else calls[0].oa,
            "channel": first.channel if first else "", "generated_at": utcnow().isoformat(),
            "messages": [_message_view(m) for m in messages], "model_calls": [_model_call_view(c) for c in calls],
            "run_status": statuses}
