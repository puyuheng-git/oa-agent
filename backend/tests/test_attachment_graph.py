"""已发送上传进入对话图：先看文件，再回答或交给办公工具。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import sqlalchemy as sa

from oa_agent.db.models import ExportFile
from oa_agent.runtime.llm import ModelConfig
from tests.test_chat import (  # noqa: F401
    INVOKE_URL,
    ROW,
    chat,
    office,
    open_chat,
    run_and_events,
    send,
)

CSV = "金额,1\n".encode()
TOOL = "query_my_travel_expense_list"
CORRUPT = "附件已损坏或无法读取，请重新上传"
ANSWER = json.dumps({"action": "answer", "answer": "合计是 1"}, ensure_ascii=False)
TOOL_ACTION = json.dumps(
    {"action": "tool", "steps": [{"tool": TOOL, "args": {}}]},
    ensure_ascii=False,
)
UNREAD = json.dumps({"action": "chat", "reply": "未读到文件"}, ensure_ascii=False)


def _upload_csv(chat, headers) -> str:
    uploaded = chat.post(
        "/v1/chat/attachments",
        headers=headers,
        files=[("files", ("note.csv", CSV, "text/csv"))],
    )
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()["files"][0]["file_id"]


def _bind(chat, headers, file_id: str) -> None:
    from oa_agent.chat.attachment_files import bind_uploads

    rt = chat.app.state.runtime
    thread_id = chat.get("/v1/chat/session", headers=headers).json()["thread_id"]
    with rt.session() as db:
        bind_uploads(
            db,
            tenant_id=rt.tenant_id,
            oa="zhangsan",
            thread_id=thread_id,
            file_ids=[file_id],
        )


def _corrupt_object(chat, file_id: str) -> None:
    rt = chat.app.state.runtime
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.file_id == file_id))
        assert row is not None
        key = row.object_key
    path = rt.settings.data_dir / "exports" / key
    assert path.is_file(), path
    path.write_bytes(b"not-the-csv")


def _text_of(messages) -> str:
    return json.dumps(messages, ensure_ascii=False, default=str)


def _human_texts(messages) -> list[str]:
    texts: list[str] = []
    for item in messages:
        role = item[0] if isinstance(item, (list, tuple)) else item.get("role")
        content = item[1] if isinstance(item, (list, tuple)) else item.get("content")
        if role not in ("human", "user"):
            continue
        texts.append(content if isinstance(content, str) else _text_of(content))
    return texts


def _install_model(monkeypatch) -> list:
    calls: list = []

    def invoke(messages):
        calls.append(messages)
        text = _text_of(messages)
        if "查报销" in text and "金额,1" in text:
            content = TOOL_ACTION
        elif "金额,1" in text:
            content = ANSWER
        else:
            content = UNREAD
        return SimpleNamespace(
            content=content,
            response_metadata={"token_usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        )

    cfg = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (SimpleNamespace(invoke=invoke), cfg))
    return calls


def test_bound_csv_answer_includes_amount_and_read_range(chat, monkeypatch):
    calls = _install_model(monkeypatch)
    headers = open_chat(chat)
    file_id = _upload_csv(chat, headers)
    _bind(chat, headers, file_id)

    resp = send(chat, headers, "合计多少")
    assert resp.status_code == 200, resp.text
    assert calls, "模型没有被调用"
    humans = _human_texts(calls[0])
    assert humans, calls[0]
    assert "金额" in humans[0]
    assert "object_key" not in _text_of(calls[0])
    content = resp.json()["reply"]["content"]
    assert "合计是 1" in content
    assert "已阅读全文" in content or "已读过" in content


def test_next_turn_tool_action_reaches_call_tool(chat, office, monkeypatch):
    route = office.post(INVOKE_URL).mock(return_value=httpx.Response(
        200, json={"code": 0, "data": {"list": [ROW], "total": 1}},
    ))
    calls = _install_model(monkeypatch)
    headers = open_chat(chat)
    file_id = _upload_csv(chat, headers)
    _bind(chat, headers, file_id)

    first = send(chat, headers, "合计多少")
    assert first.status_code == 200, first.text
    before = len(calls)

    second = send(chat, headers, "查报销")
    assert second.status_code == 200, second.text
    body = second.json()
    data = body["reply"].get("data") or {}
    assert data.get("tool") == TOOL
    assert data.get("kind") == "table"
    assert "已阅读全文" not in (body["reply"].get("content") or "")
    assert route.called
    assert len(calls) > before
    seen = _text_of(calls[before])
    assert "金额,1" in seen and "查报销" in seen
    _, events = run_and_events(chat, body["run_id"])
    assert any(event.node_name == "call_tool" and event.event_type == "node_start" for event in events)


def test_replaced_bytes_fail_without_calling_model(chat, monkeypatch):
    calls = _install_model(monkeypatch)
    headers = open_chat(chat)
    file_id = _upload_csv(chat, headers)
    _bind(chat, headers, file_id)
    _corrupt_object(chat, file_id)

    resp = send(chat, headers, "再看一眼")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_status"] == "failed"
    assert (body.get("reply") or {}).get("content") == CORRUPT
    assert calls == []


def test_csv_longer_than_8000_reaches_model(chat, monkeypatch):
    marker = "ENDMARK9000"
    body = "金额,1\n" + ("x" * 8500) + marker + "\n"
    assert 8000 < len(body) < 30000
    calls = _install_model(monkeypatch)
    headers = open_chat(chat)
    uploaded = chat.post(
        "/v1/chat/attachments",
        headers=headers,
        files=[("files", ("long.csv", body.encode(), "text/csv"))],
    )
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["files"][0]["file_id"]
    _bind(chat, headers, file_id)

    resp = send(chat, headers, "合计多少")
    assert resp.status_code == 200, resp.text
    assert calls, "model was not called"
    seen = _text_of(calls[0])
    assert "<<<UNTRUSTED_DATA" in seen
    assert marker in seen
