"""P2 运行监控 API：指标与库内记录一致、列表/详情/事件、权限。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from oa_agent.db.models import Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.ids import new_event_id, new_run_id, new_thread_id
from oa_agent.observability.run_stats import percentile, sum_tokens
from tests.conftest import login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

NOW = utcnow()
START = (NOW - timedelta(hours=1)).isoformat()
END = (NOW + timedelta(days=1)).isoformat()


def add_run(rt, status, *, minutes_ago=10, duration_ms=None, ended=True, error_code=None, failed_node=None,
            usage=None, oa="zhangsan", thread_id=None, tool_calls=0, model_calls=0) -> str:
    started = utcnow() - timedelta(minutes=minutes_ago)
    run = Run(run_id=new_run_id(), thread_id=thread_id or new_thread_id(), tenant_id=rt.tenant_id, oa=oa,
              channel="oa_web", agent_id="oa_assistant", workflow_id="travel_query", workflow_version="1",
              run_status=status, started_at=started,
              ended_at=started + timedelta(milliseconds=duration_ms or 60_000) if ended else None,
              duration_ms=duration_ms, error_code=error_code, failed_node=failed_node, usage_json=usage,
              tool_call_count=tool_calls, model_call_count=model_calls)
    with rt.session() as db, db.begin():
        db.add(run)
    return run.run_id


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


@pytest.fixture
def seeded(rt):
    ids = {
        "ok1": add_run(rt, "succeeded", duration_ms=100, tool_calls=1),
        "ok2": add_run(rt, "succeeded", duration_ms=200, tool_calls=1),
        "ok3": add_run(rt, "succeeded", duration_ms=300, tool_calls=1, model_calls=1,
                       usage=[{"model": "m", "provider": "p",
                               "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}}]),
        "fail": add_run(rt, "failed", duration_ms=400, error_code="UPSTREAM_UNAVAILABLE", failed_node="call_tool",
                        tool_calls=1, oa="lisi"),
        "timeout": add_run(rt, "timed_out", error_code="RUN_TIMEOUT"),  # 巡检写入：无 duration_ms，按 60s 计
        "cancelled": add_run(rt, "cancelled", duration_ms=50),
        "stuck": add_run(rt, "running", minutes_ago=5, ended=False),
        "fresh": add_run(rt, "running", minutes_ago=0, ended=False),
        "old": add_run(rt, "succeeded", minutes_ago=24 * 60, duration_ms=10),
    }
    return ids


def test_stats_match_db_records(admin, seeded):
    r = admin.get("/v1/admin/runs/stats", params={"start": START, "end": END})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["total"] == 8
    assert s["by_status"]["succeeded"] == 3 and s["by_status"]["failed"] == 1
    assert s["by_status"]["timed_out"] == 1 and s["by_status"]["cancelled"] == 1 and s["by_status"]["expired"] == 0
    assert s["rate_denominator"] == 5 and s["success_rate"] == 0.6
    assert s["in_progress"] == 2 and s["suspected_stuck"] == 1
    # 已结束 6 个：50,100,200,300,400,60000 → 最近秩 P50 = 第 3 个
    assert s["duration_ms"] == {"samples": 6, "p50": 200, "p95": None, "p95_insufficient": True}
    assert s["tool_calls"] == 4 and s["model_calls"] == 1
    assert s["tokens"] == {"runs_with_usage": 1, "model_calls_with_usage": 1, "prompt_tokens": 50,
                           "completion_tokens": 20, "total_tokens": 70}
    assert sum(d["total"] for d in s["daily"]) == 8
    assert s["observability"]["status"] in ("ok", "degraded")


def test_stats_empty_shows_no_data(admin):
    s = admin.get("/v1/admin/runs/stats").json()
    assert s["total"] == 0 and s["success_rate"] is None and s["tokens"] is None
    assert s["duration_ms"]["p50"] is None and s["daily"] == []


def test_stats_without_usage_tokens_is_none(admin, rt):
    add_run(rt, "succeeded", duration_ms=100, model_calls=1)
    assert admin.get("/v1/admin/runs/stats", params={"start": START, "end": END}).json()["tokens"] is None


def test_stats_cached_30s_and_range_validation(admin, rt):
    first = admin.get("/v1/admin/runs/stats", params={"start": START, "end": END}).json()
    add_run(rt, "succeeded", duration_ms=1)
    second = admin.get("/v1/admin/runs/stats", params={"start": START, "end": END}).json()
    assert second["generated_at"] == first["generated_at"] and second["total"] == first["total"]
    rt.stats_cache.clear()
    assert admin.get("/v1/admin/runs/stats", params={"start": START, "end": END}).json()["total"] == first["total"] + 1

    assert admin.get("/v1/admin/runs/stats", params={"start": END, "end": START}).status_code == 422
    far = (NOW - timedelta(days=100)).isoformat()
    assert admin.get("/v1/admin/runs/stats", params={"start": far, "end": END}).status_code == 422


def test_p95_needs_20_samples():
    values = list(range(1, 21))
    assert percentile(values, 0.95) == 19 and percentile(values, 0.5) == 10
    assert percentile([], 0.5) is None
    assert sum_tokens([[{"usage": {"input_tokens": 3, "output_tokens": 4}}]])["total_tokens"] == 7
    assert sum_tokens([[{"usage": {}}], []]) is None


def test_top_errors(admin, seeded, rt):
    add_run(rt, "failed", duration_ms=10, error_code="UPSTREAM_UNAVAILABLE", failed_node="call_tool")
    items = admin.get("/v1/admin/runs/errors/top", params={"start": START, "end": END}).json()["items"]
    assert items[0]["error_code"] == "UPSTREAM_UNAVAILABLE" and items[0]["failed_node"] == "call_tool"
    assert items[0]["count"] == 2 and items[0]["sample_run_id"]
    assert {i["error_code"] for i in items} == {"UPSTREAM_UNAVAILABLE", "RUN_TIMEOUT"}


def test_list_filters_and_stuck_flag(admin, seeded):
    r = admin.get("/v1/admin/runs", params={"start": START, "end": END, "page_size": 100}).json()
    assert r["total"] == 8
    started = [i["started_at"] for i in r["items"]]
    assert started == sorted(started, reverse=True)
    by_id = {i["run_id"]: i for i in r["items"]}
    assert by_id[seeded["stuck"]]["suspected_stuck"] is True
    assert by_id[seeded["fresh"]]["suspected_stuck"] is False
    assert by_id[seeded["timeout"]]["duration_ms"] == 60_000

    assert [i["run_id"] for i in admin.get("/v1/admin/runs", params={"oa": "lisi"}).json()["items"]] == [seeded["fail"]]
    failed = admin.get("/v1/admin/runs", params={"status": "failed"}).json()["items"]
    assert [i["failed_node"] for i in failed] == ["call_tool"]
    assert admin.get("/v1/admin/runs", params={"stuck_only": True}).json()["total"] == 1
    assert admin.get("/v1/admin/runs", params={"status": "bogus"}).status_code == 422
    assert admin.get("/v1/admin/runs", params={"page_size": 101}).status_code == 422


def test_detail_and_events(admin, rt):
    thread = new_thread_id()
    run_id = add_run(rt, "failed", duration_ms=400, error_code="UPSTREAM_UNAVAILABLE", failed_node="call_tool",
                     thread_id=thread)
    add_run(rt, "succeeded", duration_ms=1, thread_id=thread)
    with rt.session() as db, db.begin():
        for seq in range(1, 6):
            db.add(RunEvent(event_id=new_event_id(), run_id=run_id, seq=seq, event_type="node_start",
                            node_name="n", occurred_at=datetime.now(UTC)))
    d = admin.get(f"/v1/admin/runs/{run_id}").json()
    assert d["failed_node"] == "call_tool" and d["event_count"] == 5 and d["thread_run_count"] == 2

    page1 = admin.get(f"/v1/admin/runs/{run_id}/events", params={"limit": 3}).json()
    assert [e["seq"] for e in page1["items"]] == [1, 2, 3] and page1["has_more"] is True
    page2 = admin.get(f"/v1/admin/runs/{run_id}/events", params={"after_seq": 3}).json()
    assert [e["seq"] for e in page2["items"]] == [4, 5] and page2["has_more"] is False

    assert admin.get("/v1/admin/runs/run_missing").status_code == 404
    assert admin.get("/v1/admin/runs/run_missing/events").status_code == 404


def test_requires_ops_run_view(admin, installed):
    role = _role(admin, "audit_only", ["ops.audit.view"])
    _user(admin, "auditor", [role["id"]])
    other = login(TestClient(installed.app), "auditor", VIEWER_PASS)
    for url in ("/v1/admin/runs", "/v1/admin/runs/stats", "/v1/admin/runs/errors/top", "/v1/admin/runs/run_x"):
        assert other.get(url).status_code == 403, url

    role2 = _role(admin, "run_viewer", ["ops.run.view"])
    _user(admin, "runviewer", [role2["id"]])
    viewer = login(TestClient(installed.app), "runviewer", VIEWER_PASS)
    assert viewer.get("/v1/admin/runs").status_code == 200
