"""P6 加固：权限矩阵、CSRF/幂等全覆盖、事件保留期清理、性能基线。"""

from __future__ import annotations

import re
import time
import uuid
from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from oa_agent.db.models import AuditLog, Run, RunEvent
from oa_agent.db.types import utcnow
from tests.conftest import login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_chat import LIST_URL, ROW, chat, office, open_chat, runtime, send  # noqa: F401

# 只要求登录、不要求权限点的端点（本人会话/改密）
SELF_SERVICE = re.compile(r"^/v1/admin/auth/")
AUDIT_ONLY_OK = re.compile(r"^/v1/admin/audit")


def admin_routes(app) -> list[tuple[str, str]]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/v1/admin") and not SELF_SERVICE.match(path):
            for m in sorted(ops):
                out.append((m.upper(), re.sub(r"\{[^}]+\}", "x1", path)))
    return out


def call(client, method, path, headers=None):
    return client.request(method, path, json={}, headers=headers or {})


def test_permission_matrix_every_admin_endpoint(admin, installed):
    routes = admin_routes(installed.app)
    assert len(routes) >= 40, routes
    role = _role(admin, "audit_reader", ["ops.audit.view"])
    _user(admin, "matrix", [role["id"]])
    user = login(TestClient(installed.app), "matrix", VIEWER_PASS)
    wrong = []
    for method, path in routes:
        headers = {"X-CSRF-Token": user.csrf, "Idempotency-Key": uuid.uuid4().hex}
        status = call(user.client, method, path, headers).status_code
        expected_ok = method == "GET" and AUDIT_ONLY_OK.match(path)
        if (status == 403) == bool(expected_ok):
            wrong.append((method, path, status))
    assert wrong == [], wrong

    anonymous = TestClient(installed.app)
    unauth = [(m, p) for m, p in routes if call(anonymous, m, p).status_code != 401]
    assert unauth == []


def test_every_admin_write_requires_csrf_and_idempotency(admin, installed):
    writes = [(m, p) for m, p in admin_routes(installed.app) if m != "GET"]
    assert len(writes) >= 25
    missing_csrf, missing_idem = [], []
    for method, path in writes:
        r = call(admin.client, method, path, {"Idempotency-Key": uuid.uuid4().hex})
        if r.status_code != 403 or r.json()["error"]["code"] != "CSRF_FAILED":
            missing_csrf.append((method, path, r.status_code))
        r = call(admin.client, method, path, {"X-CSRF-Token": admin.csrf})
        if r.status_code != 400 or r.json()["error"]["code"] != "IDEMPOTENCY_KEY_REQUIRED":
            missing_idem.append((method, path, r.status_code))
    assert missing_csrf == [] and missing_idem == []


def test_duplicate_idempotency_key_executes_once(admin):
    rt = runtime(admin.client)

    def audit_count():
        with rt.session() as db:
            return db.scalar(sa.select(sa.func.count()).select_from(AuditLog).where(AuditLog.action == "tool.disable"))

    headers = {"Idempotency-Key": "same-key-123"}
    first = admin.post("/v1/admin/tools/query_my_travel_expense_list/disable", json={"reason": "维护"},
                       headers=headers)
    second = admin.post("/v1/admin/tools/query_my_travel_expense_list/disable", json={"reason": "维护"},
                        headers=headers)
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["error"]["code"] == "DUPLICATE_REQUEST"
    assert audit_count() == 1


def test_event_retention_purge(admin):
    rt = runtime(admin.client)
    now = utcnow()
    with rt.session() as db, db.begin():
        db.add(Run(run_id="run_old", thread_id="t", oa="zhangsan", channel="oa_web", agent_id="a", workflow_id="w",
                   workflow_version="1", run_status="succeeded", started_at=now - timedelta(days=200),
                   last_event_at=now))
        for i, days in enumerate((200, 190, 10), start=1):
            db.add(RunEvent(event_id=f"evt_old_{i}", run_id="run_old", seq=i, event_type="node_end",
                            occurred_at=now - timedelta(days=days), retry_count=0))
    assert rt.engine.runs.purge_events(180) == 2
    with rt.session() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(RunEvent).where(RunEvent.run_id == "run_old")) == 1
        assert db.scalar(sa.select(sa.func.count()).select_from(Run).where(Run.run_id == "run_old")) == 1
    assert rt.engine.runs.purge_events(0) == 0


@pytest.mark.perf
def test_performance_baseline(chat, office, admin, record_property):
    """性能基线（单进程 SQLite、mock office-api）：记录实测值，阈值只防止数量级退化。"""
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW] * 10}}))
    rt = runtime(chat)
    h = open_chat(chat)
    rt.settings_svc  # noqa: B018
    admin.put("/v1/admin/settings/runtime", json={"values": {"chat_rate_limit_per_min": 1000}})
    durations = []
    for _ in range(40):
        started = time.perf_counter()
        assert send(chat, h, "查上周的行程报销").json()["run_status"] == "succeeded"
        durations.append(time.perf_counter() - started)
    durations.sort()
    p95_chat = durations[int(len(durations) * 0.95) - 1]

    now = utcnow()
    with rt.session() as db, db.begin():
        db.execute(sa.insert(Run), [
            {"run_id": f"run_perf_{i}", "thread_id": f"t{i % 50}", "tenant_id": rt.tenant_id, "oa": f"u{i % 200}",
             "channel": "oa_web", "agent_id": "a", "workflow_id": "travel_query", "workflow_version": "1",
             "run_status": "succeeded" if i % 10 else "failed", "started_at": now - timedelta(minutes=i % 1400),
             "ended_at": now, "duration_ms": 100 + i % 900, "error_code": None if i % 10 else "UPSTREAM_TIMEOUT",
             "tool_call_count": 1, "model_call_count": 0, "last_event_at": now} for i in range(5000)])
    started = time.perf_counter()
    assert admin.get("/v1/admin/runs/stats").status_code == 200
    stats_s = time.perf_counter() - started
    started = time.perf_counter()
    assert admin.get("/v1/admin/runs", params={"page_size": 100, "status": "failed"}).status_code == 200
    list_s = time.perf_counter() - started

    record_property("chat_p95_s", round(p95_chat, 3))
    record_property("stats_5000_runs_s", round(stats_s, 3))
    record_property("list_5000_runs_s", round(list_s, 3))
    print(f"\n[perf] chat p95={p95_chat:.3f}s stats(5000 runs)={stats_s:.3f}s list={list_s:.3f}s")
    assert p95_chat < 1.0 and stats_s < 5.0 and list_s < 2.0
