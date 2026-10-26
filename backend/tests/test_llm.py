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
