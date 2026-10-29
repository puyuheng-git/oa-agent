import httpx
import respx

from tests.conftest import audit_rows

API_KEY = "sk-test-very-secret-KEY9"


def _create_provider(admin, **kw):
    body = {"name": "deepseek", "base_url": "https://llm.example.com/v1", "api_key": API_KEY, **kw}
    r = admin.post("/v1/admin/llm/providers", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_provider_key_masked_and_audited(admin):
    p = _create_provider(admin)
    assert p["api_key"] == {"is_set": True, "display": "已设置 · ****KEY9"}
    listed = admin.get("/v1/admin/llm/providers")
    assert API_KEY not in listed.text
    rows = audit_rows(admin, action="llm.provider")
    assert rows and API_KEY not in str(rows)


@respx.mock
def test_provider_and_model_connection_tests(admin):
    p = _create_provider(admin)
    route = respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "deepseek-chat"}]}))
    r = admin.post(f"/v1/admin/llm/providers/{p['id']}/test")
    assert r.json()["ok"] is True and r.json()["models"] == ["deepseek-chat"]
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {API_KEY}"

    m = admin.post("/v1/admin/llm/models", json={
        "provider_id": p["id"], "model_name": "deepseek-chat", "temperature": 0.2, "purpose_tags": ["intent"]}).json()
    assert m["temperature"] == 0.2 and m["purpose_tags"] == ["intent"]

    respx.post("https://llm.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"usage": {"prompt_tokens": 3, "completion_tokens": 1}}))
    r = admin.post(f"/v1/admin/llm/models/{m['id']}/test")
    assert r.json()["ok"] is True
    assert r.json()["usage"] == {"prompt_tokens": 3, "completion_tokens": 1}


@respx.mock
def test_provider_failure_reported_without_key(admin):
    p = _create_provider(admin)
    respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(401, text=f"invalid api key {API_KEY}"))
    r = admin.post(f"/v1/admin/llm/providers/{p['id']}/test").json()
    assert r["ok"] is False and "401" in r["error"]
    assert API_KEY not in r["error"]


def test_provider_with_models_cannot_be_deleted(admin):
    p = _create_provider(admin)
    m = admin.post("/v1/admin/llm/models", json={"provider_id": p["id"], "model_name": "x"}).json()
    assert admin.delete(f"/v1/admin/llm/providers/{p['id']}").status_code == 409
    assert admin.delete(f"/v1/admin/llm/models/{m['id']}").status_code == 200
    assert admin.delete(f"/v1/admin/llm/providers/{p['id']}").status_code == 200


def test_update_keeps_key_when_blank_and_can_clear(admin):
    p = _create_provider(admin)
    body = {"name": "deepseek", "base_url": "https://llm.example.com/v1"}
    r = admin.put(f"/v1/admin/llm/providers/{p['id']}", json=body).json()
    assert r["api_key"]["is_set"] is True
    r = admin.put(f"/v1/admin/llm/providers/{p['id']}", json={**body, "clear_api_key": True}).json()
    assert r["api_key"]["is_set"] is False


def test_readyz_reports_llm_configured_not_checked(admin):
    p = _create_provider(admin)
    admin.post("/v1/admin/llm/models", json={"provider_id": p["id"], "model_name": "x"})
    llm = admin.get("/readyz").json()["llm"]
    assert llm["status"] == "已配置（未检测）"


@respx.mock
def test_remote_models_lists_from_provider(admin):
    p = _create_provider(admin)
    respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}))
    r = admin.get(f"/v1/admin/llm/providers/{p['id']}/remote-models")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["models"] == ["a", "b", "c"]
    assert body["model_count"] == 3
    assert body["truncated"] is False
    assert "latency_ms" in body
    assert API_KEY not in r.text


@respx.mock
def test_remote_models_truncated_at_200(admin):
    p = _create_provider(admin)
    data = [{"id": f"m{i}"} for i in range(250)]
    respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": data}))
    body = admin.get(f"/v1/admin/llm/providers/{p['id']}/remote-models").json()
    assert body["ok"] is True
    assert body["model_count"] == 250
    assert body["truncated"] is True
    assert len(body["models"]) == 200
    assert body["models"][0] == "m0"
    assert body["models"][-1] == "m199"


@respx.mock
def test_provider_test_still_limits_to_50(admin):
    p = _create_provider(admin)
    data = [{"id": f"m{i}"} for i in range(60)]
    respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": data}))
    body = admin.post(f"/v1/admin/llm/providers/{p['id']}/test").json()
    assert body["ok"] is True
    assert body["model_count"] == 60
    assert body["truncated"] is True
    assert len(body["models"]) == 50


def test_remote_models_without_api_key(admin):
    p = _create_provider(admin)
    admin.put(f"/v1/admin/llm/providers/{p['id']}", json={
        "name": "deepseek", "base_url": "https://llm.example.com/v1", "clear_api_key": True})
    body = admin.get(f"/v1/admin/llm/providers/{p['id']}/remote-models").json()
    assert body["ok"] is False
    assert "API Key" in body["error"] or "api key" in body["error"].lower() or "密钥" in body["error"]


@respx.mock
def test_remote_models_failure_redacts_key(admin):
    p = _create_provider(admin)
    respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(401, text=f"invalid api key {API_KEY}"))
    body = admin.get(f"/v1/admin/llm/providers/{p['id']}/remote-models").json()
    assert body["ok"] is False and "401" in body["error"]
    assert API_KEY not in body["error"]


def test_remote_models_provider_not_found(admin):
    assert admin.get("/v1/admin/llm/providers/99999/remote-models").status_code == 404


def test_remote_models_forbidden_without_view(admin, installed):
    from fastapi.testclient import TestClient
    from tests.conftest import login

    role = admin.post("/v1/admin/roles", json={"code": "no_setting", "name": "no_setting", "perm_codes": []}).json()
    admin.post("/v1/admin/accounts", json={
        "username": "nolmview", "password": "Reader!Passw0rd1", "role_ids": [role["id"]]})
    other = login(TestClient(installed.app), "nolmview", "Reader!Passw0rd1")
    p = _create_provider(admin)
    assert other.get(f"/v1/admin/llm/providers/{p['id']}/remote-models").status_code == 403
