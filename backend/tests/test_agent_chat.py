"""日常聊天 + 按语义自动选 Tool：模型理解员工原话决定查询还是直接回答，多轮追问沿用上下文。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx

from oa_agent.runtime.graphs import travel_query
from oa_agent.runtime.llm import ModelConfig
from tests.test_chat import (  # noqa: F401
    DETAIL_URL, LIST_URL, ROW, chat, office, open_chat, run_and_events, runtime, send,
)
from tests.workflow_helpers import WF, publish_config

CFG = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})


class ScriptedModel:
    """按顺序返回预设输出，并记录每次收到的消息。"""

    def __init__(self, outputs: list):
        self.outputs = list(outputs)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        out = self.outputs.pop(0)
        content = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return SimpleNamespace(content=content, response_metadata={"token_usage": {"prompt_tokens": 5}})


def use_model(monkeypatch, outputs: list) -> ScriptedModel:
    model = ScriptedModel(outputs)
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (model, CFG))
    return model


def test_small_talk_is_answered_by_model_without_calling_office(chat, office, monkeypatch):
    route = office.get(LIST_URL)
    model = use_model(monkeypatch, [{"action": "chat", "reply": "你好！今天有什么可以帮你？"}])
    h = open_chat(chat)
    body = send(chat, h, "早上好呀").json()
    assert body["run_status"] == "succeeded"
    assert body["reply"] == {"type": "markdown", "content": "你好！今天有什么可以帮你？", "data": None}
    assert not route.called
    system = model.calls[0][0][1]
    assert "query_my_travel_expense_list" in system and '"action": "chat"' in system
    run, events = run_and_events(chat, body["run_id"])
    understand = next(json.loads(e.output_summary) for e in events
                      if e.event_type == "node_end" and e.node_name == "understand")
    assert understand["intent"] == "chat" and understand["intent_source"] == "llm"
    assert run.tool_call_count == 0 and run.model_call_count == 1


def test_plain_text_model_output_is_treated_as_chat(chat, office, monkeypatch):
    use_model(monkeypatch, ["Python 是一种编程语言。"])
    h = open_chat(chat)
    body = send(chat, h, "python 是什么").json()
    assert body["run_status"] == "succeeded" and body["reply"]["content"] == "Python 是一种编程语言。"


def test_broken_json_falls_back_to_rules(chat, office, monkeypatch):
    use_model(monkeypatch, ['{"action": "tool", "tool": '])
    h = open_chat(chat)
    body = send(chat, h, "你好").json()
    assert "行程报销" in body["reply"]["content"], "无效输出回退规则，规则下非查询问题回复帮助"


def test_colloquial_question_calls_tool_and_followups_use_context(chat, office, monkeypatch):
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "list": [ROW, {**ROW, "id": 102}], "total": 2}}))
    detail = office.get(DETAIL_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"info": ROW}}))
    model = use_model(monkeypatch, [
        {"action": "tool", "tool": "query_my_travel_expense_list",
         "args": {"date_gte": "2026-09-01", "date_lte": "2026-09-30"}},
        {"action": "tool", "tool": "query_my_travel_expense_list",
         "args": {"date_gte": "2026-08-01", "date_lte": "2026-08-31"}},
        {"action": "tool", "tool": "query_my_travel_expense_detail", "args": {"id": 102}},
        {"action": "chat", "reply": "不客气！"},
    ])
    h = open_chat(chat)
    first = send(chat, h, "九月份跑客户花的钱都报了没").json()
    assert first["reply"]["data"]["kind"] == "table"
    assert json.loads(route.calls.last.request.url.params["queryParams"])["date_gte"] == "2026-09-01"

    second = send(chat, h, "那八月呢").json()
    assert second["run_status"] == "succeeded"
    assert json.loads(route.calls.last.request.url.params["queryParams"])["date_gte"] == "2026-08-01"
    history = model.calls[1][1:-1]
    assert [role for role, _ in history] == ["human", "ai"]
    assert history[0][1] == "九月份跑客户花的钱都报了没"
    assert "query_my_travel_expense_list" in history[1][1] and "101，102" in history[1][1]
    assert "客户A" not in history[1][1], "历史里只有查询摘要，不含业务明细"
    assert model.calls[1][-1][0] == "human" and "那八月呢" in model.calls[1][-1][1]
    assert model.calls[1][-1][1].startswith("<<<UNTRUSTED_DATA source=user")

    third = send(chat, h, "第二条详细看看").json()
    assert third["reply"]["data"]["kind"] == "record"
    assert json.loads(detail.calls.last.request.url.params["queryParams"]) == {"id": 102, "oa": "zhangsan"}

    fourth = send(chat, h, "谢谢").json()
    assert fourth["reply"]["content"] == "不客气！"
    assert len(model.calls[3]) == 1 + 3 * 2 + 1, "带之前 3 轮（6 条）历史"
    assert "返回记录 ID 101" in model.calls[3][-2][1]


def test_history_is_bounded(chat, office, monkeypatch):
    turns = travel_query.DEFAULT_CONFIG["history_turns"]
    outputs = [{"action": "chat", "reply": f"回复{i}"} for i in range(turns + 3)]
    model = use_model(monkeypatch, outputs)
    h = open_chat(chat)
    for i in range(len(outputs)):
        send(chat, h, f"消息{i}")
    last = model.calls[-1]
    assert len(last) == 1 + turns * 2 + 1
    assert last[1] == ("human", "消息2")
    system = last[0][1]
    assert "## 更早对话的记忆" in system and "员工：消息0" in system and "助手：回复1" in system, \
        "默认截断压缩：移出的旧对话进入记忆"


def test_history_is_per_session(chat, office, monkeypatch):
    model = use_model(monkeypatch, [{"action": "chat", "reply": "a"}, {"action": "chat", "reply": "b"}])
    send(chat, open_chat(chat), "我叫小王")
    send(chat, open_chat(chat, oa="lisi"), "我叫什么")
    assert len(model.calls[1]) == 2, "另一个会话看不到前一个会话的历史"


def test_chat_works_without_any_skill_when_model_available(chat, office, admin, monkeypatch):
    admin.post("/v1/admin/skills/travel_expense_query/disable", json={"reason": "暂停"})
    model = use_model(monkeypatch, [{"action": "chat", "reply": "目前暂不支持查询，但可以聊聊别的。"}])
    h = open_chat(chat)
    body = send(chat, h, "帮我查下报销").json()
    assert body["run_status"] == "succeeded" and "暂不支持" in body["reply"]["content"]
    assert "当前没有开放任何查询工具" in model.calls[0][0][1]


def test_model_cannot_pick_unavailable_tool(chat, office, admin, monkeypatch):
    admin.post("/v1/admin/skills/travel_expense_query/disable", json={"reason": "暂停"})
    route = office.get(LIST_URL)
    use_model(monkeypatch, [{"action": "tool", "tool": "query_my_travel_expense_list", "args": {}}])
    h = open_chat(chat)
    body = send(chat, h, "查报销").json()
    assert body["run_status"] == "succeeded" and not route.called
    assert body["reply"]["data"] is None


def test_chat_mode_help_keeps_help_reply(chat, office, admin, monkeypatch):
    publish_config(admin, {"chat_mode": "help"})
    model = use_model(monkeypatch, [{"action": "chat", "reply": "随便聊"}])
    h = open_chat(chat)
    body = send(chat, h, "你好").json()
    assert "行程报销" in body["reply"]["content"] and "随便聊" not in body["reply"]["content"]
    assert '"action": "chat"' not in model.calls[0][0][1], "help 模式用工具选择提示词"


def test_chat_instructions_are_sent_to_model(chat, office, admin, monkeypatch):
    publish_config(admin, {"chat_instructions": "回答控制在三句话以内"})
    model = use_model(monkeypatch, [{"action": "chat", "reply": "好"}])
    send(chat, open_chat(chat), "介绍一下你自己")
    assert "回答控制在三句话以内" in model.calls[0][0][1]


def test_without_model_skill_disabled_still_rejected(chat, office, admin):
    admin.post("/v1/admin/skills/travel_expense_query/disable", json={"reason": "暂停"})
    body = send(chat, open_chat(chat), "你好").json()
    assert body["reply"]["error_code"] == "SKILL_DISABLED"


def test_session_reports_chat_availability(chat, office, monkeypatch):
    h = open_chat(chat)
    assert chat.get("/v1/chat/session", headers=h).json()["chat"] is False
    monkeypatch.setattr("oa_agent.chat.service.resolve_model", lambda *a, **k: CFG)
    assert chat.get("/v1/chat/session", headers=h).json()["chat"] is True


def test_old_release_without_chat_fields_validates_and_defaults(chat, admin):
    current = admin.get(WF).json()["current_version"]["content"]
    old = {k: v for k, v in current.items() if k not in ("chat_mode", "chat_instructions")}
    assert admin.put(f"{WF}/draft", json={"content": old}).status_code == 200
    assert admin.post(f"{WF}/draft/validate").json()["status"] == "validated"
    bad = {**current, "chat_mode": "free"}
    admin.put(f"{WF}/draft", json={"content": bad})
    r = admin.post(f"{WF}/draft/validate").json()
    assert r["status"] == "draft" and any("非查询问题" in e for e in r["validation"]["errors"])
    schema = admin.get(f"{WF}/schema").json()
    assert schema["defaults"]["chat_mode"] == "llm"
    assert {"chat_mode", "chat_instructions"} <= {f["key"] for f in schema["fields"]}
