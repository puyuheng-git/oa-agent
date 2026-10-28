"""M1：ChatSession.principal_id 双写（默认等于 oa）。"""

from __future__ import annotations

from oa_agent.auth.chat_launch import ChatSession


def _session(**over):
    base = {
        "oa": "u1",
        "uid": 1,
        "display_name": "User",
        "thread_id": "thr_test",
        "office_token": "tok",
        "token_expires_at": 9_999_999_999,
        "created_at": 1000,
    }
    base.update(over)
    return ChatSession(**base)


def test_chat_session_principal_id_defaults_to_oa():
    session = _session()
    assert session.principal_id == "u1"
    assert session.oa == "u1"


def test_chat_session_explicit_principal_id():
    session = _session(principal_id="p1")
    assert session.principal_id == "p1"
    assert session.oa == "u1"
