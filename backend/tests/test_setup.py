from fastapi.testclient import TestClient

from oa_agent.main import create_app
from tests.conftest import ADMIN_PASS, DB_PASSWORD, install_payload, login


def test_first_boot_enters_setup_mode(setup_client, settings):
    assert settings.master_key_path.exists()
    assert settings.setup_token_path.exists()
    assert setup_client.get("/healthz").json() == {"status": "ok", "mode": "setup"}
    r = setup_client.get("/v1/admin/auth/me")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "NOT_INSTALLED"
    assert setup_client.get("/readyz").status_code == 503


def test_bad_token_rejected_and_throttled(setup_client):
    for _ in range(10):
        assert setup_client.post("/v1/setup/verify-token", json={"token": "nope"}).status_code == 401
    assert setup_client.post("/v1/setup/verify-token", json={"token": "nope"}).status_code == 429


def test_mysql_only_unless_sqlite_allowed(tmp_path):
    from tests.conftest import make_settings

    s = make_settings(tmp_path)
    s.allow_sqlite = False
    with TestClient(create_app(s)) as c:
        r = c.post("/v1/setup/test-db", json={**install_payload(s), "admin": None})
        assert r.status_code == 422


def test_weak_admin_password_rejected(setup_client, settings):
    payload = install_payload(settings)
    payload["admin"]["password"] = "short"
    r = setup_client.post("/v1/setup/install", json=payload)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "WEAK_PASSWORD"
    assert not settings.bootstrap_path.exists()


def test_install_flow_closes_setup_and_survives_restart(setup_client, settings):
    payload = install_payload(settings)
    assert setup_client.post("/v1/setup/test-db", json=payload).json()["ok"] is True
    r = setup_client.post("/v1/setup/install", json=payload)
    assert r.status_code == 200, r.text

    assert not settings.setup_token_path.exists()
    raw = settings.bootstrap_path.read_text(encoding="utf-8")
    assert DB_PASSWORD not in raw and "password_enc" in raw

    assert setup_client.post("/v1/setup/install", json=payload).status_code == 404
    assert setup_client.get("/v1/setup/status").status_code == 404
    login(setup_client)

    with TestClient(create_app(settings)) as again:
        assert again.get("/healthz").json()["mode"] == "normal"
        ready = again.get("/readyz").json()
        assert ready["ready"] is True
        assert ready["database"]["migration"]["up_to_date"] is True
        assert ready["redis"]["status"] == "未配置"
        assert ready["llm"]["status"] == "未配置"
        login(again)


def test_install_writes_system_audit(installed):
    admin = login(installed)
    rows = admin.get("/v1/admin/audit", params={"action": "system.install"}).json()["items"]
    assert len(rows) == 1 and rows[0]["actor_type"] == "system"
    assert ADMIN_PASS not in str(rows)
