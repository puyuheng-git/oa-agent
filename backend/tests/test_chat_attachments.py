"""Employee upload registration and download."""

from __future__ import annotations

import json
from types import SimpleNamespace

import sqlalchemy as sa
import pytest

from oa_agent.chat.service import setting
from oa_agent.db.models import ExportFile
from oa_agent.errors import AppError
from oa_agent.runtime.llm import ModelConfig
from tests.test_chat import chat, office, open_chat, send  # noqa: F401

CSV = b"a,b\n1,2\n"
NOT_FOUND = "\u6587\u4ef6\u4e0d\u5b58\u5728"


def _upload(chat, headers, parts):
    return chat.post("/v1/chat/attachments", headers=headers, files=parts)


def _csv_part(name: str, data: bytes = CSV):
    return ("files", (name, data, "text/csv"))


def test_upload_hides_object_key_until_sent(chat):
    h = open_chat(chat)
    uploaded = _upload(chat, h, [_csv_part("note.csv")])
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert "object_key" not in uploaded.text
    item = body["files"][0]
    assert set(item) == {"file_id", "filename", "size_bytes", "media_kind"}
    assert item["filename"] == "note.csv"
    assert item["size_bytes"] == len(CSV)
    assert item["media_kind"] == "document"
    assert item["file_id"].startswith("upl_")
    file_id = item["file_id"]
    denied = chat.get(f"/v1/chat/files/{file_id}", headers=h)
    assert denied.status_code == 404
    assert denied.json()["error"]["message"] == NOT_FOUND

    rt = chat.app.state.runtime
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.file_id == file_id))
    assert row is not None
    assert row.origin == "upload"
    assert row.in_message is False
    assert row.oa == "zhangsan"
    assert row.thread_id == chat.get("/v1/chat/session", headers=h).json()["thread_id"]
    assert row.sha256
    assert "://" not in row.object_key


def test_long_filename_clipped_to_255(chat):
    h = open_chat(chat)
    name = ("n" * 300) + ".csv"
    uploaded = _upload(chat, h, [_csv_part(name, b"a\n")])
    assert uploaded.status_code == 200, uploaded.text
    item = uploaded.json()["files"][0]
    assert item["filename"] == name[:255]
    assert len(item["filename"]) == 255


def test_bad_file_rejects_whole_batch(chat):
    h = open_chat(chat)
    rt = chat.app.state.runtime
    root = rt.settings.data_dir / "exports"
    before_files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []
    with rt.session() as db:
        before = db.scalar(sa.select(sa.func.count()).select_from(ExportFile).where(ExportFile.origin == "upload"))
    resp = _upload(
        chat,
        h,
        [
            _csv_part("note.csv"),
            ("files", ("run.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert resp.status_code == 422
    with rt.session() as db:
        after = db.scalar(sa.select(sa.func.count()).select_from(ExportFile).where(ExportFile.origin == "upload"))
    assert after == before
    after_files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()) if root.exists() else []
    assert after_files == before_files


def test_bound_owner_downloads_bytes_other_oa_and_export_ticket_404(chat):
    from oa_agent.chat.attachment_files import bind_uploads

    h = open_chat(chat)
    uploaded = _upload(chat, h, [_csv_part("note.csv")])
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["files"][0]["file_id"]
    rt = chat.app.state.runtime
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.file_id == file_id))
        assert row is not None and row.in_message is False
        ticket, thread_id = row.ticket, row.thread_id

    with rt.session() as db:
        bind_uploads(
            db,
            tenant_id=rt.tenant_id,
            oa="zhangsan",
            thread_id=thread_id,
            file_ids=[file_id],
        )

    got = chat.get(f"/v1/chat/files/{file_id}", headers=h)
    assert got.status_code == 200
    assert got.content == CSV
    again = chat.get(f"/v1/chat/files/{file_id}", headers=h)
    assert again.status_code == 200 and again.content == CSV

    other = open_chat(chat, oa="lisi")
    denied = chat.get(f"/v1/chat/files/{file_id}", headers=other)
    assert denied.status_code == 404
    assert denied.json()["error"]["message"] == NOT_FOUND

    via_ticket = chat.get(f"/v1/chat/exports/{ticket}", headers=h)
    assert via_ticket.status_code == 404
    assert via_ticket.json()["error"]["message"] == NOT_FOUND


def test_bind_failure_does_not_mark_any_row(chat):
    from oa_agent.chat.attachment_files import bind_uploads

    h = open_chat(chat)
    uploaded = _upload(
        chat,
        h,
        [_csv_part("one.csv", b"a\n"), _csv_part("two.csv", b"b\n")],
    )
    assert uploaded.status_code == 200, uploaded.text
    file_ids = [item["file_id"] for item in uploaded.json()["files"]]
    rt = chat.app.state.runtime
    with rt.session() as db:
        thread_id = db.scalar(
            sa.select(ExportFile.thread_id).where(ExportFile.file_id == file_ids[0])
        )
    with pytest.raises(AppError) as exc:
        with rt.session() as db:
            bind_uploads(
                db,
                tenant_id=rt.tenant_id,
                oa="zhangsan",
                thread_id=thread_id,
                file_ids=[file_ids[0], "upl_missing"],
            )
    assert exc.value.status == 404
    assert exc.value.code == "NOT_FOUND"
    assert exc.value.message == NOT_FOUND
    with rt.session() as db:
        rows = db.scalars(sa.select(ExportFile).where(ExportFile.file_id.in_(file_ids))).all()
    assert len(rows) == 2
    assert all(row.in_message is False for row in rows)

    with pytest.raises(AppError) as wrong_oa:
        with rt.session() as db:
            bind_uploads(
                db,
                tenant_id=rt.tenant_id,
                oa="lisi",
                thread_id=thread_id,
                file_ids=file_ids,
            )
    assert wrong_oa.value.message == NOT_FOUND
    with rt.session() as db:
        rows = db.scalars(sa.select(ExportFile).where(ExportFile.file_id.in_(file_ids))).all()
    assert all(row.in_message is False for row in rows)


def test_upload_without_thread_creates_one(chat):
    from oa_agent.auth.chat_launch import load_session, store_session
    from oa_agent.chat.service import launch_policy
    from oa_agent.db.models import ChatThread

    h = open_chat(chat)
    rt = chat.app.state.runtime
    ticket = h["Authorization"].split(" ", 1)[1]
    session = load_session(rt.kv.current, ticket)
    assert session is not None and session.thread_id
    previous = session.thread_id
    session.thread_id = ""
    store_session(rt.kv.current, ticket, session, launch_policy(rt))

    uploaded = _upload(chat, h, [_csv_part("note.csv")])
    assert uploaded.status_code == 200, uploaded.text
    file_id = uploaded.json()["files"][0]["file_id"]
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.file_id == file_id))
        thread = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == row.thread_id))
    assert row is not None
    assert row.thread_id.startswith("thr_") and row.thread_id != previous
    assert thread is not None and thread.oa == "zhangsan"
    restored = load_session(rt.kv.current, ticket)
    assert restored is not None and restored.thread_id == row.thread_id


EMPTY = "消息不能为空"


def _fake_chat_model(monkeypatch) -> None:
    """Same stand-in as tests/test_chat.py so these cases never call a real LLM."""
    reply = json.dumps({"action": "chat", "reply": "已收到"}, ensure_ascii=False)
    fake = SimpleNamespace(invoke=lambda _: SimpleNamespace(
        content=reply,
        response_metadata={"token_usage": {"prompt_tokens": 50, "completion_tokens": 20}},
    ))
    cfg = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (fake, cfg))


def _upload_csv(chat, headers) -> str:
    uploaded = _upload(chat, headers, [_csv_part("note.csv")])
    assert uploaded.status_code == 200, uploaded.text
    return uploaded.json()["files"][0]["file_id"]


def _upload_row(chat, file_id: str) -> ExportFile:
    rt = chat.app.state.runtime
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.file_id == file_id))
    assert row is not None
    return row


def test_blank_message_allowed_with_attachment(chat, monkeypatch):
    _fake_chat_model(monkeypatch)
    h = open_chat(chat)
    file_id = _upload_csv(chat, h)
    resp = send(chat, h, "", attachment_ids=[file_id], client_msg_id="att-blank-0001")
    assert resp.status_code == 200
    assert _upload_row(chat, file_id).in_message is True


def test_empty_message_without_attachment_rejected(chat):
    h = open_chat(chat)
    resp = send(chat, h, "")
    assert resp.status_code == 422
    assert resp.json()["error"]["message"] == EMPTY


def test_body_over_max_chars_rejected_with_attachment(chat):
    h = open_chat(chat)
    file_id = _upload_csv(chat, h)
    rt = chat.app.state.runtime
    limit = int(setting(rt, "chat", "message_max_chars"))
    resp = send(
        chat, h, "字" * (limit + 1),
        attachment_ids=[file_id], client_msg_id="att-max-chars-01",
    )
    assert resp.status_code == 422
    assert _upload_row(chat, file_id).in_message is False


def test_blank_attachment_client_msg_id_dedupes(chat, monkeypatch):
    _fake_chat_model(monkeypatch)
    h = open_chat(chat)
    file_id = _upload_csv(chat, h)
    first = send(chat, h, "", attachment_ids=[file_id], client_msg_id="att-dedupe-0001")
    assert first.status_code == 200
    again = send(chat, h, "", attachment_ids=[file_id], client_msg_id="att-dedupe-0001")
    assert again.status_code == 409


def test_travel_state_accepts_attachment_ids():
    from langgraph.graph import END, START, StateGraph

    from oa_agent.runtime.graphs.oa_assistant import TravelState

    assert "attachment_ids" in TravelState.__annotations__

    def keep(state):
        return {}

    graph = StateGraph(TravelState)
    graph.add_node("keep", keep)
    graph.add_edge(START, "keep")
    graph.add_edge("keep", END)
    out = graph.compile().invoke({"message": "", "attachment_ids": ["upl_demo"]})
    assert out["attachment_ids"] == ["upl_demo"]


def test_user_message_persists_attachments_and_documents_list(chat, monkeypatch):
    _fake_chat_model(monkeypatch)
    h = open_chat(chat)
    file_id = _upload_csv(chat, h)
    assert send(chat, h, "请看附件", attachment_ids=[file_id], client_msg_id="att-hist-0001").status_code == 200
    tid = chat.get("/v1/chat/session", headers=h).json()["thread_id"]
    msgs = chat.get(f"/v1/chat/threads/{tid}/messages", headers=h).json()
    user = next(m for m in msgs["items"] if m["role"] == "user")
    assert user["attachments"]
    assert user["attachments"][0]["file_id"] == file_id
    assert user["attachments"][0]["filename"] == "note.csv"
    assert _upload_row(chat, file_id).run_id

    docs = chat.get("/v1/chat/documents", headers=h, params={"origin": "upload"}).json()
    assert docs["total"] >= 1
    assert any(i["file_id"] == file_id for i in docs["items"])
    dl = chat.get(f"/v1/chat/documents/{file_id}/download", headers=h)
    assert dl.status_code == 200
    assert dl.content == CSV
