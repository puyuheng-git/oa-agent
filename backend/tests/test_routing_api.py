"""管理端 routing API：stats 与库一致、403、空库。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from oa_agent.db.models import Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.ids import new_event_id, new_run_id, new_thread_id
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_runs_admin import START, END, add_run


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def _add_event(rt, run_id: str, seq: int, event_type: str, *, metadata=None, duration_ms=None,
               tool_name=None, status=None):
    with rt.session() as db, db.begin():
        db.add(RunEvent(
            event_id=new_event_id(),
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            occurred_at=utcnow(),
            duration_ms=duration_ms,
            tool_name=tool_name,
            status=status,
            metadata_json=metadata,
        ))


def test_routing_stats_empty(admin):
    s = admin.get("/v1/admin/routing/stats", params={"start": START, "end": END}).json()
    assert s["empty"] is True
    assert s["runs_by_mode"] == []
    assert s["top_tools"] == []
    assert s["clarify_rate"] is None
    assert s["misselect"] == "未检测"


def test_routing_stats_match_inserted_events(admin, rt):
    rid = add_run(rt, "succeeded", duration_ms=120, tool_calls=1)
    _add_event(rt, rid, 1, "routing_start", metadata={"mode": "legacy_prompt", "message_chars": 8})
    _add_event(rt, rid, 2, "routing_stage", metadata={"stage": "topk", "candidates": ["a"]}, duration_ms=5)
    _add_event(rt, rid, 3, "routing_decision", metadata={
        "mode": "legacy_prompt", "action": "tool", "tool": "query_my_travel_expense_list",
        "skill": "travel", "clarify": False, "fallback_from": None,
    }, duration_ms=40, tool_name="query_my_travel_expense_list")
    _add_event(rt, rid, 4, "tool_call_end", tool_name="query_my_travel_expense_list",
               status="ok", duration_ms=80)

    rid2 = add_run(rt, "succeeded", duration_ms=90, tool_calls=1, oa="lisi")
    _add_event(rt, rid2, 1, "routing_decision", metadata={
        "mode": "skill_then_tool", "action": "clarify", "clarify": True,
        "fallback_from": "deterministic_first", "skill": "travel",
    }, duration_ms=20)
    _add_event(rt, rid2, 2, "routing_clarify", metadata={"question": "请补充"})

    s = admin.get("/v1/admin/routing/stats", params={"start": START, "end": END}).json()
    assert s["empty"] is False
    assert s["decision_runs"] == 2
    by_mode = {i["mode"]: i["count"] for i in s["runs_by_mode"]}
    assert by_mode["legacy_prompt"] == 1 and by_mode["skill_then_tool"] == 1
    assert s["clarify_rate"] == 0.5
    assert s["fallback_rate"] == 0.5
    assert s["tool_calls"]["total"] == 1 and s["tool_calls"]["ok"] == 1
    assert s["tool_calls"]["success_rate"] == 1.0
    assert s["avg_routing_ms"] == 30  # (40+20)/2
    assert s["top_tools"][0]["name"] == "query_my_travel_expense_list"
    assert s["top_skills"][0]["name"] == "travel"


def test_routing_runs_list_and_detail(admin, rt):
    rid = add_run(rt, "succeeded", duration_ms=100, tool_calls=1)
    _add_event(rt, rid, 1, "routing_decision", metadata={
        "mode": "retrieve_then_tool", "action": "tool", "tool": "query_my_travel_expense_list",
        "skill": "travel", "clarify": False,
    }, duration_ms=15, tool_name="query_my_travel_expense_list")
    _add_event(rt, rid, 2, "routing_stage", metadata={"stage": "retrieve", "candidates": ["query_my_travel_expense_list"]})
    _add_event(rt, rid, 3, "tool_call_end", tool_name="query_my_travel_expense_list", status="ok")

    lst = admin.get("/v1/admin/routing/runs", params={"start": START, "end": END}).json()
    assert lst["total"] >= 1
    assert any(i["run_id"] == rid and i["mode"] == "retrieve_then_tool" for i in lst["items"])

    detail = admin.get(f"/v1/admin/routing/runs/{rid}").json()
    assert detail["run"]["run_id"] == rid
    assert detail["empty_routing"] is False
    assert any(e["event_type"] == "routing_decision" for e in detail["routing_events"])
    assert detail["connector_status"].startswith("未使用")


def test_routing_forbidden_without_perm(admin, installed):
    role = _role(admin, "no_run_view", ["ops.audit.view"])
    _user(admin, "routing_denied", [role["id"]])
    from fastapi.testclient import TestClient
    from tests.conftest import login

    client = login(TestClient(installed.app), "routing_denied", VIEWER_PASS)
    assert client.get("/v1/admin/routing/stats").status_code == 403
    assert client.get("/v1/admin/routing/runs").status_code == 403
    assert client.get("/v1/admin/routing/runs/run_x").status_code == 403
