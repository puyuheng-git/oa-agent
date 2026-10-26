"""P1 运行时单元：状态机、巡检/启动恢复、意图规则、参数校验、事件幂等"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
import sqlalchemy as sa

from oa_agent.db.models import Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.ids import new_run_id, new_thread_id
from oa_agent.executor.executor import Identity, ToolError, build_request, validate_args
from oa_agent.executor.registry import ToolRegistry
from oa_agent.observability.events import RunRecorder
from oa_agent.runtime import intent_rules
from oa_agent.runtime.run_service import InvalidTransition, StaleState


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def new_recorder(rt) -> RunRecorder:
    return RunRecorder(run_id=new_run_id(), thread_id=new_thread_id(), oa="zhangsan", correlation_id="req",
                       sink=rt.engine.sink)


def start(rt, rec):
    assert rt.engine.runs.start(rec, channel="oa_web", agent_id="a", workflow_id="w", workflow_version="1",
                                business_type=None)


def status_of(rt, run_id):
    with rt.session() as db:
        return db.scalar(sa.select(Run.run_status).where(Run.run_id == run_id))


def test_state_machine_guards(rt):
    runs = rt.engine.runs
    rec = new_recorder(rt)
    start(rt, rec)
    assert status_of(rt, rec.run_id) == "running"
    with pytest.raises(InvalidTransition):
        runs.transition(rec.run_id, "running", "queued")
    with pytest.raises(StaleState):
        runs.transition(rec.run_id, "queued", "running")
    assert runs.finish(rec, "succeeded") == "succeeded"
    with pytest.raises(InvalidTransition):
        runs.transition(rec.run_id, "succeeded", "running")


def test_watchdog_times_out_and_finish_does_not_overwrite(rt):
    rec = new_recorder(rt)
    start(rt, rec)
    long_ago = utcnow() - timedelta(seconds=120)
    with rt.session() as db, db.begin():
        db.execute(sa.update(Run).where(Run.run_id == rec.run_id).values(started_at=long_ago, last_event_at=long_ago))
    assert rt.engine.watchdog_tick() == 1
    assert status_of(rt, rec.run_id) == "timed_out"
    assert rt.engine.runs.finish(rec, "succeeded") == "timed_out"
    assert status_of(rt, rec.run_id) == "timed_out"


def test_watchdog_times_from_resume_not_from_start(rt):
    """在等待人工里停了很久的运行，被恢复后按本段执行计时，不能一恢复就判超时"""
    rec = new_recorder(rt)
    start(rt, rec)
    runs = rt.engine.runs
    runs.transition(rec.run_id, "running", "waiting_human")
    with rt.session() as db, db.begin():
        db.execute(sa.update(Run).where(Run.run_id == rec.run_id)
                   .values(started_at=utcnow() - timedelta(minutes=10), last_event_at=utcnow() - timedelta(minutes=10)))
    runs.transition(rec.run_id, "waiting_human", "running")
    assert rt.engine.watchdog_tick() == 0
    assert status_of(rt, rec.run_id) == "running"


def test_recover_interrupted(rt):
    rec = new_recorder(rt)
    start(rt, rec)
    assert rt.engine.runs.recover_interrupted() == 1
    with rt.session() as db:
        run = db.scalar(sa.select(Run).where(Run.run_id == rec.run_id))
    assert run.run_status == "failed" and run.error_code == "RUNTIME_INTERRUPTED"


def test_event_replay_is_idempotent(rt):
    sink = rt.engine.sink
    rec = new_recorder(rt)
    start(rt, rec)
    rec.event("node_start", node_name="x")
    assert sink.flush(5)
    with rt.session() as db:
        ev = db.scalars(sa.select(RunEvent).where(RunEvent.run_id == rec.run_id)).all()
    dup = {c: getattr(ev[-1], c) for c in ("event_id", "run_id", "seq", "event_type", "node_name", "occurred_at")}
    sink.spool("event", [dup])
    sink.replay_spool()
    with rt.session() as db:
        n = db.scalar(sa.select(sa.func.count()).select_from(RunEvent).where(RunEvent.run_id == rec.run_id))
    assert n == len(ev)


# ---------------- 意图规则 ----------------

TODAY = date(2026, 10, 9)  # 周五


@pytest.mark.parametrize("text,expected", [
    ("查上周行程报销", ("2026-09-28", "2026-10-04")),
    ("本周的行程", ("2026-10-05", "2026-10-09")),
    ("上月行程报销", ("2026-09-01", "2026-09-30")),
    ("最近7天的行程", ("2026-10-03", "2026-10-09")),
    ("昨天的行程报销", ("2026-10-08", "2026-10-08")),
])
def test_date_ranges(text, expected):
    parsed = intent_rules.parse(text, TODAY)
    assert parsed["intent"] == "list"
    assert (parsed["params"]["date_gte"], parsed["params"]["date_lte"]) == expected


def test_intent_rules_filters_and_detail():
    assert intent_rules.parse("本月未报销的行程", TODAY)["params"]["status"] == 0
    assert intent_rules.parse("查看报销单 12345 详情", TODAY) == {"intent": "detail", "params": {"id": 12345}}
    assert intent_rules.parse("今天天气怎么样", TODAY)["intent"] == "help"


# ---------------- 参数校验 / 身份注入 ----------------

def test_validate_args_drops_identity_and_caps_limit():
    spec = ToolRegistry.load().get("query_my_travel_expense_list")
    clean, dropped = validate_args(spec, {"oa": "lisi", "limit": 999, "evil": 1, "date_gte": "2026-09-01"})
    assert "oa" not in clean and set(dropped) == {"oa", "evil"}
    assert clean["limit"] == 20 and clean["page"] == 1
    req = build_request(spec, clean, Identity(oa="zhangsan", authorization="t"))
    assert json.loads(req["queryParams"]) == {"date_gte": "2026-09-01", "oa": "zhangsan"}
    with pytest.raises(ToolError):
        validate_args(spec, {"date_gte": "2026-13-01"})
    with pytest.raises(ToolError):
        validate_args(spec, {"date_gte": "2026-09-10", "date_lte": "2026-09-01"})


def test_registry_only_low_risk_enabled():
    assert set(ToolRegistry.load().names()) == {"query_my_travel_expense_list", "query_my_travel_expense_detail"}
