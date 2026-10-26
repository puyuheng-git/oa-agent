"""人工介入任务（设计 §8、§10、§13 P3）。

- kind=admin：上游暂时故障转人工，由持 ops.intervention.handle 的管理员决定重试或终止。
- kind=user_confirm：业务确认，只能由员工本人凭确认令牌完成（runtime/confirmation.py），管理员不能代办。
任务处理用 version 乐观锁：pending → resolving 只有一个请求能抢到，重复提交不会重复执行。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import InterventionTask, Run
from oa_agent.db.types import utcnow
from oa_agent.ids import new_task_id
from oa_agent.observability.events import RunRecorder
from oa_agent.observability.redact import redact
from oa_agent.runtime.run_service import (
    EXPIRED, FAILED, RUNNING, WAITING_CONFIRMATION, WAITING_HUMAN, RunService, StaleState,
)

log = logging.getLogger(__name__)

ADMIN, USER_CONFIRM = "admin", "user_confirm"
PENDING, RESOLVING, RESOLVED, CANCELLED, TASK_EXPIRED = "pending", "resolving", "resolved", "cancelled", "expired"
OPEN_STATUSES = (PENDING, RESOLVING)
DEFAULT_EXPIRE_MINUTES = 30


class InterventionService:
    def __init__(self, session_factory: Callable[[], Session], tenant_id: str, runs: RunService):
        self._sf = session_factory
        self.tenant = tenant_id
        self._runs = runs

    def handoff(self, rec: RunRecorder, *, node_name: str, error_code: str, error_summary: str,
                expire_minutes: int) -> str | None:
        """running → waiting_human 并创建管理员介入任务（同一事务）。运行已不在 running 时返回 None。"""
        now = utcnow()
        task_id = new_task_id()
        with self._sf() as db, db.begin():
            result = db.execute(
                sa.update(Run).where(Run.run_id == rec.run_id, Run.run_status == RUNNING).values(
                    run_status=WAITING_HUMAN, last_event_at=now, error_code=error_code,
                    error_summary=redact(error_summary, 1000), failed_node=node_name,
                    **RunService.counters(rec)))
            if result.rowcount != 1:
                return None
            db.add(InterventionTask(
                task_id=task_id, tenant_id=self.tenant, run_id=rec.run_id, kind=ADMIN, status=PENDING,
                reason=redact(f"{error_code}：{error_summary}", 255), node_name=node_name, error_code=error_code,
                expire_at=now + timedelta(minutes=max(1, expire_minutes)), created_at=now))
        rec.event("run_waiting_human", node_name=node_name, status=WAITING_HUMAN, error_code=error_code,
                  error_summary=error_summary, metadata={"task_id": task_id})
        return task_id

    # ---- 任务状态（乐观锁） ----
    @staticmethod
    def claim(db: Session, task_id: str, version: int, operator: str) -> bool:
        result = db.execute(
            sa.update(InterventionTask)
            .where(InterventionTask.task_id == task_id, InterventionTask.status == PENDING,
                   InterventionTask.version == version)
            .values(status=RESOLVING, version=version + 1, handled_by=operator, handled_at=utcnow()))
        return result.rowcount == 1

    def release(self, task_id: str, note: str) -> None:
        """预检失败：退回 pending，保留给其他处理方式（如终止）。"""
        with self._sf() as db, db.begin():
            db.execute(
                sa.update(InterventionTask)
                .where(InterventionTask.task_id == task_id, InterventionTask.status == RESOLVING)
                .values(status=PENDING, version=InterventionTask.version + 1, handle_note=redact(note, 255)))

    def complete(self, task_id: str, result: str, note: str = "") -> None:
        with self._sf() as db, db.begin():
            self.resolve_claimed(db, task_id, result, note)

    @staticmethod
    def resolve_claimed(db: Session, task_id: str, result: str, note: str = "") -> None:
        db.execute(
            sa.update(InterventionTask)
            .where(InterventionTask.task_id == task_id, InterventionTask.status == RESOLVING)
            .values(status=RESOLVED, result=result, handled_at=utcnow(), handle_note=redact(note, 255) or None,
                    version=InterventionTask.version + 1))

    @staticmethod
    def cancel_open_for_run(db: Session, run_id: str, operator: str, note: str) -> int:
        result = db.execute(
            sa.update(InterventionTask)
            .where(InterventionTask.run_id == run_id, InterventionTask.status == PENDING)
            .values(status=CANCELLED, result="cancelled", handled_by=operator, handled_at=utcnow(),
                    handle_note=redact(note, 255), version=InterventionTask.version + 1))
        return result.rowcount

    # ---- 巡检 ----
    def expire_due(self, recorder_for_run: Callable[[Run], RunRecorder]) -> int:
        now = utcnow()
        with self._sf() as db:
            due = db.scalars(
                sa.select(InterventionTask)
                .where(InterventionTask.tenant_id == self.tenant, InterventionTask.status == PENDING,
                       InterventionTask.expire_at < now)
                .limit(100)).all()
        count = 0
        for task in due:
            with self._sf() as db, db.begin():
                won = db.execute(
                    sa.update(InterventionTask)
                    .where(InterventionTask.task_id == task.task_id, InterventionTask.status == PENDING,
                           InterventionTask.version == task.version)
                    .values(status=TASK_EXPIRED, result="expired", handled_at=now, handled_by="system",
                            version=task.version + 1)).rowcount == 1
            if not won:
                continue
            count += 1
            if task.kind == ADMIN:
                from_status, to_status, code = WAITING_HUMAN, FAILED, "INTERVENTION_EXPIRED"
                summary = "人工介入超时未处理"
            else:
                from_status, to_status, code = WAITING_CONFIRMATION, EXPIRED, "CONFIRMATION_EXPIRED"
                summary = "员工未在有效期内确认"
            try:
                self._runs.transition(task.run_id, from_status, to_status, ended_at=now, error_code=code,
                                      error_summary=summary)
            except StaleState:
                continue
            with self._sf() as db:
                run = db.scalar(sa.select(Run).where(Run.run_id == task.run_id))
            if run is not None:
                rec = recorder_for_run(run)
                rec.event("intervention_expired", status=to_status, error_code=code, error_summary=summary,
                          metadata={"task_id": task.task_id}, operator_id="system")
                rec.event("run_end", status=to_status, error_code=code, error_summary=summary)
        return count
