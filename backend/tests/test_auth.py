from oa_agent.auth.sessions import COOKIE_NAME
from tests.conftest import ADMIN_PASS, ADMIN_USER, audit_rows, login


def test_login_me_logout(installed):
    admin = login(installed)
    me = installed.get("/v1/admin/auth/me").json()
    assert me["user"]["username"] == ADMIN_USER
    assert "super_admin" in me["roles"]
    assert "sys.setting.edit" in me["perms"]
    assert admin.post("/v1/admin/auth/logout").status_code == 200
    assert installed.get("/v1/admin/auth/me").status_code == 401


def test_session_cookie_flags(settings, installed):
    r = installed.post("/v1/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    cookie = r.headers["set-cookie"]
    assert COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie


def test_wrong_password_and_lockout(installed):
    for _ in range(4):
        r = installed.post("/v1/admin/auth/login", json={"username": ADMIN_USER, "password": "wrong"})
        assert r.status_code == 401
    r = installed.post("/v1/admin/auth/login", json={"username": ADMIN_USER, "password": "wrong"})
    assert r.status_code == 423
    r = installed.post("/v1/admin/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
    assert r.status_code == 423 and r.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_unknown_user_same_message(installed):
    r = installed.post("/v1/admin/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "用户名或密码错误"


def test_write_requires_csrf_and_idempotency(admin):
    c = admin.client
    body = {"values": {"bot_id": "aib-test"}}
    r = c.put("/v1/admin/settings/wecom", json=body, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_FAILED"

    r = c.put("/v1/admin/settings/wecom", json=body, headers={"X-CSRF-Token": admin.csrf})
    assert r.status_code == 400 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"

    h = {"X-CSRF-Token": admin.csrf, "Idempotency-Key": "same-key"}
    assert c.put("/v1/admin/settings/wecom", json=body, headers=h).status_code == 200
    r = c.put("/v1/admin/settings/wecom", json=body, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_REQUEST"


def test_change_password(admin, installed):
    new = "An0ther!Passw0rd"
    assert admin.post("/v1/admin/auth/password", json={"old_password": "bad", "new_password": new}).status_code == 400
    assert admin.post("/v1/admin/auth/password",
                      json={"old_password": ADMIN_PASS, "new_password": "weak"}).status_code == 422
    assert admin.post("/v1/admin/auth/password",
                      json={"old_password": ADMIN_PASS, "new_password": new}).status_code == 200
    login(installed, password=new)
    rows = audit_rows(admin, action="admin.password.change")
    assert rows and new not in str(rows)


def test_login_audited(installed):
    installed.post("/v1/admin/auth/login", json={"username": ADMIN_USER, "password": "wrong-pass"})
    admin = login(installed)
    rows = audit_rows(admin, action="admin.login")
    results = [r["result"] for r in rows]
    assert "failure" in results and "success" in results
    assert "wrong-pass" not in str(rows)
