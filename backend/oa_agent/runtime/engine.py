"""Agent 运行时装配：EventSink、RunService、Checkpointer、Graph、巡检线程"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import sqlalchemy as sa
from langgraph.types import Command
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from oa_agent.db.models import Run, RunEvent
from oa_agent.errors import AppError
from oa_agent.executor.catalog import Catalog, SkillState
from oa_agent.executor.registry import ToolRegistry
from oa_agent.observability.events import RUN_COLUMNS, EventSink, RunRecorder
from oa_agent.runtime.checkpointer import open_checkpointer
from oa_agent.runtime.graphs import travel_query, travel_reimburse_submit
from oa_agent.runtime.intervention import InterventionService
from oa_agent.runtime.releases import ReleaseService
from oa_agent.runtime.run_service import RunService
from oa_agent.settings import AppSettings

log = logging.getLogger(__name__)

WATCHDOG_INTERVAL = 30.0
PURGE_INTERVAL = 3600.0


class LiveRegistry:
    """每次查找都读引擎当前注册表：停用立即对后续调用生效"""

    def __init__(self, engine: "AgentEngine"):
        self._engine = engine

    def get(self, name: str):
        return self._engine.registry.get(name)

    def names(self) -> list[str]:
        return self._engine.registry.names()


class AgentEngine:
    def __init__(self, settings: AppSettings, session_factory: Callable[[], Session], tenant_id: str,
                 timeout_seconds: Callable[[], int], retention_days: Callable[[], int] = lambda: 180,
                 setting: Callable[[str, str], object] | None = None):
        self._sf = session_factory
        self._setting = setting
        self.sink = EventSink(session_factory, settings.data_dir / "event_spool")
        self.runs = RunService(session_factory, self.sink, tenant_id)
        self.interventions = InterventionService(session_factory, tenant_id, self.runs)
        self.catalog = Catalog(session_factory, tenant_id)
        self.registry = ToolRegistry({})
        self.live_registry = LiveRegistry(self)
        self.skill_states: dict[str, SkillState] = {}
        self._catalog_loaded = False
        self.skill_checker = self.check_skills
        self.release_provider = ReleaseService(session_factory, tenant_id)
        self._contexts: dict[str, travel_query.RunContext] = {}
        self._write_contexts: dict[str, travel_reimburse_submit.WriteRunContext] = {}
        self._cancel_requested: set[str] = set()
        self.checkpointer = open_checkpointer(settings.data_dir / "checkpoints.sqlite", self._recorder_for)
        # 主对话图为 oa_assistant（graphs.travel_query 仅为兼容 import shim）
        self.graph = travel_query.build_graph(self.checkpointer, self._context)
        self.write_graph = travel_reimburse_submit.build_graph(self.checkpointer, self._write_context)
        self._timeout_seconds = timeout_seconds
        self._retention_days = retention_days
        self._last_purge = 0.0
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self.tick_hooks: list[Callable[[], None]] = []

    def _context(self, run_id: str) -> travel_query.RunContext:
        return self._contexts[run_id]

    def _write_context(self, run_id: str) -> travel_reimburse_submit.WriteRunContext:
        return self._write_contexts[run_id]

    def _recorder_for(self, run_id: str | None) -> RunRecorder | None:
        if not run_id:
            return None
        ctx = self._contexts.get(run_id) or self._write_contexts.get(run_id)
        return ctx.recorder if ctx else None

    def start(self) -> None:
        self.sink.start()
        try:
            self.runs.recover_interrupted()
        except SQLAlchemyError:
            log.exception("启动恢复失败（监控库不可用？")
        try:
            self.catalog.bootstrap()
        except SQLAlchemyError:
            log.exception("Tool/Skill 首次同步失败")
        self.reload_catalog()
        try:
            self.release_provider.seed()
            self.release_provider.current()
        except SQLAlchemyError:
            log.exception("初始化 Workflow 发布失败")
        self._watchdog = threading.Thread(target=self._watch, name="run-watchdog", daemon=True)
        self._watchdog.start()

    def stop(self) -> None:
        self._stop.set()
        self.sink.stop()
        try:
            self.checkpointer.conn.close()
        except Exception:  # noqa: BLE001
            pass

    def _runtime_number(self, key: str, default: float) -> float:
        try:
            return float(self._setting("runtime", key)) if self._setting else default
        except Exception:  # noqa: BLE001 —"配置读不到时用默认值，巡检不能"
            return default

    def _watch(self) -> None:
        while not self._stop.wait(self._runtime_number("watchdog_interval_seconds", WATCHDOG_INTERVAL)):
            self.watchdog_tick()

    def watchdog_tick(self) -> int:
        try:
            n = self.runs.sweep_timeouts(self._timeout_seconds())
            if n:
                log.warning("巡检到 %d 个运行超时，标记为 timed_out", n)
        except SQLAlchemyError:
            log.exception("巡检失败")
            n = 0
        try:
            expired = self.interventions.expire_due(self.recorder_for_run)
            if expired:
                log.warning("巡检到 %d 个介入任务过期", expired)
        except SQLAlchemyError:
            log.exception("介入任务过期巡检失败")
        if not self._catalog_loaded:
            self.reload_catalog()
        purge_every = self._runtime_number("purge_interval_minutes", PURGE_INTERVAL / 60) * 60
        if time.monotonic() - self._last_purge >= purge_every:
            self._last_purge = time.monotonic()
            try:
                purged = self.runs.purge_events(self._retention_days())
                if purged:
                    log.info("巡检：清理过期事件 %d 条", purged)
            except SQLAlchemyError:
                log.exception("清理过期事件失败")
        for hook in self.tick_hooks:
            try:
                hook()
            except Exception:  # noqa: BLE001 —"附加巡检失败不影响主巡检
                log.exception("巡检附加任务失败")
        return n

    # ---- Tool / Skill ----
    def reload_catalog(self) -> bool:
        """从库重建运行时注册表"Skill 状态。失败时保留上一份（启动即失败则为空：宁可拒绝也不放开已停用的 Tool）"""
        try:
            with self._sf() as db:
                registry = self.catalog.load_registry(db)
                states = self.catalog.skill_states(db)
        except SQLAlchemyError:
            log.exception("加载 Tool/Skill 注册表失败，沿用上一")
            return False
        self.registry, self.skill_states, self._catalog_loaded = registry, states, True
        return True

    def available_skills(self) -> list[SkillState]:
        return [s for s in self.skill_states.values() if s.available]

    def check_skills(self) -> None:
        if not self.available_skills():
            why = "；".join(f"{s.name}：{'已停用' if not s.enabled else '；'.join(s.errors) or '校验未通过'}" for s in self.skill_states.values()) or "未配置任何 Skill"
            raise AppError(503, "SKILL_DISABLED", f"没有可用的 Skill（{why}")

    # ---- 取消 ----
    def request_cancel(self, run_id: str) -> None:
        self._cancel_requested.add(run_id)

    def is_executing(self, run_id: str) -> bool:
        return run_id in self._contexts

    def cancel_checker(self, run_id: str) -> Callable[[], bool]:
        return lambda: run_id in self._cancel_requested

    # ---- 执行 ----
    def _run_graph(self, ctx: travel_query.RunContext, graph_input, thread_id: str) -> dict:
        run_id = ctx.recorder.run_id
        self._contexts[run_id] = ctx
        ctx.should_cancel = self.cancel_checker(run_id)
        config = {"configurable": {"thread_id": thread_id, "run_id": run_id}}
        try:
            return self.graph.invoke(graph_input, config)
        finally:
            self._contexts.pop(run_id, None)
            self._cancel_requested.discard(run_id)

    def _run_write_graph(self, ctx: travel_reimburse_submit.WriteRunContext, graph_input, thread_id: str) -> dict:
        run_id = ctx.recorder.run_id
        self._write_contexts[run_id] = ctx
        config = {"configurable": {"thread_id": thread_id, "run_id": run_id}}
        try:
            return self.write_graph.invoke(graph_input, config)
        finally:
            self._write_contexts.pop(run_id, None)
            self._cancel_requested.discard(run_id)

    def invoke(self, ctx: travel_query.RunContext, message: str, thread_id: str) -> dict:
        if self.checkpointer.get_tuple({"configurable": {"thread_id": thread_id}}) is not None:
            ctx.recorder.event("checkpoint_restored", metadata={"thread_id": thread_id})
        return self._run_graph(ctx, {"run_id": ctx.recorder.run_id, "message": message}, thread_id)

    def resume(self, ctx: travel_query.RunContext, thread_id: str, decision: dict) -> dict:
        ctx.recorder.event("checkpoint_restored", metadata={"thread_id": thread_id, "resume": True})
        return self._run_graph(ctx, Command(resume=decision), thread_id)

    def invoke_write(self, ctx: travel_reimburse_submit.WriteRunContext, expense_id: int, thread_id: str) -> dict:
        return self._run_write_graph(
            ctx, {"run_id": ctx.recorder.run_id, "expense_id": expense_id}, thread_id,
        )

    def resume_write(self, ctx: travel_reimburse_submit.WriteRunContext, thread_id: str, decision: dict) -> dict:
        ctx.recorder.event("checkpoint_restored", metadata={"thread_id": thread_id, "resume": True, "write": True})
        return self._run_write_graph(ctx, Command(resume=decision), thread_id)

    def pending_interrupt(self, thread_id: str, run_id: str) -> dict | None:
        """Checkpoint 中属于该运行的未决中断；不存在返"None（不可恢复）"""
        for graph in (self.graph, self.write_graph):
            try:
                snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
            except Exception:  # noqa: BLE001 —"Checkpoint 损坏/缺失一律视为不可恢"
                log.exception("读取 Checkpoint 失败：thread=%s", thread_id)
                continue
            for item in getattr(snapshot, "interrupts", ()) or ():
                value = getattr(item, "value", None)
                if isinstance(value, dict) and value.get("run_id") == run_id:
                    return value
        return None

    def recorder_for_run(self, run: Run, correlation_id: str = "") -> RunRecorder:
        """给库内已有运行续写事件：执行中的用其记录器；否则先刷出队列，seq 接在库内最大值之后"""
        ctx = self._contexts.get(run.run_id)
        if ctx is not None:
            return ctx.recorder
        self.sink.flush(2.0)
        with self._sf() as db:
            max_seq = db.scalar(sa.select(sa.func.max(RunEvent.seq)).where(RunEvent.run_id == run.run_id)) or 0
        rec = RunRecorder(run_id=run.run_id, thread_id=run.thread_id, oa=run.oa, correlation_id=correlation_id,
                          sink=self.sink, tool_call_count=run.tool_call_count or 0,
                          model_call_count=run.model_call_count or 0, usages=list(run.usage_json or []),
                          started_at=run.started_at,
                          snapshot={c: getattr(run, c) for c in RUN_COLUMNS})
        return rec.continue_after(max_seq)
