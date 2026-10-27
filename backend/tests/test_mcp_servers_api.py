"""Task 5：/v1/admin/mcp-servers CRUD（ops.mcp.manage + CSRF + Idempotency-Key + 审计；密钥只写不读）。"""

from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

pytest_plugins = ("tests.test_chat",)

URL = "/v1/admin/mcp-servers"
SECRET_TOKEN = "Bearer sk-live-SUPERSECRET-9f8e7d6c"


def http_body(**over) -> dict:
    body = {"name": "demo_http", "display_name": "Demo HTTP", "transport": "http",
            "url": "https://mcp.example.internal/mcp", "tool_prefix": "demo_", "timeout_seconds": 20,
            "enabled": False}
    body.update(over)
    return body


def stdio_body(**over) -> dict:
    body = {"name": "demo_stdio", "display_name": "Demo stdio", "transport": "stdio",
            "command": "/usr/local/bin/mcp-demo", "args": ["--flag"], "timeout_seconds": 30, "enabled": False}
    body.update(over)
    return body


def set_allowlist(admin, origins: list[str]) -> None:
    r = admin.put("/v1/admin/settings/mcp", json={"values": {"allowed_origins": origins}})
    assert r.status_code == 200, r.text


# ---------------- 校验 ----------------

def test_http_without_allowlist_rejected(admin):
    r = admin.post(URL, json=http_body())
    assert r.status_code == 422, r.text
    assert "白名单" in r.json()["error"]["message"]
    assert admin.get(URL).json()["items"] == []


def test_http_host_not_in_allowlist_rejected(admin):
    set_allowlist(admin, ["https://other.example.internal"])
    r = admin.post(URL, json=http_body())
    assert r.status_code == 422, r.text
    assert "白名单" in r.json()["error"]["message"]


def test_stdio_missing_command_rejected(admin):
    r = admin.post(URL, json=stdio_body(command=None))
    assert r.status_code == 422, r.text
    r = admin.post(URL, json=stdio_body(command="  "))
    assert r.status_code == 422, r.text


def test_stdio_rejects_shell_command_and_remote_fields(admin):
    assert admin.post(URL, json=stdio_body(command="npx foo; rm -rf /")).status_code == 422
    assert admin.post(URL, json=stdio_body(url="https://x.example.internal")).status_code == 422
    assert admin.post(URL, json=stdio_body(headers={"A": "b"})).status_code == 422


def test_remote_rejects_command_env_and_bad_url(admin):
    set_allowlist(admin, ["https://mcp.example.internal"])
    assert admin.post(URL, json=http_body(command="npx")).status_code == 422
    assert admin.post(URL, json=http_body(env={"A": "b"})).status_code == 422
    assert admin.post(URL, json=http_body(url=None)).status_code == 422
    assert admin.post(URL, json=http_body(url="file:///etc/passwd")).status_code == 422
    assert admin.post(URL, json=http_body(url="https://user:pw@mcp.example.internal/mcp")).status_code == 422
    assert admin.post(URL, json=http_body(url="http://mcp.example.internal/mcp")).status_code == 422


def test_invalid_name_and_transport_rejected(admin):
    assert admin.post(URL, json=stdio_body(name="Bad Name")).status_code == 422
    assert admin.post(URL, json=stdio_body(transport="ws")).status_code == 422
    assert admin.post(URL, json=stdio_body(timeout_seconds=0)).status_code == 422


# ---------------- CRUD ----------------

def test_create_http_and_stdio_then_list_get(admin):
    set_allowlist(admin, ["https://mcp.example.internal"])
    r = admin.post(URL, json=http_body())
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["name"] == "demo_http" and created["transport"] == "http"
    assert created["url"] == "https://mcp.example.internal/mcp" and created["enabled"] is False
    assert created["headers_set"] == {"is_set": False, "display": "未设置"}
    assert admin.post(URL, json=stdio_body()).status_code == 200

    items = admin.get(URL).json()["items"]
    assert [i["name"] for i in items] == ["demo_http", "demo_stdio"]
    detail = admin.get(f"{URL}/demo_stdio").json()
    assert detail["command"] == "/usr/local/bin/mcp-demo" and detail["args"] == ["--flag"]
    assert admin.get(f"{URL}/nope").status_code == 404


def test_allowlist_matches_default_port_and_case(admin):
    set_allowlist(admin, ["https://MCP.example.internal:443"])
    assert admin.post(URL, json=http_body(url="https://mcp.example.internal/mcp")).status_code == 200


def test_allowlist_port_must_match(admin):
    set_allowlist(admin, ["https://mcp.example.internal"])
    r = admin.post(URL, json=http_body(url="https://mcp.example.internal:8443/mcp"))
    assert r.status_code == 422


def test_duplicate_name_conflict(admin):
    assert admin.post(URL, json=stdio_body()).status_code == 200
    assert admin.post(URL, json=stdio_body()).status_code == 409


def test_update_and_name_immutable(admin):
    assert admin.post(URL, json=stdio_body()).status_code == 200
    r = admin.put(f"{URL}/demo_stdio", json=stdio_body(display_name="改名", timeout_seconds=45, enabled=True))
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "改名" and r.json()["timeout_seconds"] == 45 and r.json()["enabled"] is True
    assert admin.put(f"{URL}/demo_stdio", json=stdio_body(name="other")).status_code == 422
    assert admin.put(f"{URL}/ghost", json=stdio_body(name="ghost")).status_code == 404


def test_delete(admin):
    assert admin.post(URL, json=stdio_body()).status_code == 200
    assert admin.delete(f"{URL}/demo_stdio").status_code == 200
    assert admin.get(f"{URL}/demo_stdio").status_code == 404
    assert admin.delete(f"{URL}/demo_stdio").status_code == 404


def test_delete_blocked_when_tools_reference_server(admin, installed):
    from oa_agent.db.models import McpServer, Tool

    assert admin.post(URL, json=stdio_body()).status_code == 200
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        sid = db.scalar(sa.select(McpServer.id).where(McpServer.name == "demo_stdio"))
        db.add(Tool(tenant_id=rt.tenant_id, name="demo_echo", kind="mcp", mcp_server_id=sid,
                    mcp_tool_name="echo"))
    r = admin.delete(f"{URL}/demo_stdio")
    assert r.status_code == 409, r.text
    assert admin.get(f"{URL}/demo_stdio").status_code == 200


# ---------------- 密钥只写不读 ----------------

def test_secrets_write_only_masked_everywhere(admin, installed):
    set_allowlist(admin, ["https://mcp.example.internal"])
    r = admin.post(URL, json=http_body(headers={"Authorization": SECRET_TOKEN}))
    assert r.status_code == 200, r.text
    assert r.json()["headers_set"]["is_set"] is True
    assert admin.post(URL, json=stdio_body(env={"API_KEY": "key-ENVSECRET-12345678"})).status_code == 200

    blobs = [r.text, admin.get(URL).text, admin.get(f"{URL}/demo_http").text, admin.get(f"{URL}/demo_stdio").text]
    detail = admin.get(f"{URL}/demo_stdio").json()
    assert detail["env_set"]["is_set"] is True and "headers" not in detail and "env" not in detail
    # 审计与响应均不含明文
    blobs.append(json.dumps(audit_rows(admin), ensure_ascii=False))
    for blob in blobs:
        assert "SUPERSECRET" not in blob and "ENVSECRET" not in blob

    # 数据库中密文（非明文）
    rt = installed.app.state.runtime
    with rt.session() as db:
        raw = db.execute(sa.text("SELECT name, ciphertext FROM agent_secret WHERE name LIKE 'mcp.%'")).all()
        assert len(raw) == 2
        for _, ct in raw:
            assert b"SUPERSECRET" not in bytes(ct) and b"ENVSECRET" not in bytes(ct)
        row = db.execute(sa.text("SELECT env_json, headers_secret_ref FROM agent_mcp_server")).all()
        assert all("ENVSECRET" not in str(x) for x in row)


def test_update_secret_semantics_keep_replace_clear(admin, installed):
    assert admin.post(URL, json=stdio_body(env={"A": "value-one-1111"})).status_code == 200
    # 不带 env = 沿用
    r = admin.put(f"{URL}/demo_stdio", json=stdio_body(display_name="x"))
    assert r.json()["env_set"]["is_set"] is True
    # 空对象 = 清除
    r = admin.put(f"{URL}/demo_stdio", json=stdio_body(env={}))
    assert r.json()["env_set"] == {"is_set": False, "display": "未设置"}
    # 再设置，delete 同步清理 vault
    assert admin.put(f"{URL}/demo_stdio", json=stdio_body(env={"B": "value-two-2222"})).status_code == 200
    assert admin.delete(f"{URL}/demo_stdio").status_code == 200
    rt = installed.app.state.runtime
    with rt.session() as db:
        assert db.scalar(sa.text("SELECT COUNT(*) FROM agent_secret WHERE name LIKE 'mcp.%'")) == 0


# ---------------- 审计 / 权限 / 幂等 ----------------

def test_audit_recorded(admin):
    assert admin.post(URL, json=stdio_body()).status_code == 200
    assert admin.put(f"{URL}/demo_stdio", json=stdio_body(display_name="n")).status_code == 200
    assert admin.delete(f"{URL}/demo_stdio").status_code == 200
    actions = {a["action"] for a in audit_rows(admin)}
    assert {"mcp_server.create", "mcp_server.update", "mcp_server.delete"} <= actions


def test_requires_ops_mcp_manage_permission(admin, installed):
    role = _role(admin, "tool_only", ["ops.tool.manage"])
    _user(admin, "toolonly", [role["id"]])
    other = login(TestClient(installed.app), "toolonly", VIEWER_PASS)
    assert other.get(URL).status_code == 403
    assert other.post(URL, json=stdio_body()).status_code == 403
    assert admin.get(URL).json()["items"] == []


def test_write_requires_csrf_and_idempotency_key(admin, installed):
    c = admin.client
    r = c.post(URL, json=stdio_body(), headers={"Idempotency-Key": "k1"})
    assert r.status_code == 403
    r = c.post(URL, json=stdio_body(), headers={"X-CSRF-Token": admin.csrf})
    assert r.status_code == 400
    h = {"X-CSRF-Token": admin.csrf, "Idempotency-Key": "same-key"}
    assert c.post(URL, json=stdio_body(), headers=h).status_code == 200
    assert c.post(URL, json=stdio_body(name="other_one"), headers=h).status_code == 409
