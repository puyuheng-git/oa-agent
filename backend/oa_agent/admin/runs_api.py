"""/v1/admin/runs：运行监控（只读，设计 §9 ops.run.view / §12）。

摘要字段在写入时已统一 redact；这里不返回任何未脱敏内容。取消/恢复/重试属于 P3。
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.chat.service import after_cancel, cancel_run, employee_session, retry_run
from oa_agent.db.models import InterventionTask, Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.ids import new_run_id
from oa_agent.observability.run_stats import (
    ALL_STATUSES, P95_MIN_SAMPLES, compute_stats, run_duration_ms, top_errors,
)
from oa_agent.runtime.intervention import InterventionService
from oa_agent.runtime.run_service import FAILED, RUNNING, TERMINAL, TIMED_OUT, WAITING_HUMAN, StaleState

router = APIRouter(prefix="/v1/admin/runs", tags=["admin-runs"])

VIEW = "ops.run.view"
OPERATE = "ops.run.operate"
RETRYABLE = (FAILED, TIMED_OUT)
MAX_RANGE = timedelta(days=92)
DEFAULT_RANGE = timedelta(hours=24)
STATS_CACHE_SECONDS = 30
EVENT_PAGE_MAX = 500

RUN_FIELDS = ("run_id", "thread_id", "oa", "channel", "agent_id", "workflow_id", "workflow_version",
              "config_release_id", "run_status", "started_at", "ended_at", "last_event_at", "error_code",
              "error_summary", "failed_node", "tool_call_count", "model_call_count", "business_type",
              "business_record_id")
EVENT_FIELDS = ("event_id", "seq", "event_type", "node_name", "status", "occurred_at", "duration_ms", "tool_name",
                "tool_version", "correlation_id", "error_code", "error_summary", "input_summary", "output_summary",
                "retry_count", "operator_id", "metadata_json")

_stats_lock = threading.Lock()


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = _aware(end) or utcnow()
    start = _aware(start) or end - DEFAULT_RANGE
    if start >= end:
        raise AppError(422, "VALIDATION_ERROR", "开始时间必须早于结束时间")
    if end - start > MAX_RANGE:
        raise AppError(422, "VALIDATION_ERROR", "时间范围不能超过 92 天")
    return start, end


def _stuck_threshold(ctx: AdminCtx) -> int:
    rt = ctx.runtime
    return int(rt.settings_svc.effective(ctx.db, "runtime").get("stuck_threshold_seconds") or 30)


def _run_view(run: Run, now: datetime, stuck_seconds: int) -> dict:
    out = {f: getattr(run, f) for f in RUN_FIELDS}
    out["duration_ms"] = run_duration_ms(run)
    out["suspected_stuck"] = (run.run_status == RUNNING
                              and (run.last_event_at or run.started_at) < now - timedelta(seconds=stuck_seconds))
    return out


@router.get("/stats")
def stats(start: datetime | None = None, end: datetime | None = None,
          ctx: AdminCtx = Depends(admin_read(VIEW))):
    start, end = _range(start, end)
    # 按分钟取整作为缓存键：「最近 24 小时」这类相对范围 30 秒内命中同一份结果
    key = (ctx.runtime.tenant_id, start.replace(second=0, microsecond=0), end.replace(second=0, microsecond=0))
    cache = ctx.runtime.stats_cache
    with _stats_lock:
        hit = cache.get(key)
    cfg = ctx.runtime.settings_svc.effective(ctx.db, "runtime")
    cache_seconds = int(cfg.get("stats_cache_seconds") if cfg.get("stats_cache_seconds") is not None
                        else STATS_CACHE_SECONDS)
    if hit and time.monotonic() - hit[0] < cache_seconds:
        data = hit[1]
    else:
        data = compute_stats(ctx.db, ctx.runtime.tenant_id, start, end, utcnow(), _stuck_threshold(ctx),
                             int(cfg.get("p95_min_samples") or P95_MIN_SAMPLES))
        data["generated_at"] = utcnow()
        with _stats_lock:
            if len(cache) > 256:
                cache.clear()
            cache[key] = (time.monotonic(), data)
    engine = ctx.runtime.engine
    return {**data, "observability": engine.sink.status() if engine else {"status": "未启动"}}


@router.get("/errors/top")
def errors_top(start: datetime | None = None, end: datetime | None = None, limit: int = Query(10, ge=1, le=50),
               ctx: AdminCtx = Depends(admin_read(VIEW))):
    start, end = _range(start, end)
    return {"items": top_errors(ctx.db, ctx.runtime.tenant_id, start, end, limit), "range": {"start": start, "end": end}}


@router.get("")
def list_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    oa: str | None = None,
    run_id: str | None = None,
    thread_id: str | None = None,
    error_code: str | None = None,
    failed_node: str | None = None,
    workflow_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    stuck_only: bool = False,
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    if status and status not in ALL_STATUSES:
        raise AppError(422, "VALIDATION_ERROR", f"未知状态：{status}")
    now = utcnow()
    stuck_seconds = _stuck_threshold(ctx)
    q = sa.select(Run).where(Run.tenant_id == ctx.runtime.tenant_id)
    for column, value in ((Run.run_status, status), (Run.oa, oa), (Run.run_id, run_id), (Run.thread_id, thread_id),
                          (Run.error_code, error_code), (Run.failed_node, failed_node),
                          (Run.workflow_id, workflow_id)):
        if value:
            q = q.where(column == value.strip())
    if start:
        q = q.where(Run.started_at >= _aware(start))
    if end:
        q = q.where(Run.started_at < _aware(end))
    if stuck_only:
        q = q.where(Run.run_status == RUNNING,
                    sa.func.coalesce(Run.last_event_at, Run.started_at) < now - timedelta(seconds=stuck_seconds))
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(
        q.order_by(Run.started_at.desc(), Run.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": [_run_view(r, now, stuck_seconds) for r in rows], "total": total, "page": page,
            "page_size": page_size}


def _get_run(ctx: AdminCtx, run_id: str) -> Run:
    run = ctx.db.scalar(sa.select(Run).where(Run.tenant_id == ctx.runtime.tenant_id, Run.run_id == run_id))
    if run is None:
        raise AppError(404, "NOT_FOUND", "运行不存在")
    return run


@router.get("/{run_id}")
def run_detail(run_id: str, ctx: AdminCtx = Depends(admin_read(VIEW))):
    run = _get_run(ctx, run_id)
    out = _run_view(run, utcnow(), _stuck_threshold(ctx))
    out["usage"] = run.usage_json
    out["event_count"] = ctx.db.scalar(sa.select(sa.func.count()).where(RunEvent.run_id == run_id))
    out["thread_run_count"] = ctx.db.scalar(
        sa.select(sa.func.count()).where(Run.tenant_id == run.tenant_id, Run.thread_id == run.thread_id))
    out["parent_run_id"] = run.parent_run_id
    out["child_runs"] = [{"run_id": r.run_id, "run_status": r.run_status, "started_at": r.started_at}
                         for r in ctx.db.scalars(sa.select(Run).where(Run.parent_run_id == run_id)
                                                 .order_by(Run.started_at)).all()]
    out["interventions"] = [{"task_id": t.task_id, "kind": t.kind, "status": t.status, "reason": t.reason,
                             "created_at": t.created_at, "handled_by": t.handled_by, "result": t.result}
                            for t in ctx.db.scalars(sa.select(InterventionTask)
                                                    .where(InterventionTask.run_id == run_id)
                                                    .order_by(InterventionTask.id)).all()]
    out["can_cancel"] = run.run_status not in TERMINAL and run.run_status != "cancel_requested"
    out["can_retry"] = run.run_status in RETRYABLE
    out["waiting_human"] = run.run_status == WAITING_HUMAN
    return out


class OperateIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


def _locked_run(ctx: AdminCtx, run_id: str) -> Run:
    run = _get_run(ctx, run_id)
    ctx.db.expunge(run)
    return run


@router.post("/{run_id}/cancel")
def cancel(run_id: str, body: OperateIn, ctx: AdminCtx = Depends(admin_write(OPERATE))):
    """running → cancel_requested（下一个节点开始前停止）；waiting_* → cancelled。状态变更与审计同事务。"""
    with ctx.db.begin():
        run = _locked_run(ctx, run_id)
        try:
            status = cancel_run(ctx.runtime, run, ctx.db)
        except StaleState:
            raise AppError(409, "RUN_STATE_CHANGED", "运行状态已变化，请刷新后重试") from None
        tasks = InterventionService.cancel_open_for_run(ctx.db, run_id, ctx.user.username, body.reason)
        ctx.audit("run.cancel", "run", run_id, before={"run_status": run.run_status},
                  after={"run_status": status, "cancelled_tasks": tasks}, reason=body.reason)
    after_cancel(ctx.runtime, run, status, ctx.user.username, body.reason)
    return {"run_id": run_id, "run_status": status}


@router.post("/{run_id}/retry")
def retry(run_id: str, body: OperateIn, ctx: AdminCtx = Depends(admin_write(OPERATE))):
    """failed / timed_out 的运行以原员工会话重新执行（新运行，parent_run_id 指向原运行）。"""
    rt = ctx.runtime
    with ctx.db.begin():
        run = _locked_run(ctx, run_id)
        if run.run_status not in RETRYABLE:
            raise AppError(409, "RUN_NOT_RETRYABLE", f"只有失败或超时的运行可以重试（当前 {run.run_status}）")
        session, run_ctx, why = employee_session(rt, run)
        if session is None:
            raise AppError(409, "RUN_NOT_RECOVERABLE", why)
        new_id = new_run_id()
        ctx.audit("run.retry", "run", run_id, before={"run_status": run.run_status},
                  after={"new_run_id": new_id}, reason=body.reason)
    result = retry_run(rt, run, session, run_ctx, ctx.user.username, ctx.meta.correlation_id, new_id)
    return {"run_id": run_id, "new_run_id": new_id, "new_run_status": result["run_status"]}


@router.get("/{run_id}/events")
def run_events(run_id: str, after_seq: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=EVENT_PAGE_MAX),
               ctx: AdminCtx = Depends(admin_read(VIEW))):
    _get_run(ctx, run_id)
    rows = ctx.db.scalars(
        sa.select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
        .order_by(RunEvent.seq).limit(limit + 1)
    ).all()
    return {"items": [{f: getattr(e, f) for f in EVENT_FIELDS} for e in rows[:limit]], "has_more": len(rows) > limit}
