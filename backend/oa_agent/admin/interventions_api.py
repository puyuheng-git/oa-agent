"""/v1/admin/interventions：介入中心（设计 §9 ops.intervention.handle、§13 P3）。

恢复前重验：任务类型与状态、运行状态、流程版本、员工会话（身份）、Checkpoint 中断点；任一不满足如实拒绝。
任务以 version 乐观锁认领，重复提交只有一个生效。员工业务确认（user_confirm）管理员不能代办。
"""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.chat.service import after_terminate, employee_session, resume_run, terminate_run
from oa_agent.db.models import InterventionTask, Run
from oa_agent.errors import AppError
from oa_agent.runtime.graphs import travel_query
from oa_agent.runtime.intervention import ADMIN, PENDING, InterventionService
from oa_agent.runtime.releases import ReleaseError
from oa_agent.runtime.run_service import WAITING_HUMAN, StaleState

router = APIRouter(prefix="/v1/admin/interventions", tags=["admin-interventions"])

HANDLE = "ops.intervention.handle"
STATUSES = ("pending", "resolving", "resolved", "cancelled", "expired")
TASK_FIELDS = ("task_id", "run_id", "kind", "status", "reason", "node_name", "error_code", "expire_at", "created_at",
               "handled_by", "handled_at", "result", "handle_note", "version")


class HandleIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)
    version: int = Field(ge=1)


def _view(task: InterventionTask, run: Run | None) -> dict:
    out = {f: getattr(task, f) for f in TASK_FIELDS}
    out["run"] = None if run is None else {
        "run_id": run.run_id, "oa": run.oa, "run_status": run.run_status, "workflow_id": run.workflow_id,
        "workflow_version": run.workflow_version, "started_at": run.started_at, "error_code": run.error_code}
    return out


def _load(ctx: AdminCtx, task_id: str) -> tuple[InterventionTask, Run | None]:
    task = ctx.db.scalar(sa.select(InterventionTask).where(InterventionTask.tenant_id == ctx.runtime.tenant_id,
                                                           InterventionTask.task_id == task_id))
    if task is None:
        raise AppError(404, "NOT_FOUND", "介入任务不存在")
    run = ctx.db.scalar(sa.select(Run).where(Run.run_id == task.run_id))
    return task, run


def _forbid_user_confirm(ctx: AdminCtx, action: str, task_id: str) -> None:
    with ctx.db.begin():
        ctx.audit(action, "intervention", task_id, result="denied", reason="管理员不能代员工确认业务操作")
    raise AppError(403, "ADMIN_CANNOT_CONFIRM", "员工业务确认只能由员工本人完成，管理员不能代为确认")


def _base_reasons(task: InterventionTask, run: Run | None) -> list[str]:
    reasons = []
    if task.status != PENDING:
        reasons.append(f"任务当前状态为 {task.status}，不可处理")
    if run is None:
        reasons.append("关联运行记录不存在")
    elif run.run_status != WAITING_HUMAN:
        reasons.append(f"运行当前状态为 {run.run_status}，不在等待人工")
    return reasons


def resume_blockers(ctx: AdminCtx, task: InterventionTask, run: Run | None) -> list[str]:
    reasons = _base_reasons(task, run)
    if task.kind != ADMIN:
        reasons.insert(0, "员工业务确认只能由员工本人完成")
    if run is None or reasons:
        return reasons
    if run.workflow_version != travel_query.WORKFLOW_VERSION:
        reasons.append(f"运行使用的流程版本 {run.workflow_version} 与当前版本 {travel_query.WORKFLOW_VERSION} 不一致")
    if run.config_release_id:
        try:
            ctx.runtime.engine.release_provider.get(run.config_release_id)
        except ReleaseError as exc:
            reasons.append(exc.message)
    session, _, why = employee_session(ctx.runtime, run)
    if session is None:
        reasons.append(why)
    if ctx.runtime.engine.pending_interrupt(run.thread_id, run.run_id) is None:
        reasons.append("Checkpoint 中没有该运行的中断点（检查点缺失或已被同一会话的新请求覆盖）")
    return reasons


@router.get("")
def list_tasks(status: str | None = None, kind: str | None = None, run_id: str | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               ctx: AdminCtx = Depends(admin_read(HANDLE))):
    if status and status not in STATUSES:
        raise AppError(422, "VALIDATION_ERROR", f"未知状态：{status}")
    q = sa.select(InterventionTask).where(InterventionTask.tenant_id == ctx.runtime.tenant_id)
    for column, value in ((InterventionTask.status, status), (InterventionTask.kind, kind),
                          (InterventionTask.run_id, run_id)):
        if value:
            q = q.where(column == value)
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(q.subquery()))
    tasks = ctx.db.scalars(q.order_by(InterventionTask.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    runs = {r.run_id: r for r in ctx.db.scalars(sa.select(Run).where(Run.run_id.in_([t.run_id for t in tasks])))}
    pending = ctx.db.scalar(sa.select(sa.func.count()).where(InterventionTask.tenant_id == ctx.runtime.tenant_id,
                                                             InterventionTask.status == PENDING))
    return {"items": [_view(t, runs.get(t.run_id)) for t in tasks], "total": total, "page": page,
            "page_size": page_size, "pending_count": pending}


@router.get("/{task_id}")
def task_detail(task_id: str, ctx: AdminCtx = Depends(admin_read(HANDLE))):
    task, run = _load(ctx, task_id)
    out = _view(task, run)
    blockers = resume_blockers(ctx, task, run)
    out["resumable"] = {"ok": not blockers, "reasons": blockers}
    terminate_blockers = _base_reasons(task, run) if task.kind == ADMIN else ["员工业务确认只能由员工本人完成"]
    out["terminable"] = {"ok": not terminate_blockers, "reasons": terminate_blockers}
    return out


def _reject(ctx: AdminCtx, action: str, task_id: str, reasons: list[str], reason: str) -> None:
    with ctx.db.begin():
        ctx.audit(action, "intervention", task_id, result="rejected", reason=f"{reason}｜{'；'.join(reasons)}")
    raise AppError(409, "NOT_RECOVERABLE", "；".join(reasons))


@router.post("/{task_id}/resume")
def resume(task_id: str, body: HandleIn, ctx: AdminCtx = Depends(admin_write(HANDLE))):
    rt = ctx.runtime
    with ctx.db.begin():
        task, run = _load(ctx, task_id)
        blockers = resume_blockers(ctx, task, run)
        session = None
        if task.kind == ADMIN and not blockers:
            session, _, _ = employee_session(rt, run)
            if not InterventionService.claim(ctx.db, task_id, body.version, ctx.user.username):
                raise AppError(409, "TASK_ALREADY_HANDLED", "任务已被处理或版本已变化，请刷新")
            ctx.audit("intervention.resume", "intervention", task_id,
                      before={"task_status": task.status, "run_status": run.run_status},
                      after={"action": "retry", "run_id": run.run_id}, reason=body.reason)
    if task.kind != ADMIN:
        _forbid_user_confirm(ctx, "intervention.resume", task_id)
    if blockers:
        _reject(ctx, "intervention.resume", task_id, blockers, body.reason)
    ctx.db.expunge_all()
    try:
        result = resume_run(rt, run, session, ctx.user.username, ctx.meta.correlation_id,
                            {"action": "retry", "operator": ctx.user.username})
    except StaleState:
        rt.engine.interventions.complete(task_id, "state_changed", "运行状态已变化")
        raise AppError(409, "RUN_STATE_CHANGED", "运行状态已变化，未执行") from None
    rt.engine.interventions.complete(task_id, result["run_status"], body.reason)
    return {"task_id": task_id, "run_id": run.run_id, "run_status": result["run_status"]}


@router.post("/{task_id}/terminate")
def terminate(task_id: str, body: HandleIn, ctx: AdminCtx = Depends(admin_write(HANDLE))):
    rt = ctx.runtime
    with ctx.db.begin():
        task, run = _load(ctx, task_id)
        blockers = _base_reasons(task, run)
        if task.kind == ADMIN and not blockers:
            if not InterventionService.claim(ctx.db, task_id, body.version, ctx.user.username):
                raise AppError(409, "TASK_ALREADY_HANDLED", "任务已被处理或版本已变化，请刷新")
            try:
                terminate_run(rt, run, ctx.user.username, body.reason, ctx.db)
            except StaleState:
                raise AppError(409, "RUN_STATE_CHANGED", "运行状态已变化，请刷新") from None
            InterventionService.resolve_claimed(ctx.db, task_id, "terminated", body.reason)
            ctx.audit("intervention.terminate", "intervention", task_id,
                      before={"task_status": task.status, "run_status": run.run_status},
                      after={"run_status": "failed", "error_code": "HUMAN_TERMINATED"}, reason=body.reason)
    if task.kind != ADMIN:
        _forbid_user_confirm(ctx, "intervention.terminate", task_id)
    if blockers:
        _reject(ctx, "intervention.terminate", task_id, blockers, body.reason)
    ctx.db.expunge_all()
    after_terminate(rt, run, ctx.user.username, body.reason)
    return {"task_id": task_id, "run_id": run.run_id, "run_status": "failed"}
