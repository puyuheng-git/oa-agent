"""运行生命周期与状态机（设计 §10）。

监控库不可用时不阻塞对话：运行快照落 spool，恢复后补写（设计 P1 验收「监控库故障时对话可用且有告警」）。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from oa_agent.db.models import Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.observability.events import EventSink, RunRecorder
from oa_agent.observability.redact import redact

log = logging.getLogger(__name__)

QUEUED, RUNNING = "queued", "running"
WAITING_CONFIRMATION, WAITING_HUMAN = "waiting_confirmation", "waiting_human"
CANCEL_REQUESTED = "cancel_requested"
SUCCEEDED, FAILED, CANCELLED, TIMED_OUT, EXPIRED = "succeeded", "failed", "cancelled", "timed_out", "expired"
TERMINAL = {SUCCEEDED, FAILED, CANCELLED, TIMED_OUT, EXPIRED}

TRANSITIONS: dict[str, set[str]] = {
    QUEUED: {RUNNING},
    RUNNING: {WAITING_CONFIRMATION, WAITING_HUMAN, SUCCEEDED, FAILED, TIMED_OUT, CANCEL_REQUESTED},
    WAITING_CONFIRMATION: {RUNNING, FAILED, EXPIRED, CANCEL_REQUESTED},
    WAITING_HUMAN: {RUNNING, FAILED, CANCELLED},
    CANCEL_REQUESTED: {CANCELLED, SUCCEEDED, FAILED},
}


class InvalidTransition(Exception):
    pass


class StaleState(Exception):
    """数据库中的当前状态不是期望的 from 状态（并发或已被巡检改写）。"""


class RunService:
    def __init__(self, session_factory: Callable[[], Session], sink: EventSink, tenant_id: str):
        self._sf = session_factory
        self._sink = sink
        self.tenant = tenant_id

    # ---- 状态转换 ----
    def transition(self, run_id: str, from_status: str, to_status: str, *, db: Session | None = None,
                   **fields) -> None:
        """db 给定时在调用方事务内执行（与审计同事务提交）；否则独立事务。"""
        if to_status not in TRANSITIONS.get(from_status, set()):
            raise InvalidTransition(f"{from_status} → {to_status} 不合法")
        values = {"run_status": to_status, "last_event_at": utcnow(), **fields}
        stmt = sa.update(Run).where(Run.run_id == run_id, Run.run_status == from_status).values(**values)
        if db is not None:
            if db.execute(stmt).rowcount != 1:
                raise StaleState(f"{run_id} 当前不是 {from_status}")
            return
        with self._sf() as own, own.begin():
            if own.execute(stmt).rowcount != 1:
                raise StaleState(f"{run_id} 当前不是 {from_status}")

    # ---- 生命周期 ----
    def start(self, rec: RunRecorder, *, channel: str, agent_id: str, workflow_id: str, workflow_version: str,
              business_type: str | None, config_release_id: str | None = None,
              parent_run_id: str | None = None, message: str | None = None) -> bool:
        """创建 queued 并转 running。返回 False 表示监控库不可用（已落 spool）。"""
        now = utcnow()
        snapshot = {
            "run_id": rec.run_id, "thread_id": rec.thread_id, "tenant_id": self.tenant, "oa": rec.oa,
            "channel": channel, "agent_id": agent_id, "workflow_id": workflow_id,
            "workflow_version": workflow_version, "config_release_id": config_release_id,
            "parent_run_id": parent_run_id, "run_status": QUEUED, "started_at": now, "last_event_at": now,
            "tool_call_count": 0, "model_call_count": 0, "business_type": business_type,
        }
        rec.started_at = now
        rec.snapshot = snapshot
        try:
            with self._sf() as db, db.begin():
                db.add(Run(**snapshot))
            self.transition(rec.run_id, QUEUED, RUNNING)
            snapshot["run_status"] = RUNNING
            ok = True
        except SQLAlchemyError as exc:
            snapshot["run_status"] = RUNNING
            log.error("监控库不可用，运行 %s 记录落 spool：%s", rec.run_id, redact(str(exc), 200))
            self._sink.spool("run", [snapshot])
            ok = False
        rec.event("run_start", status=RUNNING,
                  input_summary={"message": message} if message is not None else None,
                  metadata={"channel": channel, "workflow_id": workflow_id, "workflow_version": workflow_version})
        return ok

    def finish(self, rec: RunRecorder, to_status: str, *, error_code: str | None = None,
               error_summary: str | None = None, business_record_id: str | None = None) -> str:
        """运行结束（同步写库）。返回最终状态（可能已被巡检改为 timed_out）。"""
        ended = utcnow()
        started = rec.started_at or ended
        fields = {
            "ended_at": ended,
            "duration_ms": int((ended - started).total_seconds() * 1000),
            "error_code": error_code,
            "error_summary": redact(error_summary, 1000) if error_summary else None,
            "failed_node": rec.failed_node,
            "tool_call_count": rec.tool_call_count,
            "model_call_count": rec.model_call_count,
            "usage_json": rec.usages or None,
            "business_record_id": business_record_id,
        }
        final = to_status
        try:
            if to_status not in TRANSITIONS[RUNNING]:  # 如 cancelled：只能经 cancel_requested 到达
                raise StaleState(rec.run_id)
            self.transition(rec.run_id, RUNNING, to_status, **fields)
        except StaleState:
            final = self._current_status(rec.run_id) or to_status
            if final == CANCEL_REQUESTED:
                # 已请求取消：以实际停止结果为准（设计 §10）
                final = to_status if to_status in TRANSITIONS[CANCEL_REQUESTED] else FAILED
                try:
                    self.transition(rec.run_id, CANCEL_REQUESTED, final, **fields)
                except StaleState:
                    final = self._current_status(rec.run_id) or final
            elif final == to_status:  # 记录缺失（start 时监控库不可用）：补写完整快照
                self._sink.spool("run", [{**rec.snapshot, **fields, "run_status": to_status}])
            else:
                log.warning("运行 %s 结束时状态已是 %s，未覆盖为 %s", rec.run_id, final, to_status)
        except SQLAlchemyError as exc:
            log.error("监控库不可用，运行 %s 终态落 spool：%s", rec.run_id, redact(str(exc), 200))
            self._sink.spool("run", [{**rec.snapshot, **fields, "run_status": to_status}])
        rec.event("run_end", status=final, duration_ms=fields["duration_ms"], error_code=error_code,
                  error_summary=error_summary, node_name=rec.failed_node)
        return final

    @staticmethod
    def counters(rec: RunRecorder) -> dict:
        return {"tool_call_count": rec.tool_call_count, "model_call_count": rec.model_call_count,
                "usage_json": rec.usages or None}

    def _current_status(self, run_id: str) -> str | None:
        try:
            with self._sf() as db:
                return db.scalar(sa.select(Run.run_status).where(Run.run_id == run_id))
        except SQLAlchemyError:
            return None

    # ---- 恢复与巡检 ----
    def recover_interrupted(self) -> int:
        """单实例：启动时库内仍为 running/queued 的运行必然无人执行；已请求取消的视为已取消。
        waiting_human / waiting_confirmation 不处理：其 Checkpoint 已持久化，重启后仍可恢复或由巡检过期。"""
        now = utcnow()
        with self._sf() as db, db.begin():
            result = db.execute(
                sa.update(Run)
                .where(Run.tenant_id == self.tenant, Run.run_status.in_([RUNNING, QUEUED]))
                .values(run_status=FAILED, ended_at=now, last_event_at=now, error_code="RUNTIME_INTERRUPTED",
                        error_summary="服务重启时运行未结束")
            )
            cancelled = db.execute(
                sa.update(Run)
                .where(Run.tenant_id == self.tenant, Run.run_status == CANCEL_REQUESTED)
                .values(run_status=CANCELLED, ended_at=now, last_event_at=now)
            )
        if result.rowcount:
            log.warning("启动恢复：%d 个未结束运行标记为 failed(RUNTIME_INTERRUPTED)", result.rowcount)
        return result.rowcount + cancelled.rowcount

    def purge_events(self, retention_days: int, batch: int = 5000) -> int:
        """删除超过保留期的事件（设计 §8：默认 180 天，审计不自动删除）。分批避免长事务。"""
        if retention_days < 1:
            return 0
        cutoff = utcnow() - timedelta(days=retention_days)
        total = 0
        while True:
            with self._sf() as db, db.begin():
                ids = db.scalars(sa.select(RunEvent.id).where(RunEvent.occurred_at < cutoff).limit(batch)).all()
                if not ids:
                    return total
                db.execute(sa.delete(RunEvent).where(RunEvent.id.in_(ids)))
            total += len(ids)

    def sweep_timeouts(self, timeout_seconds: int) -> int:
        now = utcnow()
        cutoff = now - timedelta(seconds=timeout_seconds)
        with self._sf() as db, db.begin():
            # last_event_at 随每次状态迁移更新：RUNNING 按本段执行计时（等待人工的时长不计入）
            result = db.execute(
                sa.update(Run)
                .where(Run.tenant_id == self.tenant, Run.run_status == RUNNING,
                       sa.func.coalesce(Run.last_event_at, Run.started_at) < cutoff)
                .values(run_status=TIMED_OUT, ended_at=now, last_event_at=now, error_code="RUN_TIMEOUT",
                        error_summary=f"超过 {timeout_seconds} 秒未结束")
            )
            # 取消请求发出后超过超时仍未停下：执行线程已不可能再产出有效结果
            db.execute(
                sa.update(Run)
                .where(Run.tenant_id == self.tenant, Run.run_status == CANCEL_REQUESTED,
                       Run.last_event_at < cutoff)
                .values(run_status=CANCELLED, ended_at=now, last_event_at=now)
            )
        return result.rowcount
