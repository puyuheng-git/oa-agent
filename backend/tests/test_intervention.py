"""P3 验收：介入任务、取消、恢复（重验身份/状态/版本；Checkpoint 缺失拒绝）、重试、确认令牌。

- 未授权被拒；重复恢复不重复执行；不可恢复如实显示；管理员不能代员工确认。
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from oa_agent.auth import chat_launch
from oa_agent.db.models import InterventionTask, Run
from oa_agent.db.types import utcnow
from oa_agent.runtime import confirmation
from oa_agent.runtime.confirmation import ConfirmationError
from oa_agent.runtime.graphs import travel_query
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_chat import LIST_URL, ROW, chat, office, open_chat, run_and_events, runtime, send  # noqa: F401
from tests.workflow_helpers import publish_config

OK_LIST = httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}})
DOWN = httpx.Response(503, text="maintenance")


@pytest.fixture
def handoff(chat, admin):
    """发布配置 on_upstream_error=handoff。"""
    publish_config(admin, {"on_upstream_error": "handoff"})
    return chat


def _task_for(rt, run_id) -> InterventionTask:
    with rt.session() as db:
        return db.scalar(sa.select(InterventionTask).where(InterventionTask.run_id == run_id))


def _handoff_run(client, office_mock, admin_client=None):
    route = office_mock.get(LIST_URL).mock(side_effect=[DOWN, OK_LIST, OK_LIST])
    h = open_chat(client)
    body = send(client, h, "查上周的行程报销").json()
    return route, h, body


def test_upstream_error_hands_off_to_human(handoff, office):
    route, h, body = _handoff_run(handoff, office)
    assert body["run_status"] == "waiting_human" and body["reply"]["type"] == "pending"
    rt = runtime(handoff)
    run, events = run_and_events(handoff, body["run_id"])
    assert run.run_status == "waiting_human" and run.error_code == "UPSTREAM_HTTP_ERROR"
    types = [e.event_type for e in events]
    assert "node_interrupted" in types and "run_waiting_human" in types and "run_end" not in types
    task = _task_for(rt, body["run_id"])
    assert task.kind == "admin" and task.status == "pending" and task.version == 1

    poll = handoff.get(f"/v1/chat/runs/{body['run_id']}", headers=h).json()
    assert poll == {"run_id": body["run_id"], "run_status": "waiting_human", "done": False, "reply": None}
    # 其他员工看不到
    other = open_chat(handoff, oa="lisi")
    assert handoff.get(f"/v1/chat/runs/{body['run_id']}", headers=other).status_code == 404


def test_resume_reexecutes_once_and_duplicate_is_rejected(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    rt = runtime(handoff)
    task = _task_for(rt, body["run_id"])
    detail = admin.get(f"/v1/admin/interventions/{task.task_id}").json()
    assert detail["resumable"] == {"ok": True, "reasons": []}

    r = admin.post(f"/v1/admin/interventions/{task.task_id}/resume", json={"reason": "上游已恢复", "version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["run_status"] == "succeeded"
    assert route.call_count == 2

    again = admin.post(f"/v1/admin/interventions/{task.task_id}/resume", json={"reason": "再来一次", "version": 1})
    assert again.status_code == 409
    assert route.call_count == 2, "重复恢复不得重复执行"

    run, events = run_and_events(handoff, body["run_id"])
    assert run.run_status == "succeeded" and run.error_code is None and run.tool_call_count == 2
    resume_evt = next(e for e in events if e.event_type == "operator_resume")
    assert resume_evt.operator_id == "root_admin"
    assert [e.seq for e in events] == list(range(1, len(events) + 1)), "恢复后 seq 连续"
    assert _task_for(rt, body["run_id"]).status == "resolved"

    poll = handoff.get(f"/v1/chat/runs/{body['run_id']}", headers=h).json()
    assert poll["done"] and poll["reply"]["data"]["items"][0]["id"] == 101
    assert any(a["action"] == "intervention.resume" for a in audit_rows(admin))


def test_resume_refused_when_employee_session_gone(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    rt = runtime(handoff)
    rt.kv.current.delete(chat_launch.session_key(h["Authorization"][7:]))
    task = _task_for(rt, body["run_id"])
    detail = admin.get(f"/v1/admin/interventions/{task.task_id}").json()
    assert detail["resumable"]["ok"] is False and "员工会话已过期" in detail["resumable"]["reasons"][0]

    r = admin.post(f"/v1/admin/interventions/{task.task_id}/resume", json={"reason": "试试", "version": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_RECOVERABLE"
    assert route.call_count == 1
    assert _task_for(rt, body["run_id"]).status == "pending"
    assert any(a["action"] == "intervention.resume" and a["result"] == "rejected" for a in audit_rows(admin))

    # 仍可终止
    t = admin.post(f"/v1/admin/interventions/{task.task_id}/terminate", json={"reason": "无法恢复", "version": 1})
    assert t.status_code == 200, t.text
    run, _ = run_and_events(handoff, body["run_id"])
    assert run.run_status == "failed" and run.error_code == "HUMAN_TERMINATED"


def test_resume_refused_when_checkpoint_missing(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    rt = runtime(handoff)
    run, _ = run_and_events(handoff, body["run_id"])
    rt.engine.checkpointer.delete_thread(run.thread_id)
    task = _task_for(rt, body["run_id"])
    r = admin.post(f"/v1/admin/interventions/{task.task_id}/resume", json={"reason": "试试", "version": 1})
    assert r.status_code == 409 and "Checkpoint" in r.json()["error"]["message"]
    assert route.call_count == 1


def test_new_message_supersedes_waiting_run(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    rt = runtime(handoff)
    second = send(handoff, h, "查上周的行程报销").json()
    assert second["run_status"] == "succeeded"
    run, events = run_and_events(handoff, body["run_id"])
    assert run.run_status == "cancelled" and run.error_code == "RUN_SUPERSEDED"
    assert _task_for(rt, body["run_id"]).status == "cancelled"


def test_terminate_and_employee_sees_result(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    task = _task_for(runtime(handoff), body["run_id"])
    r = admin.post(f"/v1/admin/interventions/{task.task_id}/terminate", json={"reason": "上游长时间维护", "version": 1})
    assert r.status_code == 200, r.text
    poll = handoff.get(f"/v1/chat/runs/{body['run_id']}", headers=h).json()
    assert poll["done"] and poll["reply"]["error_code"] == "HUMAN_TERMINATED"
    _, events = run_and_events(handoff, body["run_id"])
    assert any(e.event_type == "operator_terminate" and e.operator_id == "root_admin" for e in events)


def test_watchdog_expires_pending_task(handoff, office):
    route, h, body = _handoff_run(handoff, office)
    rt = runtime(handoff)
    with rt.session() as db, db.begin():
        db.execute(sa.update(InterventionTask).values(expire_at=utcnow() - timedelta(minutes=1)))
    rt.engine.watchdog_tick()
    run, events = run_and_events(handoff, body["run_id"])
    assert run.run_status == "failed" and run.error_code == "INTERVENTION_EXPIRED"
    assert _task_for(rt, body["run_id"]).status == "expired"
    assert events[-1].event_type == "run_end"


# ---------------- 取消 ----------------

def test_cancel_waiting_and_terminal(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    rt = runtime(handoff)
    r = admin.post(f"/v1/admin/runs/{body['run_id']}/cancel", json={"reason": "员工已线下处理"})
    assert r.status_code == 200 and r.json()["run_status"] == "cancelled"
    assert _task_for(rt, body["run_id"]).status == "cancelled"
    again = admin.post(f"/v1/admin/runs/{body['run_id']}/cancel", json={"reason": "再取消"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "RUN_ALREADY_ENDED"
    poll = handoff.get(f"/v1/chat/runs/{body['run_id']}", headers=h).json()
    assert poll["reply"]["error_code"] == "RUN_CANCELLED"
    assert any(a["action"] == "run.cancel" for a in audit_rows(admin))


def test_cancel_in_flight_stops_before_next_node(chat, office):
    rt = runtime(chat)

    def slow_list(request):
        with rt.session() as db:
            run_id = db.scalar(sa.select(Run.run_id).where(Run.run_status == "running"))
        rt.engine.runs.transition(run_id, "running", "cancel_requested")
        rt.engine.request_cancel(run_id)
        return OK_LIST

    office.get(LIST_URL).mock(side_effect=slow_list)
    h = open_chat(chat)
    body = send(chat, h, "查上周的行程报销").json()
    assert body["run_status"] == "cancelled" and body["reply"]["error_code"] == "RUN_CANCELLED"
    run, events = run_and_events(chat, body["run_id"])
    assert run.run_status == "cancelled"
    assert any(e.event_type == "run_cancel_observed" and e.node_name == "respond" for e in events)


def test_cancel_running_marks_cancel_requested_then_restart_recovers(admin):
    rt = runtime(admin.client)
    now = utcnow()
    with rt.session() as db, db.begin():
        db.add(Run(run_id="run_live", thread_id="thr_x", oa="zhangsan", channel="oa_web", agent_id="a",
                   workflow_id="travel_query", workflow_version="1", run_status="running", started_at=now,
                   last_event_at=now))
    r = admin.post("/v1/admin/runs/run_live/cancel", json={"reason": "卡住了"})
    assert r.status_code == 200 and r.json()["run_status"] == "cancel_requested"
    rt.engine.runs.recover_interrupted()
    with rt.session() as db:
        assert db.scalar(sa.select(Run.run_status).where(Run.run_id == "run_live")) == "cancelled"


# ---------------- 重试 ----------------

def test_retry_failed_run_creates_child(chat, office, admin):
    route = office.get(LIST_URL).mock(side_effect=[DOWN, OK_LIST])
    h = open_chat(chat)
    body = send(chat, h, "查上周的行程报销").json()
    assert body["run_status"] == "failed"
    detail = admin.get(f"/v1/admin/runs/{body['run_id']}").json()
    assert detail["can_retry"] is True and detail["can_cancel"] is False

    r = admin.post(f"/v1/admin/runs/{body['run_id']}/retry", json={"reason": "上游已恢复"})
    assert r.status_code == 200, r.text
    child_id = r.json()["new_run_id"]
    assert r.json()["new_run_status"] == "succeeded" and route.call_count == 2
    child, events = run_and_events(chat, child_id)
    assert child.parent_run_id == body["run_id"] and child.oa == "zhangsan"
    assert any(e.event_type == "operator_retry" and e.operator_id == "root_admin" for e in events)
    assert admin.get(f"/v1/admin/runs/{body['run_id']}").json()["child_runs"][0]["run_id"] == child_id

    ok = admin.post(f"/v1/admin/runs/{child_id}/retry", json={"reason": "成功的不能重试"})
    assert ok.status_code == 409 and ok.json()["error"]["code"] == "RUN_NOT_RETRYABLE"


def test_retry_refused_without_session(chat, office, admin):
    office.get(LIST_URL).mock(return_value=DOWN)
    h = open_chat(chat)
    body = send(chat, h, "查上周的行程报销").json()
    runtime(chat).kv.current.delete(chat_launch.session_key(h["Authorization"][7:]))
    r = admin.post(f"/v1/admin/runs/{body['run_id']}/retry", json={"reason": "试试"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_NOT_RECOVERABLE"


# ---------------- 权限 ----------------

def test_operations_require_permissions(handoff, office, admin):
    route, h, body = _handoff_run(handoff, office)
    task = _task_for(runtime(handoff), body["run_id"])
    role = _role(admin, "run_viewer2", ["ops.run.view"])
    _user(admin, "viewer2", [role["id"]])
    viewer = login(TestClient(handoff.app), "viewer2", VIEWER_PASS)
    assert viewer.get("/v1/admin/interventions").status_code == 403
    assert viewer.post(f"/v1/admin/interventions/{task.task_id}/resume",
                       json={"reason": "越权", "version": 1}).status_code == 403
    assert viewer.post(f"/v1/admin/runs/{body['run_id']}/cancel", json={"reason": "越权"}).status_code == 403
    assert viewer.post(f"/v1/admin/runs/{body['run_id']}/retry", json={"reason": "越权"}).status_code == 403
    assert route.call_count == 1
    assert _task_for(runtime(handoff), body["run_id"]).status == "pending"
    # 缺 CSRF
    no_csrf = handoff.post(f"/v1/admin/interventions/{task.task_id}/resume",
                           json={"reason": "无 csrf", "version": 1}, headers={"Idempotency-Key": "k-123"})
    assert no_csrf.status_code == 403


def test_admin_cannot_confirm_for_employee(admin):
    rt = runtime(admin.client)
    with rt.session() as db, db.begin():
        issued = confirmation.issue(db, rt.tenant_id, run_id="run_c", oa="zhangsan", workflow_version="1",
                                    payload={"action": "submit", "id": 1}, reason="提交报销单")
    r = admin.post(f"/v1/admin/interventions/{issued.task_id}/resume", json={"reason": "代办", "version": 1})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_CANNOT_CONFIRM"
    r = admin.post(f"/v1/admin/interventions/{issued.task_id}/terminate", json={"reason": "代办", "version": 1})
    assert r.status_code == 403
    assert any(a["result"] == "denied" and a["action"] == "intervention.resume" for a in audit_rows(admin))


# ---------------- 确认令牌 ----------------

def test_confirmation_token_rules(admin):
    rt = runtime(admin.client)
    payload = {"action": "submit", "id": 9}
    with rt.session() as db, db.begin():
        issued = confirmation.issue(db, rt.tenant_id, run_id="run_k", oa="zhangsan", workflow_version="1",
                                    payload=payload, reason="提交")
    with rt.session() as db:
        stored = db.scalar(sa.select(InterventionTask).where(InterventionTask.task_id == issued.task_id))
        assert issued.token not in (stored.confirm_token_hash or "") and len(stored.confirm_token_hash) == 64

    def check(**kw):
        args = {"task_id": issued.task_id, "token": issued.token, "oa": "zhangsan", "payload": payload, **kw}
        with rt.session() as db, db.begin():
            return confirmation.verify_and_consume(db, **args)

    for kw, code in (({"oa": "lisi"}, "CONFIRMATION_FORBIDDEN"), ({"token": "x" * 43}, "CONFIRMATION_INVALID"),
                     ({"payload": {"action": "submit", "id": 10}}, "CONFIRMATION_MISMATCH"),
                     ({"now": utcnow() + timedelta(minutes=10)}, "CONFIRMATION_EXPIRED")):
        with pytest.raises(ConfirmationError) as err:
            check(**kw)
        assert err.value.code == code
    consumed = check()
    assert consumed.status == "resolved" and consumed.result == "confirmed"
    with pytest.raises(ConfirmationError) as err:
        check()
    assert err.value.code == "CONFIRMATION_USED"


def test_default_config_does_not_hand_off():
    assert travel_query.DEFAULT_CONFIG["on_upstream_error"] == "fail"
