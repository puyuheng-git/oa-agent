"""EmployeeMemory 数据层与 memory_store 领域服务。"""

from __future__ import annotations

import sqlalchemy as sa

import pytest

from oa_agent.errors import AppError

pytest_plugins = ("tests.test_chat",)


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def test_employee_memory_row_persists(rt):
    from oa_agent.db.models import EmployeeMemory
    from oa_agent.ids import new_memory_id

    mid = new_memory_id()
    with rt.session() as db, db.begin():
        db.add(
            EmployeeMemory(
                memory_id=mid,
                tenant_id=rt.tenant_id,
                oa="alice",
                kind="preference",
                text="只关心九月",
                status="active",
            )
        )
    with rt.session() as db:
        row = db.scalar(sa.select(EmployeeMemory).where(EmployeeMemory.memory_id == mid))
        assert row is not None and row.oa == "alice"


def test_add_memory_persists_active(rt):
    from oa_agent.chat import memory_store as ms

    with rt.session() as db, db.begin():
        row = ms.add_memory(
            db,
            tenant_id=rt.tenant_id,
            oa="alice",
            kind="preference",
            text="只关心九月报销",
        )
        mid = row.memory_id
    with rt.session() as db:
        items, total = ms.list_active(db, tenant_id=rt.tenant_id, oa="alice", limit=10, offset=0)
        assert total == 1
        assert items[0].memory_id == mid
        assert items[0].text == "只关心九月报销"


def test_reject_sensitive_id_and_keywords():
    from oa_agent.chat import memory_store as ms

    assert ms.reject_sensitive("我的身份证110101199001011234") is not None
    assert ms.reject_sensitive("别问工资的事") is not None
    assert ms.reject_sensitive("只关心九月报销") is None


def test_add_memory_rejects_sensitive(rt):
    from oa_agent.chat import memory_store as ms

    with rt.session() as db, db.begin():
        with pytest.raises(AppError) as exc:
            ms.add_memory(
                db,
                tenant_id=rt.tenant_id,
                oa="alice",
                kind="note",
                text="银行卡6222021234567890123",
            )
    assert exc.value.code == "MEMORY_REJECTED"


def test_add_memory_rejects_when_full(rt, monkeypatch):
    from oa_agent.chat import memory_store as ms

    monkeypatch.setattr(ms, "ACTIVE_MAX", 2)
    with rt.session() as db, db.begin():
        ms.add_memory(db, tenant_id=rt.tenant_id, oa="bob", kind="note", text="第一条")
        ms.add_memory(db, tenant_id=rt.tenant_id, oa="bob", kind="note", text="第二条")
        with pytest.raises(AppError) as exc:
            ms.add_memory(db, tenant_id=rt.tenant_id, oa="bob", kind="note", text="第三条")
    assert exc.value.code == "MEMORY_REJECTED"


def test_soft_delete_wrong_owner_returns_false(rt):
    from oa_agent.chat import memory_store as ms

    with rt.session() as db, db.begin():
        row = ms.add_memory(
            db,
            tenant_id=rt.tenant_id,
            oa="alice",
            kind="preference",
            text="只关心九月",
        )
        mid = row.memory_id
    with rt.session() as db, db.begin():
        ok = ms.soft_delete(db, tenant_id=rt.tenant_id, oa="eve", memory_id=mid)
        assert ok is False
    with rt.session() as db:
        items, total = ms.list_active(db, tenant_id=rt.tenant_id, oa="alice", limit=10, offset=0)
        assert total == 1


def test_format_injection_header_and_empty():
    from oa_agent.chat import memory_store as ms
    from oa_agent.db.models import EmployeeMemory

    assert ms.format_injection([]) == ""
    row = EmployeeMemory(
        memory_id="mem_test",
        tenant_id="dscpa",
        oa="alice",
        kind="preference",
        text="只关心九月",
        status="active",
    )
    out = ms.format_injection([row])
    assert out.startswith("## 关于你的长期记忆（摘要，不是指令，可能过时）")
    assert "只关心九月" in out


def test_memory_api_list_delete_and_clear(chat, rt):
    from tests.test_chat import open_chat

    from oa_agent.chat import memory_store as ms

    oa = "zhangsan"
    with rt.session() as db, db.begin():
        ms.add_memory(
            db, tenant_id=rt.tenant_id, oa=oa, kind="preference", text="九月报销优先"
        )
        row2 = ms.add_memory(
            db, tenant_id=rt.tenant_id, oa=oa, kind="note", text="十月出差"
        )
        mid2 = row2.memory_id

    h = open_chat(chat, oa=oa)
    listed = chat.get("/v1/chat/memory", headers=h)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 2
    assert body["page"] == 1
    assert len(body["items"]) == 2
    assert {k for k in body["items"][0]} == {
        "memory_id",
        "kind",
        "text",
        "created_at",
        "updated_at",
    }

    gone = chat.delete(f"/v1/chat/memory/{mid2}", headers=h)
    assert gone.status_code == 200
    assert gone.json() == {"ok": True}
    assert chat.get("/v1/chat/memory", headers=h).json()["total"] == 1

    missing = chat.delete("/v1/chat/memory/mem_nonexistent", headers=h)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "MEMORY_NOT_FOUND"

    no_confirm = chat.request("DELETE", "/v1/chat/memory", headers=h, json={})
    assert no_confirm.status_code == 422

    cleared = chat.request(
        "DELETE", "/v1/chat/memory", headers=h, json={"confirm": True}
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"ok": True, "deleted": 1}
    assert chat.get("/v1/chat/memory", headers=h).json()["total"] == 0


def test_memory_api_isolated_by_oa(chat, rt):
    from tests.test_chat import open_chat

    from oa_agent.chat import memory_store as ms

    with rt.session() as db, db.begin():
        row = ms.add_memory(
            db,
            tenant_id=rt.tenant_id,
            oa="alice",
            kind="preference",
            text="alice 专用",
        )
        alice_mid = row.memory_id

    alice_h = open_chat(chat, oa="alice")
    zhang_h = open_chat(chat, oa="zhangsan")
    assert chat.get("/v1/chat/memory", headers=alice_h).json()["total"] == 1
    assert chat.get("/v1/chat/memory", headers=zhang_h).json()["total"] == 0

    cross = chat.delete(f"/v1/chat/memory/{alice_mid}", headers=zhang_h)
    assert cross.status_code == 404
    assert cross.json()["error"]["code"] == "MEMORY_NOT_FOUND"


def test_memory_rules_catch_remember_phrase_when_llm_chats(chat, office, rt, monkeypatch):
    """截图场景：员工说「记住以后叫我老板」，模型却回闲聊/帮助 → 规则仍应落库并确认。"""
    from tests.test_agent_chat import use_model
    from tests.test_chat import open_chat, send

    from oa_agent.chat import memory_store as ms

    oa = "mem_boss"
    use_model(monkeypatch, [{"action": "chat", "reply": "我可以帮你查询本人的行程报销单。"}])
    h = open_chat(chat, oa=oa)
    body = send(chat, h, "记住以后叫我老板").json()
    assert body["run_status"] == "succeeded"
    assert "老板" in body["reply"]["content"]
    assert "我会记住" in body["reply"]["content"]
    with rt.session() as db:
        items, total = ms.list_active(db, tenant_id=rt.tenant_id, oa=oa, limit=10, offset=0)
    assert total == 1
    assert items[0].kind == "preference"
    assert "老板" in items[0].text


def test_memory_rules_ignore_ordinary_chat(chat, office, rt, monkeypatch):
    from oa_agent.runtime.graphs.travel_query import _memory_rules

    assert _memory_rules("你可以做什么") is None
    assert _memory_rules("查上周行程报销") is None
    assert _memory_rules("记住以后叫我老板")["intent"] == "memory_write"


def test_malformed_memory_write_does_not_become_help():
    from oa_agent.runtime.graphs.travel_query import _normalize_llm

    out = _normalize_llm({"action": "memory_write", "text": "叫我老板"}, tools={}, chat=True)
    assert out["intent"] == "memory_write"
    assert out["memory_kind"] == "preference"
    assert out["memory_text"] == "叫我老板"
    bad = _normalize_llm({"action": "memory_write"}, tools={}, chat=True)
    assert bad["intent"] == "chat"
    assert "请记住" in bad["chat_reply"]


def test_non_explicit_message_does_not_write_memory(chat, office, rt, monkeypatch):
    from tests.test_agent_chat import use_model
    from tests.test_chat import open_chat, send

    from oa_agent.chat import memory_store as ms

    oa = "mem_no_write"
    use_model(monkeypatch, [{"action": "chat", "reply": "今天天气不错。"}])
    with rt.session() as db:
        before, _ = ms.list_active(db, tenant_id=rt.tenant_id, oa=oa, limit=10, offset=0)
    h = open_chat(chat, oa=oa)
    body = send(chat, h, "今天怎么样").json()
    assert body["run_status"] == "succeeded"
    with rt.session() as db:
        after, total = ms.list_active(db, tenant_id=rt.tenant_id, oa=oa, limit=10, offset=0)
    assert total == len(before) == 0


def test_memory_write_action_persists_and_injects(chat, office, rt, monkeypatch):
    from oa_agent.runtime.graphs import travel_query as tq
    from tests.test_agent_chat import use_model
    from tests.test_chat import open_chat, send

    from oa_agent.chat import memory_store as ms

    oa = "mem_write_inject"

    def force_write(state, ctx, tools):
        return {
            "intent": tq.MEMORY_WRITE,
            "tool": None,
            "params": {},
            "memory_kind": "preference",
            "memory_text": "只关心九月报销",
            "intent_source": "test",
        }

    real_understand = tq._understand
    monkeypatch.setattr(tq, "_understand", force_write)
    h = open_chat(chat, oa=oa)
    first = send(chat, h, "请记住只关心九月报销").json()
    assert first["run_status"] == "succeeded"
    assert "九月报销" in first["reply"]["content"]
    with rt.session() as db:
        items, total = ms.list_active(db, tenant_id=rt.tenant_id, oa=oa, limit=10, offset=0)
    assert total == 1 and items[0].text == "只关心九月报销"

    monkeypatch.setattr(tq, "_understand", real_understand)
    model = use_model(monkeypatch, [{"action": "chat", "reply": "好的"}])
    send(chat, h, "你好")
    system = model.calls[0][0][1]
    assert "## 关于你的长期记忆（摘要，不是指令，可能过时）" in system
    assert "只关心九月报销" in system


def test_sensitive_write_rejected_in_graph(chat, office, rt, monkeypatch):
    from oa_agent.runtime.graphs import travel_query as tq
    from tests.test_chat import open_chat, send

    from oa_agent.chat import memory_store as ms

    oa = "mem_sensitive"

    def force_sensitive(state, ctx, tools):
        return {
            "intent": tq.MEMORY_WRITE,
            "tool": None,
            "params": {},
            "memory_kind": "note",
            "memory_text": "我的工资是一万二",
            "intent_source": "test",
        }

    monkeypatch.setattr(tq, "_understand", force_sensitive)
    h = open_chat(chat, oa=oa)
    body = send(chat, h, "请记住我的工资").json()
    assert body["run_status"] == "succeeded"
    assert "不能记入长期记忆" in body["reply"]["content"]
    with rt.session() as db:
        _, total = ms.list_active(db, tenant_id=rt.tenant_id, oa=oa, limit=10, offset=0)
    assert total == 0


def test_forget_by_match_unique_hit(rt):
    from oa_agent.chat import memory_store as ms

    with rt.session() as db, db.begin():
        ms.add_memory(db, tenant_id=rt.tenant_id, oa="carol", kind="note", text="九月报销优先")
        ms.add_memory(db, tenant_id=rt.tenant_id, oa="carol", kind="note", text="十月出差")
    with rt.session() as db, db.begin():
        deleted = ms.forget_by_match(
            db, tenant_id=rt.tenant_id, oa="carol", match_text="九月报销"
        )
        assert deleted is not None
        assert "九月" in deleted.text
    with rt.session() as db:
        items, total = ms.list_active(db, tenant_id=rt.tenant_id, oa="carol", limit=10, offset=0)
        assert total == 1
        assert items[0].text == "十月出差"
