"""HTTP 测调 API：按契约 mint 测试员工并向所选上游发请求。"""

from __future__ import annotations

from types import SimpleNamespace


def test_http_probe_builds_request_and_returns_data(admin, monkeypatch):
    from oa_agent.chat import service as chat_service

    class FakeMint:
        authorization = "Bearer t"
        oa = "tester"

    class FakeClient:
        def get(self, path, params, authorization, timeout=None):
            assert path == "/hr/leave/index"
            assert authorization == "Bearer t"
            assert params.get("oa") == "tester" or "queryParams" in params
            return SimpleNamespace(data={"list": [{"id": 1, "status": "ok"}], "total": 1})

    monkeypatch.setattr(chat_service, "tool_clients", lambda rt: {"open_oa": FakeClient()})
    monkeypatch.setattr(chat_service, "office_client", lambda rt: SimpleNamespace(
        mint=lambda oa, secret: FakeMint(),
    ))
    monkeypatch.setattr(chat_service, "load_settings", lambda rt, group: {"gateway_secret": "sec"})

    r = admin.post(
        "/v1/admin/tools/http-probe",
        json={
            "oa": "tester",
            "args": {"page": 1},
            "upstream": "open_oa",
            "path": "/hr/leave/index",
            "method": "GET",
            "timeout_seconds": 10,
            "inject_identity_fields": [],
            "identity_bindings": [],
            "top_level_fields": ["page"],
            "query_params_field": None,
            "identity_params": {"oa": "oa"},
            "model_params": {"page": {"type": "integer", "required": False}},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["list"][0]["id"] == 1


def test_http_probe_rejects_non_relative_path(admin):
    r = admin.post(
        "/v1/admin/tools/http-probe",
        json={
            "oa": "tester",
            "args": {},
            "upstream": "open_oa",
            "path": "https://evil.example/x",
            "method": "GET",
        },
    )
    assert r.status_code == 422, r.text
