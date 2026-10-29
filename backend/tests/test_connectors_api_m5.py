"""M5 Task 3：连接器只读总览。"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from oa_agent.db.models import McpServer
from tests.conftest import login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

URL = "/v1/admin/connectors"


def _client_with_perm(admin, installed, username: str, perm: str):
    role = _role(admin, f"{username}_role", [perm])
    _user(admin, username, [role["id"]])
    return login(TestClient(installed.app), username, VIEWER_PASS)


def test_requires_login_and_either_supported_permission(admin, installed):
    assert TestClient(installed.app).get(URL).status_code == 401

    no_perm_role = _role(admin, "connector_none", [])
    _user(admin, "connector_none", [no_perm_role["id"]])
    no_perm = login(TestClient(installed.app), "connector_none", VIEWER_PASS)
    assert no_perm.get(URL).status_code == 403

    setting_viewer = _client_with_perm(admin, installed, "connector_setting", "sys.setting.view")
    tool_manager = _client_with_perm(admin, installed, "connector_tool", "ops.tool.manage")
    assert setting_viewer.get(URL).status_code == 200
    assert tool_manager.get(URL).status_code == 200


def test_lists_http_and_mcp_shape_without_secrets(admin, installed):
    saved = admin.put("/v1/admin/settings/oa", json={"values": {
        "upstreams": [
            {"key": "office", "label": "办公接口", "base_url": "https://office.example.com/api"},
            {"key": "hr", "label": "人事接口", "base_url": "https://hr.example.com"},
        ],
        "gateway_secret": "connector-secret-value",
    }})
    assert saved.status_code == 200, saved.text

    runtime = installed.app.state.runtime
    with runtime.session() as db, db.begin():
        db.add_all([
            McpServer(
                tenant_id=runtime.tenant_id,
                name="enabled_stdio",
                display_name="本地 MCP",
                transport="stdio",
                command="mcp-secret-command",
                enabled=True,
                env_json=["SECRET_TOKEN"],
            ),
            McpServer(
                tenant_id=runtime.tenant_id,
                name="disabled_http",
                display_name="停用 MCP",
                transport="http",
                url="https://secret.example.com/mcp",
                enabled=False,
                headers_secret_ref="mcp.disabled_http.headers",
            ),
            McpServer(
                tenant_id=runtime.tenant_id,
                name="missing_target",
                display_name="缺少目标",
                transport="sse",
                enabled=True,
            ),
        ])

    response = admin.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"items"}
    assert all({"id", "kind", "label", "health"} <= set(item) for item in body["items"])
    assert all(set(item) <= {"id", "kind", "label", "envelope_profile", "health"} for item in body["items"])

    by_id = {item["id"]: item for item in body["items"]}
    assert by_id["office"] == {
        "id": "office",
        "kind": "http",
        "label": "办公接口",
        "envelope_profile": "oa_office",
        "health": "configured",
    }
    assert by_id["hr"]["health"] == "configured"
    assert by_id["enabled_stdio"] == {
        "id": "enabled_stdio",
        "kind": "mcp",
        "label": "本地 MCP",
        "health": "configured",
    }
    assert by_id["disabled_http"]["health"] == "missing"
    assert by_id["missing_target"]["health"] == "missing"
    assert by_id["builtin"] == {
        "id": "builtin",
        "kind": "builtin",
        "label": "内置运行时",
        "health": "configured",
    }
    assert body["items"][-1]["kind"] == "builtin"
    assert any(item["kind"] == "builtin" and item["health"] == "configured" for item in body["items"])

    encoded = json.dumps(body, ensure_ascii=False)
    for secret in (
        "connector-secret-value",
        "mcp-secret-command",
        "SECRET_TOKEN",
        "secret.example.com",
        "headers_secret_ref",
        "gateway_secret",
    ):
        assert secret not in encoded


def test_empty_configuration_still_includes_builtin(admin):
    response = admin.get(URL)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items == [{
        "id": "builtin",
        "kind": "builtin",
        "label": "内置运行时",
        "health": "configured",
    }]
