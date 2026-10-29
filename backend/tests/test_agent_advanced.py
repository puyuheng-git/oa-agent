"""流式输出、引用式多工具串联、会话压缩、角色设定与新增发布配置项。"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx

from oa_agent.runtime.graphs import travel_query as tq
from oa_agent.runtime.llm import ReplyStream
from tests.test_agent_chat import CFG, ScriptedModel, use_model
from tests.test_chat import (  # noqa: F401
    DETAIL_URL, LIST_URL, ROW, chat, office, open_chat, run_and_events, runtime, send,
)
from tests.workflow_helpers import WF, publish_config


class StreamingModel(ScriptedModel):
    """支持 stream：把预设输出按固定长度切片逐段返回，最后一段带 usage。"""

    def __init__(self, outputs: list, size: int = 3):
        super().__init__(outputs)
        self.size = size

    def stream(self, messages):
        self.calls.append(list(messages))
        out = self.outputs.pop(0)
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        for i in range(0, len(text), self.size):
            yield SimpleNamespace(content=text[i:i + self.size], usage_metadata=None, response_metadata={})
        yield SimpleNamespace(content="", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
                              response_metadata={})


def use_streaming(monkeypatch, outputs: list) -> StreamingModel:
    model = StreamingModel(outputs)
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (model, CFG))
    return model


def send_stream(client, headers, message):
    r = client.post("/v1/chat/messages/stream", headers=headers,
                    json={"message": message, "client_msg_id": uuid.uuid4().hex})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in r.text.split("\n\n"):
        lines = [x for x in block.splitlines() if not x.startswith(":")]
        if not lines:
            continue
        event = lines[0].removeprefix("event: ")
        events.append((event, json.loads(lines[1].removeprefix("data: "))))
    return events


# ---------------- 流式 ----------------

def test_reply_stream_extracts_reply_field_incrementally():
    pieces: list[str] = []
    s = ReplyStream(pieces.append)
    raw = '{"action": "chat", "reply": "你\\n好\\u4e16\\"界\\""}'
    for ch in raw:
        s.feed(ch)
    assert "".join(pieces) == '你\n好世"界"'
    assert len(pieces) > 1, "逐段输出"

    tool: list[str] = []
    s = ReplyStream(tool.append)
    for ch in '{"action": "tool", "tool": "q", "args": {"reply_to": "x"}}':
        s.feed(ch)
    assert tool == [], "工具调用 JSON 不输出任何内容"

    text: list[str] = []
    s = ReplyStream(text.append, allow_text=True)
    for ch in "纯文本回答":
        s.feed(ch)
    assert "".join(text) == "纯文本回答"

    leak: list[str] = []
    s = ReplyStream(leak.append, allow_text=False)
    for ch in "We need answer JSON only. User asks current time.":
        s.feed(ch)
    assert leak == [], "英文思考过程默认不向员工流式输出"


def test_text_as_chat_rejects_meta_leak_and_english_reasoning():
    from oa_agent.runtime.graphs.travel_query import _text_as_chat

    assert _text_as_chat("你好，今天可以问我报销相关问题。")["reply"].startswith("你好")
    assert _text_as_chat('We need answer JSON only. User asks current time. Could') is None
    assert _text_as_chat("System says today date but no current clock time given.") is None
    assert _text_as_chat('{"action": "chat", "reply": "x"}') is None


def test_sse_streams_chat_reply(chat, office, monkeypatch):
    use_streaming(monkeypatch, [{"action": "chat", "reply": "你好！这是一段比较长的回答。"}])
    events = send_stream(chat, open_chat(chat), "你好")
    deltas = [d["text"] for e, d in events if e == "delta"]
    assert len(deltas) > 1 and "".join(deltas) == "你好！这是一段比较长的回答。"
    kind, done = events[-1]
    assert kind == "done" and done["run_status"] == "succeeded"
    assert done["reply"]["content"] == "你好！这是一段比较长的回答。"
    run, _ = run_and_events(chat, done["run_id"])
    assert run.usage_json[0]["usage"]["input_tokens"] == 7, "流式也记录提供方 usage"


def test_sse_tool_reply_sent_once_without_model_json(chat, office, monkeypatch):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}}))
    use_streaming(monkeypatch, [{"action": "tool", "tool": "query_my_travel_expense_list", "args": {}}])
    events = send_stream(chat, open_chat(chat), "我的报销")
    deltas = [d["text"] for e, d in events if e == "delta"]
    assert len(deltas) == 1 and "共查到 **1** 条" in deltas[0]
    assert not any("action" in d for d in deltas)
    assert events[-1][1]["reply"]["data"]["kind"] == "table"


def test_stream_output_off_sends_only_done(chat, office, admin, monkeypatch):
    publish_config(admin, {"stream_output": False})
    use_streaming(monkeypatch, [{"action": "chat", "reply": "好的"}])
    events = send_stream(chat, open_chat(chat), "你好")
    assert [e for e, _ in events] == ["done"]


def test_sse_validation_errors_are_plain_json(chat, office, admin):
    admin.put("/v1/admin/settings/chat", json={"values": {"message_max_chars": 20}})
    r = chat.post("/v1/chat/messages/stream", headers=open_chat(chat),
                  json={"message": "长" * 21, "client_msg_id": uuid.uuid4().hex})
    assert r.status_code == 422 and "20" in r.json()["error"]["message"]


# ---------------- 引用式串联 ----------------

CHAIN = {"action": "tool", "steps": [
    {"tool": "query_my_travel_expense_list", "args": {"limit": 1}},
    {"tool": "query_my_travel_expense_detail", "args": {"id": {"$ref": "step1.list[0].id"}}},
]}


def test_chain_resolves_ref_on_server(chat, office, monkeypatch):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "list": [{**ROW, "id": 205}], "total": 9}}))
    detail = office.get(DETAIL_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "info": {**ROW, "id": 205}}}))
    model = use_model(monkeypatch, [CHAIN])
    body = send(chat, open_chat(chat), "我最近一笔报销的详情").json()
    assert body["run_status"] == "succeeded"
    assert json.loads(detail.calls.last.request.url.params["queryParams"]) == {"id": 205, "oa": "zhangsan"}
    assert body["reply"]["data"]["kind"] == "record" and body["reply"]["chain"] == [
        "query_my_travel_expense_list", "query_my_travel_expense_detail"]
    assert "已依次查询" in body["reply"]["content"]
    assert len(model.calls) == 1, "模型只规划一次，看不到第一步的返回值"
    system = model.calls[0][0][1]
    assert "$ref" in system and "返回：列表 list" in system
    run, events = run_and_events(chat, body["run_id"])
    assert run.tool_call_count == 2
    steps = [json.loads(e.input_summary) for e in events if e.event_type == "node_start" and e.node_name == "call_tool"]
    assert [s["step"] for s in steps] == ["1/2", "2/2"]


def test_chain_stops_when_ref_has_no_value(chat, office, monkeypatch):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}}))
    detail = office.get(DETAIL_URL)
    use_model(monkeypatch, [CHAIN])
    body = send(chat, open_chat(chat), "我最近一笔报销的详情").json()
    assert body["run_status"] == "succeeded" and not detail.called
    assert "已停止后续查询" in body["reply"]["content"]


def test_chain_refs_are_checked_against_whitelist():
    def spec(name, kind, fields):
        return SimpleNamespace(name=name, result_kind=kind, result_fields=fields, inject_identity_fields=(),
                               model_params={"id": {"type": "integer", "required": True}})
    tools = {"a": (spec("a", "list", ("id",)), None), "b": (spec("b", "object", ("id",)), None)}

    def plan(ref):
        return {"steps": [{"tool": "a", "args": {"id": 1}}, {"tool": "b", "args": {"id": {"$ref": ref}}}]}
    assert tq._normalize_llm(plan("step1.list[0].id"), tools, max_steps=3)["steps"][1]["args"] == {
        "id": {"$ref": "step1.list[0].id"}}
    for bad in ("step1.list[0].secret", "step2.id", "step1.id", "step0.list[0].id", "step1.list[0].id;x"):
        assert tq._normalize_llm(plan(bad), tools, max_steps=3) is None, bad
    assert len(tq._normalize_llm(plan("step1.list[0].id"), tools, max_steps=1).get("steps") or [1]) == 1, \
        "超过最大步数的步骤被截掉"


# ---------------- 会话压缩 ----------------

def chat_turns(chat, model_outputs, monkeypatch, messages, overrides, admin):
    publish_config(admin, overrides)
    model = use_model(monkeypatch, model_outputs)
    h = open_chat(chat)
    bodies = [send(chat, h, m).json() for m in messages]
    return model, bodies


def remember_output(chat, run_id) -> dict:
    _, events = run_and_events(chat, run_id)
    return next(json.loads(e.output_summary) for e in events
                if e.event_type == "node_end" and e.node_name == "remember")


def test_summary_compression(chat, office, admin, monkeypatch):
    model, bodies = chat_turns(chat, [
        {"action": "chat", "reply": "你好小王"},
        {"action": "chat", "reply": "记住了"},
        "员工自称小王，偏好看九月的数据。",
        {"action": "chat", "reply": "好"},
    ], monkeypatch, ["我是小王", "我只关心九月", "嗯"],
        {"history_turns": 1, "history_compress_mode": "summary"}, admin)
    assert "【新移出的对话】" in model.calls[2][1][1] and "员工：我是小王" in model.calls[2][1][1]
    system = model.calls[3][0][1]
    assert "## 更早对话的记忆" in system and "员工自称小王，偏好看九月的数据。" in system
    assert len(model.calls[3]) == 1 + 2 + 1
    out = remember_output(chat, bodies[1]["run_id"])
    assert out["mode"] == "summary" and out["compressed_turns"] == 1 and "fallback_from" not in out


def test_facts_compression(chat, office, admin, monkeypatch):
    model, _ = chat_turns(chat, [
        {"action": "chat", "reply": "好"},
        {"action": "chat", "reply": "好"},
        {"facts": ["员工叫小王", "员工只关心九月的报销"]},
        {"action": "chat", "reply": "好"},
    ], monkeypatch, ["我是小王，只看九月", "知道了吗", "嗯"],
        {"history_turns": 1, "history_compress_mode": "facts"}, admin)
    assert "- 员工叫小王\n- 员工只关心九月的报销" in model.calls[3][0][1]


def test_model_compression_falls_back_to_truncate(chat, office, admin, monkeypatch):
    model, bodies = chat_turns(chat, [
        {"action": "chat", "reply": "好"},
        {"action": "chat", "reply": "好"},
        "",
    ], monkeypatch, ["第一句话", "第二句话"], {"history_turns": 1, "history_compress_mode": "summary"}, admin)
    out = remember_output(chat, bodies[1]["run_id"])
    assert out["mode"] == "truncate" and out["fallback_from"] == "summary"
    assert bodies[1]["run_status"] == "succeeded"


def test_compression_off_drops_old_turns(chat, office, admin, monkeypatch):
    model, _ = chat_turns(chat, [{"action": "chat", "reply": "好"}] * 3, monkeypatch, ["一", "二", "三"],
                          {"history_turns": 1, "history_compress": False}, admin)
    system = model.calls[2][0][1]
    assert "更早对话的记忆" not in system
    msgs = [m for _, m in model.calls[2][1:]]
    assert msgs[:2] == ["二", "好"] and len(msgs) == 3 and "三" in msgs[2]
    assert msgs[2].startswith("<<<UNTRUSTED_DATA source=user")


def test_truncate_compression_cuts_each_line(chat, office, admin, monkeypatch):
    model, _ = chat_turns(chat, [{"action": "chat", "reply": "好"}] * 3, monkeypatch, ["很" * 50, "二", "三"],
                          {"history_turns": 1, "compress_truncate_chars": 20}, admin)
    assert "员工：" + "很" * 20 + "…" in model.calls[2][0][1]


# ---------------- 角色设定与配置校验 ----------------

def test_persona_is_used_and_blank_restores_default(chat, office, admin, monkeypatch):
    publish_config(admin, {"assistant_persona": "你是行政小助手「小 O」。"})
    model = use_model(monkeypatch, [{"action": "chat", "reply": "好"}, {"action": "chat", "reply": "好"}])
    send(chat, open_chat(chat), "你是谁")
    assert model.calls[0][0][1].startswith("你是行政小助手「小 O」。")
    publish_config(admin, {"assistant_persona": ""})
    send(chat, open_chat(chat), "你是谁")
    assert model.calls[1][0][1].startswith(tq.DEFAULT_PERSONA)
    assert "不要编造" in model.calls[1][0][1], "安全规则固定在代码中"


def test_new_release_fields_are_validated(admin):
    current = admin.get(WF).json()["current_version"]["content"]
    for bad, word in (({"history_turns": 31}, "对话轮数"), ({"history_compress_mode": "zip"}, "压缩方式"),
                      ({"history_compress": "yes"}, "压缩会话"), ({"max_tool_steps": 0}, "串联"),
                      ({"assistant_persona": "长" * 501}, "角色设定")):
        admin.put(f"{WF}/draft", json={"content": {**current, **bad}})
        r = admin.post(f"{WF}/draft/validate").json()
        assert r["status"] == "draft" and any(word in e for e in r["validation"]["errors"]), bad
    schema = admin.get(f"{WF}/schema").json()
    assert schema["groups"] and all(f.get("group") in schema["groups"] for f in schema["fields"])
    assert all(f.get("help") for f in schema["fields"]), "每个配置项都有说明"
