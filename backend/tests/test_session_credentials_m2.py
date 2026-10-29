"""M2 Task 5：ChatSession.credentials 多 connector 凭证表 + office_token 兼容。"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from oa_agent.auth.chat_launch import ChatSession, _session_payload
from oa_agent.chat.service import _authorization_for_tool, _identity_from_session
from oa_agent.errors import AppError
from oa_agent.executor.executor import Identity, ToolError, authorization_for
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM


def _session(**over):
    base = {
        "oa": "u1",
        "uid": 1,
        "display_name": "User",
        "thread_id": "thr_test",
        "office_token": "tok-office",
        "token_expires_at": 9_999_999_999,
        "created_at": 1000,
    }
    base.update(over)
    return ChatSession(**base)


def test_credentials_filled_from_office_token():
    session = _session()
    assert session.credentials[DEFAULT_UPSTREAM]["authorization"] == "tok-office"
    assert session.credentials[DEFAULT_UPSTREAM]["expires_at"] == 9_999_999_999
    assert session.get_authorization("office") == "tok-office"
    assert session.get_authorization(DEFAULT_UPSTREAM) == "tok-office"


def test_office_token_synced_from_credentials():
    session = _session(
        office_token="",
        credentials={"office": {"authorization": "from-creds", "expires_at": 12345}},
    )
    assert session.office_token == "from-creds"
    assert session.token_expires_at == 12345


def test_get_authorization_no_office_fallback_for_other_connector():
    session = _session()
    assert session.get_authorization("demo") is None
    assert session.get_authorization("office") == "tok-office"


def test_asdict_json_roundtrip_restores_credentials():
    session = _session(credentials={
        "office": {"authorization": "tok-office", "expires_at": 9_999_999_999},
        "demo": {"authorization": "tok-demo", "expires_at": 111},
    })
    raw = _session_payload(session)
    restored = ChatSession(**json.loads(raw))
    assert restored.office_token == "tok-office"
    assert restored.get_authorization("demo") == "tok-demo"
    assert restored.credentials["demo"]["expires_at"] == 111


def test_legacy_ticket_without_credentials_reconstructs():
    legacy = {
        "oa": "u1",
        "uid": 1,
        "display_name": "User",
        "thread_id": "thr_x",
        "office_token": "legacy-tok",
        "token_expires_at": 222,
        "created_at": 1000,
        "channel": "oa_web",
        "principal_id": "u1",
    }
    session = ChatSession(**legacy)
    assert session.credentials["office"]["authorization"] == "legacy-tok"
    assert "credentials" in asdict(session)


def test_service_identity_uses_office_credentials():
    session = _session()
    identity = _identity_from_session(session)
    assert identity.authorization == "tok-office"
    assert identity.credentials["office"]["authorization"] == "tok-office"


def test_service_rejects_missing_connector_credential():
    session = _session()
    with pytest.raises(AppError) as ei:
        _authorization_for_tool(session, "demo")
    assert ei.value.code == "CONNECTOR_CREDENTIAL_MISSING"


def test_executor_authorization_for_rejects_wrong_connector_fallback():
    identity = Identity(
        oa="u1",
        authorization="tok-office",
        credentials={"office": {"authorization": "tok-office", "expires_at": 1}},
    )
    assert authorization_for(identity, "office") == "tok-office"
    with pytest.raises(ToolError) as ei:
        authorization_for(identity, "demo")
    assert ei.value.code == "CONNECTOR_CREDENTIAL_MISSING"
    # OA upstreams 信任域可显式允许回落 office 票
    assert authorization_for(identity, "hr", allow_office_fallback=True) == "tok-office"


def test_executor_authorization_for_uses_connector_entry():
    identity = Identity(
        oa="u1",
        authorization="tok-office",
        credentials={
            "office": {"authorization": "tok-office"},
            "demo": {"authorization": "tok-demo"},
        },
    )
    assert authorization_for(identity, "demo") == "tok-demo"
