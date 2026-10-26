from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oa_agent.main import create_app
from oa_agent.settings import AppSettings

ADMIN_USER = "root_admin"
ADMIN_PASS = "Str0ng!Passw0rd"
DB_PASSWORD = "db-plaintext-pass-9876"


def make_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        data_dir=tmp_path / "data",
        frontend_dist=tmp_path / "dist",
        cookie_secure=False,
        allow_sqlite=True,
        master_key=None,
    )


class AdminClient:
    """带 CSRF + Idempotency-Key 的管理端客户端。"""

    def __init__(self, client: TestClient, csrf: str):
        self.client = client
        self.csrf = csrf

    def _h(self, extra=None):
        h = {"X-CSRF-Token": self.csrf, "Idempotency-Key": uuid.uuid4().hex}
        h.update(extra or {})
        return h

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, json=None, headers=None):
        return self.client.post(url, json=json, headers=self._h(headers))

    def put(self, url, json=None, headers=None):
        return self.client.put(url, json=json, headers=self._h(headers))

    def delete(self, url, headers=None):
        return self.client.delete(url, headers=self._h(headers))


def setup_token(settings: AppSettings) -> str:
    return settings.setup_token_path.read_text(encoding="utf-8").strip()


def install_payload(settings: AppSettings) -> dict:
    return {
        "token": setup_token(settings),
        "db": {"driver": "sqlite", "host": "-", "port": 1, "user": "-", "password": DB_PASSWORD,
               "database": str(settings.data_dir / "agent_ops.sqlite")},
        "admin": {"username": ADMIN_USER, "password": ADMIN_PASS, "display_name": "超管"},
    }


@pytest.fixture
def settings(tmp_path) -> AppSettings:
    return make_settings(tmp_path)


@pytest.fixture
def setup_client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def installed(settings):
    with TestClient(create_app(settings)) as c:
        r = c.post("/v1/setup/install", json=install_payload(settings))
        assert r.status_code == 200, r.text
        yield c


def login(client: TestClient, username=ADMIN_USER, password=ADMIN_PASS) -> AdminClient:
    r = client.post("/v1/admin/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return AdminClient(client, r.json()["csrf_token"])


@pytest.fixture
def admin(installed) -> AdminClient:
    return login(installed)


def audit_rows(admin: AdminClient, **params) -> list[dict]:
    r = admin.get("/v1/admin/audit", params={"page_size": 100, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]
