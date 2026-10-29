"""ChatThread 领域服务（threads.py）。"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from oa_agent.chat import threads as th
from oa_agent.db.models import ChatThread, DEFAULT_TENANT
from oa_agent.errors import AppError
from oa_agent.ids import new_thread_id
from tests.test_chat import chat, make_assertion, office, runtime  # noqa: F401


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def test_create_and_list_owned_only(rt):
    with rt.session() as db, db.begin():
        t1 = th.create_thread(db, oa="alice", channel="web")
        th.create_thread(db, oa="bob", channel="web")
        th.create_thread(db, oa="alice", channel="wecom")

    with rt.session() as db:
        items, total = th.list_threads(
            db, oa="alice", status=th.STATUS_ACTIVE, tenant_id=DEFAULT_TENANT, limit=50, offset=0
        )
    assert total == 2
    assert len(items) == 2
    assert all(t.oa == "alice" for t in items)
    assert t1.thread_id in {t.thread_id for t in items}


def test_list_threads_null_last_message_sorts_after_and_mysql_safe(rt):
    """无消息的会话排在后面；排序 SQL 不能含 MySQL 不支持的 NULLS LAST。"""
    from sqlalchemy.dialects import mysql

    with rt.session() as db, db.begin():
        empty = th.create_thread(db, oa="sort_oa", channel="web")
        recent = th.create_thread(db, oa="sort_oa", channel="web")
        th.touch_on_user_message(
            db, thread_id=recent.thread_id, oa="sort_oa", channel="web", user_text="有消息"
        )
        empty_id, recent_id = empty.thread_id, recent.thread_id

    with rt.session() as db:
        items, _ = th.list_threads(
            db, oa="sort_oa", status=th.STATUS_ACTIVE, tenant_id=DEFAULT_TENANT, limit=50, offset=0
        )
    assert [t.thread_id for t in items] == [recent_id, empty_id]

    stmt = sa.select(ChatThread).order_by(*th._list_order())
    sql = str(stmt.compile(dialect=mysql.dialect()))
    assert "NULLS LAST" not in sql.upper()


def test_soft_delete_hides_from_get(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        tid = t.thread_id

    with rt.session() as db, db.begin():
        row = th.get_owned(db, thread_id=tid, oa="alice")
        assert row is not None
        th.soft_delete(db, row)

    with rt.session() as db:
        assert th.get_owned(db, thread_id=tid, oa="alice") is None
        found = th.get_owned(
            db, thread_id=tid, oa="alice", allow_statuses={th.STATUS_DELETED}
        )
        assert found is not None
        assert found.status == th.STATUS_DELETED


def test_touch_truncates_title(rt):
    tid = new_thread_id()
    long_text = "甲" * 50
    with rt.session() as db, db.begin():
        th.ensure_thread(db, thread_id=tid, oa="alice", channel="web")
        th.touch_on_user_message(db, thread_id=tid, oa="alice", channel="web", user_text=long_text)

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.title == "甲" * th.TITLE_MAX


def test_touch_fills_title_once(rt):
    tid = new_thread_id()
    with rt.session() as db, db.begin():
        th.ensure_thread(db, thread_id=tid, oa="alice", channel="web")
        th.touch_on_user_message(db, thread_id=tid, oa="alice", channel="web", user_text="你好\n世界")

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.title == "你好 世界"

    with rt.session() as db, db.begin():
        th.touch_on_user_message(db, thread_id=tid, oa="alice", channel="wecom", user_text="不应覆盖")

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.title == "你好 世界"
        assert row.last_channel == "wecom"


def test_patch_archived_active_roundtrip(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        th.patch_thread(db, t, status=th.STATUS_ARCHIVED)
        assert t.status == th.STATUS_ARCHIVED
        th.patch_thread(db, t, status=th.STATUS_ACTIVE)
        assert t.status == th.STATUS_ACTIVE


def test_patch_invalid_status_raises(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        with pytest.raises(AppError) as exc:
            th.patch_thread(db, t, status=th.STATUS_DELETED)
        assert exc.value.status == 422
        assert exc.value.code == "VALIDATION_ERROR"


def test_ensure_thread_wrong_oa_raises(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        tid = t.thread_id

    with rt.session() as db, db.begin():
        with pytest.raises(AppError) as exc:
            th.ensure_thread(db, thread_id=tid, oa="bob", channel="web")
        assert exc.value.status == 404
        assert exc.value.code == "THREAD_NOT_FOUND"


def test_ensure_thread_deleted_raises(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        tid = t.thread_id
        th.soft_delete(db, t)

    with rt.session() as db, db.begin():
        with pytest.raises(AppError) as exc:
            th.ensure_thread(db, thread_id=tid, oa="alice", channel="web")
        assert exc.value.status == 404
        assert exc.value.code == "THREAD_NOT_FOUND"

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.status == th.STATUS_DELETED


def test_touch_wrong_oa_raises(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        tid = t.thread_id

    with rt.session() as db, db.begin():
        with pytest.raises(AppError) as exc:
            th.touch_on_user_message(
                db, thread_id=tid, oa="bob", channel="web", user_text="hi"
            )
        assert exc.value.status == 404
        assert exc.value.code == "THREAD_NOT_FOUND"

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.oa == "alice"
        assert row.last_message_at is None


def test_touch_on_soft_deleted_raises_and_does_not_revive(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        tid = t.thread_id
        th.soft_delete(db, t)

    with rt.session() as db, db.begin():
        with pytest.raises(AppError) as exc:
            th.touch_on_user_message(
                db, thread_id=tid, oa="alice", channel="web", user_text="再来一条"
            )
        assert exc.value.status == 404
        assert exc.value.code == "THREAD_NOT_FOUND"

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.status == th.STATUS_DELETED
        assert row.last_message_at is None
        assert (row.title or "").strip() == ""


def test_thread_view_iso_fields(rt):
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="alice", channel="web")
        t.title = "标题"
        view = th.thread_view(t)
    assert view["thread_id"] == t.thread_id
    assert view["title"] == "标题"
    assert view["status"] == th.STATUS_ACTIVE
    assert view["created_channel"] == "web"
    assert view["last_channel"] == "web"
    assert view["pinned"] is False
    for key in ("created_at", "updated_at", "last_message_at"):
        assert key in view
    assert view["last_message_at"] is None
    assert view["created_at"].endswith("Z") or "+" in view["created_at"]


def test_session_defaults_to_new_thread_row(chat, office):
    r = chat.post("/v1/chat/launch", json={"assertion": make_assertion()})
    assert r.status_code == 200, r.text
    r = chat.post("/v1/chat/session", json={"launch_code": r.json()["launch_code"]})
    assert r.status_code == 200, r.text
    tid = r.json()["thread_id"]
    assert tid.startswith("thr_")
    rt = runtime(chat)
    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
    assert row is not None
    assert row.oa == "zhangsan"
    assert row.created_channel == "oa_web"
    assert row.status == th.STATUS_ACTIVE


def test_session_with_foreign_thread_404(chat, office, rt):
    with rt.session() as db, db.begin():
        foreign = th.create_thread(db, oa="lisi", channel="web")
        foreign_tid = foreign.thread_id

    r = chat.post("/v1/chat/launch", json={"assertion": make_assertion("zhangsan")})
    assert r.status_code == 200, r.text
    r = chat.post(
        "/v1/chat/session",
        json={"launch_code": r.json()["launch_code"], "thread_id": foreign_tid},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "THREAD_NOT_FOUND"


def test_session_resumes_owned_thread(chat, office, rt):
    with rt.session() as db, db.begin():
        owned = th.create_thread(db, oa="zhangsan", channel="oa_web")
        owned_tid = owned.thread_id

    r = chat.post("/v1/chat/launch", json={"assertion": make_assertion()})
    r = chat.post(
        "/v1/chat/session",
        json={"launch_code": r.json()["launch_code"], "thread_id": owned_tid},
    )
    assert r.status_code == 200, r.text
    assert r.json()["thread_id"] == owned_tid


def _open_chat_on_thread(client, thread_id: str, oa: str = "zhangsan") -> dict:
    r = client.post("/v1/chat/launch", json={"assertion": make_assertion(oa)})
    assert r.status_code == 200, r.text
    r = client.post(
        "/v1/chat/session",
        json={"launch_code": r.json()["launch_code"], "thread_id": thread_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["thread_id"] == thread_id
    return {"Authorization": f"Bearer {r.json()['ticket']}"}


def test_reopen_thread_keeps_checkpoint_history(chat, office, monkeypatch):
    from tests.test_agent_chat import use_model
    from tests.test_chat import open_chat, send

    model = use_model(
        monkeypatch,
        [
            {"action": "chat", "reply": "第一轮回复"},
            {"action": "chat", "reply": "第二轮回复"},
            {"action": "chat", "reply": "第三轮回复"},
        ],
    )
    h = open_chat(chat)
    tid = chat.get("/v1/chat/session", headers=h).json()["thread_id"]
    assert send(chat, h, "第一条消息").json()["run_status"] == "succeeded"
    assert send(chat, h, "第二条消息").json()["run_status"] == "succeeded"

    h2 = _open_chat_on_thread(chat, tid)
    body = send(chat, h2, "第三条消息").json()
    assert body["run_status"] == "succeeded"
    assert body["reply"]["content"] == "第三轮回复"

    third = model.calls[2]
    history = third[1:-1]
    assert [role for role, _ in history] == ["human", "ai", "human", "ai"]
    assert history[0][1] == "第一条消息"
    assert "第一轮回复" in history[1][1]
    assert history[2][1] == "第二条消息"
    assert "第二轮回复" in history[3][1]
    assert third[-1][0] == "human" and third[-1][1].startswith("<<<UNTRUSTED_DATA source=user")
    assert "第三条消息" in third[-1][1]


def test_list_create_switch_messages_delete(chat, office):
    import httpx

    from tests.test_chat import LIST_URL, ROW, open_chat, send

    office.get(LIST_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}})
    )
    h = open_chat(chat)
    original_tid = chat.get("/v1/chat/session", headers=h).json()["thread_id"]

    r = chat.post("/v1/chat/threads", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    new_tid = body["thread_id"]
    assert new_tid.startswith("thr_") and new_tid != original_tid
    assert body["status"] == th.STATUS_ACTIVE
    assert chat.get("/v1/chat/session", headers=h).json()["thread_id"] == new_tid

    assert send(chat, h, "查上周行程报销").status_code == 200

    rt = runtime(chat)
    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == new_tid))
    assert row is not None
    assert row.title == "查上周行程报销"
    assert row.last_message_at is not None

    listed = chat.get("/v1/chat/threads", headers=h).json()
    assert listed["page"] == 1 and listed["page_size"] == 20
    ids = {t["thread_id"] for t in listed["items"]}
    assert new_tid in ids and original_tid in ids

    msgs = chat.get(f"/v1/chat/threads/{new_tid}/messages", headers=h).json()
    assert msgs["total"] >= 2
    roles = [m["role"] for m in msgs["items"]]
    assert roles[0] == "user" and "assistant" in roles
    assert all("data" in m and "message_id" in m for m in msgs["items"])

    sw = chat.post("/v1/chat/session/switch", headers=h, json={"thread_id": original_tid})
    assert sw.status_code == 200, sw.text
    assert sw.json()["thread_id"] == original_tid
    assert chat.get("/v1/chat/session", headers=h).json()["thread_id"] == original_tid

    deleted = chat.delete(f"/v1/chat/threads/{new_tid}", headers=h)
    assert deleted.status_code == 200 and deleted.json() == {"ok": True}
    active_ids = {t["thread_id"] for t in chat.get("/v1/chat/threads", headers=h).json()["items"]}
    assert new_tid not in active_ids

    missing = chat.post("/v1/chat/session/switch", headers=h, json={"thread_id": new_tid})
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "THREAD_NOT_FOUND"


def test_send_after_soft_delete_returns_404(chat, office, rt):
    """session 仍指向已删 thread 时，发消息须 opaque 404（含跨渠道续聊场景）。"""
    import httpx

    from tests.test_chat import LIST_URL, ROW, open_chat, send

    office.get(LIST_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}})
    )
    h = open_chat(chat)
    tid = chat.get("/v1/chat/session", headers=h).json()["thread_id"]

    with rt.session() as db, db.begin():
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row is not None
        th.soft_delete(db, row)

    r = send(chat, h, "软删后不应再发")
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "THREAD_NOT_FOUND"

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.status == th.STATUS_DELETED
        assert row.last_message_at is None


def test_send_preserves_thread_title(chat, office, rt):
    import httpx

    from tests.test_chat import LIST_URL, ROW, open_chat, send

    office.get(LIST_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}})
    )
    h = open_chat(chat)
    new_tid = chat.post("/v1/chat/threads", headers=h).json()["thread_id"]
    with rt.session() as db, db.begin():
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == new_tid))
        row.title = "固定标题"

    assert send(chat, h, "不应覆盖标题").status_code == 200

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == new_tid))
    assert row.title == "固定标题"
    assert row.last_message_at is not None


def test_send_truncates_empty_title_from_long_message(chat, office):
    import httpx

    from tests.test_chat import LIST_URL, ROW, open_chat, send

    office.get(LIST_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}})
    )
    h = open_chat(chat)
    new_tid = chat.post("/v1/chat/threads", headers=h).json()["thread_id"]
    long_msg = "长" * 50
    assert send(chat, h, long_msg).status_code == 200

    rt = runtime(chat)
    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == new_tid))
    assert row.title == "长" * th.TITLE_MAX
    assert row.last_message_at is not None
