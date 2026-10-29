"""O2：行程报销写闭环（flag、respx mock office-api、确认恢复）。"""

from __future__ import annotations

import uuid

import httpx
import pytest

from oa_agent.auth import chat_launch
from oa_agent.chat.service import start_travel_reimburse_submit
from oa_agent.errors import AppError
from tests.test_chat import DETAIL_URL, GATEWAY, HMAC_SECRET, OFFICE, ROW, chat, mint_handler, office, open_chat, runtime  # noqa: F401

DRAFT_URL = f"{OFFICE}/out_attendance/go_out_travel_expense/submit/draft"
SUBMIT_URL = f"{OFFICE}/out_attendance/go_out_travel_expense/submit"


def _session(client, headers):
    rt = runtime(client)
    ticket = headers["Authorization"][7:]
    return chat_launch.load_session(rt.kv.current, ticket)


def _enable_write(admin):
    r = admin.put("/v1/admin/settings/runtime", json={"values": {"write_workflows_enabled": True}})
    assert r.status_code == 200, r.text


def test_write_workflow_disabled_by_default(admin, chat, office):
    h = open_chat(chat)
    rt = runtime(chat)
    session = _session(chat, h)
    with pytest.raises(AppError) as err:
        start_travel_reimburse_submit(rt, session, 101, "test-corr")
    assert err.value.code == "WRITE_WORKFLOWS_DISABLED"


def test_write_workflow_closed_loop(admin, chat, office):
    _enable_write(admin)
    office.get(DETAIL_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": ROW}))
    office.post(DRAFT_URL).mock(return_value=httpx.Response(
        200, json={"code": 0, "data": {"draft_id": 9001, "source_expense_id": 101, "total_amount": "120.00",
                                        "status": 0, "status_text": "待确认"}},
    ))
    office.post(SUBMIT_URL).mock(return_value=httpx.Response(
        200, json={"code": 0, "data": {"submit_id": 7001, "draft_id": 9001, "status": 1, "status_text": "已提交"}},
    ))

    h = open_chat(chat)
    rt = runtime(chat)
    session = _session(chat, h)
    body = start_travel_reimburse_submit(rt, session, 101, "corr-1", session_key=chat_launch.session_key(h["Authorization"][7:]))
    assert body["run_status"] == "waiting_confirmation"
    assert body["reply"]["type"] == "confirmation_pending"
    token = body["reply"]["data"]["token"]
    task_id = body["reply"]["data"]["task_id"]
    assert token and task_id

    confirmed = chat.post(f"/v1/chat/confirmations/{task_id}", headers=h, json={"token": token})
    assert confirmed.status_code == 200, confirmed.text
    out = confirmed.json()
    assert out["run_status"] == "succeeded"
    assert "已提交" in out["reply"]["content"]
    assert office.post(DRAFT_URL).called
    assert office.post(SUBMIT_URL).called
    submit_req = office.post(SUBMIT_URL).calls[0].request
    assert submit_req.headers.get("Idempotency-Key")
    assert submit_req.headers.get("Authorization") == "tok-zhangsan"
    assert "oa" not in (submit_req.url.query or b"").decode()


def test_write_workflow_flag_off_via_settings(admin, chat, office):
    """显式关闭时拒绝（与默认一致）。"""
    r = admin.put("/v1/admin/settings/runtime", json={"values": {"write_workflows_enabled": False}})
    assert r.status_code == 200, r.text
    h = open_chat(chat)
    rt = runtime(chat)
    session = _session(chat, h)
    with pytest.raises(AppError) as err:
        start_travel_reimburse_submit(rt, session, 101, uuid.uuid4().hex)
    assert err.value.code == "WRITE_WORKFLOWS_DISABLED"
