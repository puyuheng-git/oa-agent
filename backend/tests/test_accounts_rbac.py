from tests.conftest import audit_rows, login

VIEWER_PASS = "Reader!Passw0rd1"


def _role(admin, code, perms):
    r = admin.post("/v1/admin/roles", json={"code": code, "name": code, "perm_codes": perms})
    assert r.status_code == 200, r.text
    return r.json()


def _user(admin, username, role_ids, password=VIEWER_PASS):
    r = admin.post("/v1/admin/accounts", json={"username": username, "password": password, "role_ids": role_ids})
    assert r.status_code == 200, r.text
    return r.json()


def test_no_permission_gets_403_and_denied_is_audited(admin, installed):
    role = _role(admin, "setting_viewer", ["sys.setting.view"])
    _user(admin, "viewer", [role["id"]])

    from fastapi.testclient import TestClient

    other = TestClient(installed.app)
    viewer = login(other, "viewer", VIEWER_PASS)
    assert viewer.get("/v1/admin/settings").status_code == 200
    r = viewer.put("/v1/admin/settings/oa", json={"values": {"gateway_secret": "x" * 10}})
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    assert viewer.get("/v1/admin/accounts").status_code == 403
    assert viewer.get("/v1/admin/audit").status_code == 403
    assert viewer.post("/v1/admin/llm/providers", json={"name": "a", "base_url": "https://a.b"}).status_code == 403

    rows = audit_rows(admin, action="access.denied")
    assert {r["actor_id"] for r in rows} == {"viewer"}
    assert all(r["result"] == "denied" for r in rows)


def test_permission_change_takes_effect_immediately(admin, installed):
    role = _role(admin, "r1", [])
    _user(admin, "user1", [role["id"]])
    from fastapi.testclient import TestClient

    u1 = login(TestClient(installed.app), "user1", VIEWER_PASS)
    assert u1.get("/v1/admin/settings").status_code == 403
    admin.put(f"/v1/admin/roles/{role['id']}", json={"code": "r1", "name": "r1", "perm_codes": ["sys.setting.view"]})
    assert u1.get("/v1/admin/settings").status_code == 200


def test_disabled_user_session_revoked(admin, installed):
    role = _role(admin, "r2", ["sys.setting.view"])
    u = _user(admin, "user2", [role["id"]])
    from fastapi.testclient import TestClient

    u2 = login(TestClient(installed.app), "user2", VIEWER_PASS)
    admin.put(f"/v1/admin/accounts/{u['id']}", json={"status": "disabled", "role_ids": [role["id"]]})
    assert u2.get("/v1/admin/settings").status_code == 401


def test_last_super_admin_protected(admin):
    me = admin.get("/v1/admin/auth/me").json()
    uid = me["user"]["id"]
    r = admin.put(f"/v1/admin/accounts/{uid}", json={"status": "active", "role_ids": []})
    assert r.status_code == 409 and r.json()["error"]["code"] == "LAST_SUPER_ADMIN"
    r = admin.put(f"/v1/admin/accounts/{uid}", json={"status": "disabled", "role_ids": [1]})
    assert r.status_code == 409


def test_builtin_role_immutable(admin):
    assert admin.put("/v1/admin/roles/1", json={"code": "super_admin", "name": "x"}).status_code == 409
    assert admin.delete("/v1/admin/roles/1").status_code == 409


def test_unknown_perm_and_weak_password_rejected(admin):
    r = admin.post("/v1/admin/roles", json={"code": "bad", "name": "bad", "perm_codes": ["nope"]})
    assert r.status_code == 422
    r = admin.post("/v1/admin/accounts", json={"username": "weakling", "password": "abc"})
    assert r.status_code == 422


def test_account_changes_audited_without_password(admin):
    role = _role(admin, "r3", ["ops.audit.view"])
    u = _user(admin, "user3", [role["id"]])
    admin.post(f"/v1/admin/accounts/{u['id']}/reset-password", json={"password": "Brand!NewPass9"})
    actions = {r["action"] for r in audit_rows(admin)}
    assert {"role.create", "account.create", "account.password.reset"} <= actions
    assert VIEWER_PASS not in str(audit_rows(admin)) and "Brand!NewPass9" not in str(audit_rows(admin))


def test_roles_list_and_perm_catalog(admin):
    perms = admin.get("/v1/admin/perms").json()["items"]
    assert any(p["code"] == "sys.account.manage" for p in perms)
    roles = admin.get("/v1/admin/roles").json()["items"]
    sa = next(r for r in roles if r["code"] == "super_admin")
    assert sa["is_builtin"] and len(sa["perm_codes"]) == len(perms) and sa["user_count"] == 1
