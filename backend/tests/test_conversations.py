"""完整对话记录：原文落库（只去密钥）、模型调用原文、后台查看与训练导出（权限 + 审计）。"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from oa_agent.db.types import utcnow
from oa_agent.runtime.llm import ModelConfig
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_chat import LIST_URL, ROW, chat, office, open_chat, run_and_events, send  # noqa: F401

PHONE = "13812345678"
MESSAGE = f"查上周行程报销，有问题打我电话 {PHONE}"


def _window() -> dict:
    now = utcnow()
    return {"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(days=1)).isoformat()}


def _ask(chat, office, message=MESSAGE):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "list": [ROW], "total": 1}}))
    h = open_chat(chat)
    body = send(chat, h, message).json()
    run_and_events(chat, body["run_id"])
    return body


def test_full_conversation_is_stored_and_viewable(admin, chat, office):
    body = _ask(chat, office)
    run, events = run_and_events(chat, body["run_id"])
    assert PHONE in events[0].input_summary  # 个人信息不再打码

    r = admin.get("/v1/admin/conversations")
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["thread_id"] == run.thread_id and item["oa"] == "zhangsan" and item["message_count"] == 2
    assert item["first_message"] == MESSAGE

    d = admin.get(f"/v1/admin/conversations/{run.thread_id}").json()
    user, bot = d["messages"]
    assert user["role"] == "user" and user["content"] == MESSAGE and user["run_id"] == run.run_id
    assert bot["role"] == "assistant" and bot["content"] == body["reply"]["content"]
    assert bot["data"] == body["reply"]["data"]  # 员工看到的业务数据完整保存
    assert d["run_status"][run.run_id] == "succeeded"
    assert "tok-zhangsan" not in json.dumps(d, ensure_ascii=False)

    actions = [a["action"] for a in audit_rows(admin)]
    assert "conversation.list" in actions and "conversation.view" in actions

    assert admin.get("/v1/admin/conversations?keyword=打我电话").json()["total"] == 1
    assert admin.get("/v1/admin/conversations?keyword=不存在的词").json()["total"] == 0


def test_secrets_in_message_are_still_masked(admin, chat, office):
    body = _ask(chat, office, "查上周行程报销 token=abcdefgh12345678")
    run, _ = run_and_events(chat, body["run_id"])
    d = admin.get(f"/v1/admin/conversations/{run.thread_id}").json()
    assert "abcdefgh12345678" not in d["messages"][0]["content"]


def test_model_call_logged_without_reasoning(admin, chat, office, monkeypatch):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}}))
    content = [{"type": "thinking", "thinking": "隐藏推理内容"},
               {"type": "text", "text": json.dumps({"tool": "query_my_travel_expense_list",
                                                   "args": {"date_gte": "2026-09-01", "date_lte": "2026-09-30"}})}]
    fake = SimpleNamespace(invoke=lambda _: SimpleNamespace(
        content=content, response_metadata={"token_usage": {"prompt_tokens": 5, "completion_tokens": 3}}))
    cfg = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (fake, cfg))
    h = open_chat(chat)
    body = send(chat, h, "查九月的行程报销").json()
    run, _ = run_and_events(chat, body["run_id"])

    d = admin.get(f"/v1/admin/conversations/{run.thread_id}").json()
    call = d["model_calls"][0]
    assert call["model"] == "fake-model" and call["status"] == "ok" and call["run_id"] == run.run_id
    assert [m["role"] for m in call["messages"]] == ["system", "human"]
    assert "查九月的行程报销" in call["messages"][1]["content"]
    assert call["messages"][1]["content"].startswith("<<<UNTRUSTED_DATA source=user")
    assert call["parsed"]["tool"] == "query_my_travel_expense_list" and call["usage"]["prompt_tokens"] == 5
    assert "行程报销查询" in call["messages"][0]["content"], "提示词包含 Skill 说明"
    assert "隐藏推理内容" not in json.dumps(d, ensure_ascii=False)


def test_export_jsonl_requires_permission_and_is_audited(admin, chat, office, installed):
    body = _ask(chat, office)
    r = admin.get("/v1/admin/conversations/export", params=_window())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in r.text.splitlines()]
    assert len(lines) == 1 and lines[0]["thread_id"] == body["thread_id"]
    assert [m["role"] for m in lines[0]["messages"]] == ["user", "assistant"]
    assert lines[0]["messages"][0]["content"] == MESSAGE
    assert any(a["action"] == "conversation.export" for a in audit_rows(admin))

    now = utcnow()
    bad = admin.get("/v1/admin/conversations/export",
                    params={"start": (now - timedelta(days=100)).isoformat(), "end": now.isoformat()})
    assert bad.status_code == 422

    role = _role(admin, "run_viewer_c", ["ops.run.view"])
    _user(admin, "plainviewer", [role["id"]])
    viewer = login(TestClient(installed.app), "plainviewer", VIEWER_PASS)
    assert viewer.get("/v1/admin/conversations").status_code == 403
    assert viewer.get("/v1/admin/conversations/export", params=_window()).status_code == 403

    role2 = _role(admin, "sensitive_c", ["ops.run.view_sensitive"])
    _user(admin, "sensitiveviewer", [role2["id"]])
    sens = login(TestClient(installed.app), "sensitiveviewer", VIEWER_PASS)
    assert sens.get("/v1/admin/conversations").status_code == 200
    assert sens.get("/v1/admin/conversations/export", params=_window()).status_code == 403
