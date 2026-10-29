"""X5：固定 Workflow 注册表与员工显式触发。"""

from __future__ import annotations

import httpx
import pytest

from oa_agent.auth import chat_launch
from oa_agent.chat.service import start_workflow
from oa_agent.errors import AppError
from oa_agent.runtime import workflow_catalog as wc
from tests.test_chat import DETAIL_URL, OFFICE, ROW, chat, office, open_chat, runtime  # noqa: F401
from tests.test_write_workflow import DRAFT_URL, SUBMIT_URL, _enable_write, _session


def test_catalog_lists_chat_and_write():
    items = wc.list_entries(write_enabled=False)
    ids = {i["workflow_id"] for i in items}
    assert "oa_assistant" in ids
    assert "travel_reimburse_submit" in ids
    write = next(i for i in items if i["kind"] == "write")
    assert write["available"] is False
    assert write["unavailable_reason"] == "write_workflows_disabled"
    assert wc.list_entries(write_enabled=True)[1]["available"] is True


def test_resolve_travel_query_alias():
    assert wc.resolve_id("travel_query") == "oa_assistant"
    assert wc.get("travel_query").workflow_id == "oa_assistant"


def test_session_includes_workflows(admin, chat, office):
    h = open_chat(chat)
    body = chat.get("/v1/chat/session", headers=h).json()
    assert "workflows" in body
    assert any(w["workflow_id"] == "oa_assistant" for w in body["workflows"])


def test_start_write_via_catalog_api(admin, chat, office):
    _enable_write(admin)
    office.get(DETAIL_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": ROW}))
    office.post(DRAFT_URL).mock(return_value=httpx.Response(
        200, json={"code": 0, "data": {"draft_id": 9001, "source_expense_id": 101, "total_amount": "120.00",
                                        "status": 0, "status_text": "待确认"}},
    ))
    h = open_chat(chat)
    r = chat.post(
        "/v1/chat/workflows/travel_reimburse_submit/start",
        headers=h,
        json={"expense_id": 101, "client_msg_id": "wf-start-1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["run_status"] == "waiting_confirmation"


def test_start_write_disabled_returns_503(admin, chat, office):
    h = open_chat(chat)
    r = chat.post(
        "/v1/chat/workflows/travel_reimburse_submit/start",
        headers=h,
        json={"expense_id": 101, "client_msg_id": "wf-start-2"},
    )
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "WRITE_WORKFLOWS_DISABLED"


def test_start_unknown_workflow(admin, chat, office):
    h = open_chat(chat)
    r = chat.post(
        "/v1/chat/workflows/nope/start",
        headers=h,
        json={"expense_id": 1, "client_msg_id": "wf-start-3"},
    )
    assert r.status_code == 404


def test_start_chat_workflow_rejected(admin, chat, office):
    """对话类走普通消息，不经 start。"""
    h = open_chat(chat)
    rt = runtime(chat)
    session = _session(chat, h)
    with pytest.raises(AppError) as err:
        start_workflow(rt, session, "oa_assistant", {"expense_id": 1}, "c", session_key="")
    assert err.value.code == "WORKFLOW_NOT_STARTABLE"
