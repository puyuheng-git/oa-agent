"""STD-009：跨域静态对话页调用 /v1/chat。"""

from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient

from oa_agent.main import create_app
from oa_agent.settings import AppSettings
from tests.conftest import make_settings, login, install_payload
from tests.test_chat import HMAC_SECRET, OFFICE, GATEWAY, make_assertion, mint_handler


def test_chat_cors_origins_reads_chat_cors_origins_env(monkeypatch):
    monkeypatch.setenv("CHAT_CORS_ORIGINS", "https://from-env.test")
    monkeypatch.delenv("OA_AGENT_CHAT_CORS_ORIGINS", raising=False)
    settings = AppSettings()
    assert settings.chat_cors_allowlist() == ["https://from-env.test"]


@pytest.fixture
def office():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{OFFICE}/agent/token/mint").mock(side_effect=mint_handler)
        yield mock


@pytest.fixture
def cors_client(tmp_path, office):
    settings = make_settings(tmp_path)
    settings.chat_cors_origins = "https://chat.static.test,https://other.test"
    with TestClient(create_app(settings)) as client:
        r = client.post("/v1/setup/install", json=install_payload(settings))
        assert r.status_code == 200, r.text
        admin = login(client)
        admin.put("/v1/admin/settings/oa", json={"values": {
            "mint_base_url": OFFICE,
            "upstreams": [{"key": "office", "label": "office-api", "base_url": OFFICE}],
            "gateway_secret": GATEWAY,
            "assertion_hmac_secret": HMAC_SECRET,
        }})
        yield client, settings


def test_chat_cors_preflight_allowed(cors_client):
    client, _ = cors_client
    origin = "https://chat.static.test"
    r = client.options(
        "/v1/chat/launch",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert r.status_code == 204
    assert r.headers.get("access-control-allow-origin") == origin
    assert "POST" in r.headers.get("access-control-allow-methods", "")


def test_chat_cors_preflight_allows_idempotency_key_header(cors_client):
    client, _ = cors_client
    origin = "https://chat.static.test"
    r = client.options(
        "/v1/chat/launch",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type, idempotency-key",
        },
    )
    assert r.status_code == 204
    allow_headers = r.headers.get("access-control-allow-headers", "")
    assert "idempotency-key" in allow_headers.lower()


def test_chat_cors_preflight_rejects_unknown_origin(cors_client):
    client, _ = cors_client
    r = client.options("/v1/chat/launch", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_chat_cors_on_api_response(cors_client):
    client, _ = cors_client
    origin = "https://other.test"
    r = client.post(
        "/v1/chat/launch",
        json={"assertion": make_assertion()},
        headers={"Origin": origin},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == origin
