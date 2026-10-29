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


# ---------------- Task 7：test / sync ----------------

class FakeMcp:
    """替身出站客户端：list_tools / call_tool 都不触网。"""

    def __init__(self, tools=None, fail=None):
        self.tools = tools if tools is not None else [
            {"name": "echo", "description": "回显", "input_schema": {"type": "object"}},
            {"name": "add", "description": "加法", "input_schema": {"type": "object"}},
        ]
        self.fail = fail
        self.listed: list = []

    def list_tools(self, server):
        self.listed.append(server)
        if self.fail:
            raise self.fail
        return list(self.tools)

    def call_tool(self, name, arguments, *, identity, server_id=None):
        return {"text": "ok", "truncated": False}


def _fake(installed, **kw) -> FakeMcp:
    fake = FakeMcp(**kw)
    installed.app.state.runtime.mcp_client = fake
    return fake


def _tools(installed, server_id=None):
    from oa_agent.db.models import Tool

    rt = installed.app.state.runtime
    with rt.session() as db:
        rows = db.scalars(sa.select(Tool).where(Tool.kind == "mcp").order_by(Tool.name)).all()
        return [(t.name, t.mcp_tool_name, t.enabled, t.mcp_server_id) for t in rows]


def test_test_endpoint_returns_ok_and_count_without_writing_tools(admin, installed):
    fake = _fake(installed)
    assert admin.post(URL, json=stdio_body(env={"API_KEY": "key-ENVSECRET-12345678"})).status_code == 200
    r = admin.post(f"{URL}/demo_stdio/test")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["count"] == 2
    assert _tools(installed) == []
    # 探测配置带上了保险箱里的 env（仅服务端内部），响应/审计不含明文
    assert fake.listed[0].env == {"API_KEY": "key-ENVSECRET-12345678"}
    assert "ENVSECRET" not in r.text and "ENVSECRET" not in json.dumps(audit_rows(admin), ensure_ascii=False)
    assert "mcp_server.test" in {a["action"] for a in audit_rows(admin)}


def test_test_endpoint_reports_failure_honestly(admin, installed):
    from oa_agent.executor.executor import ToolError

    _fake(installed, fail=ToolError("UPSTREAM_UNAVAILABLE", "demo_stdio 连接失败：ConnectionError"))
    assert admin.post(URL, json=stdio_body()).status_code == 200
    r = admin.post(f"{URL}/demo_stdio/test")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and "连接失败" in r.json()["error"]


def test_sync_creates_disabled_prefixed_mcp_tools(admin, installed):
    _fake(installed)
    assert admin.post(URL, json=stdio_body(tool_prefix="demo_")).status_code == 200
    r = admin.post(f"{URL}/demo_stdio/sync")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["count"] == 2
    assert sorted(r.json()["created"]) == ["demo_add", "demo_echo"]
    rows = _tools(installed)
    assert [(n, m, e) for n, m, e, _ in rows] == [("demo_add", "add", False), ("demo_echo", "echo", False)]
    assert all(sid is not None for *_, sid in rows)
    detail = admin.get(f"{URL}/demo_stdio").json()
    assert detail["last_sync_result"] == "ok" and detail["last_sync_error"] is None and detail["last_sync_at"]
    assert "mcp_server.sync" in {a["action"] for a in audit_rows(admin)}


def test_sync_maps_input_schema_properties_to_model_params(admin, installed):
    from oa_agent.db.models import Tool, ToolVersion

    _fake(installed, tools=[{
        "name": "search", "description": "搜索",
        "input_schema": {
            "type": "object", "required": ["q"],
            "properties": {
                "q": {"type": "string", "description": "关键词"},
                "limit": {"type": "integer", "description": "条数"},
                "active": {"type": "boolean", "description": "仅有效"},
            },
        },
    }])
    assert admin.post(URL, json=stdio_body(tool_prefix="demo_")).status_code == 200
    assert admin.post(f"{URL}/demo_stdio/sync").status_code == 200
    rt = installed.app.state.runtime
    with rt.session() as db:
        tool = db.scalar(sa.select(Tool).where(Tool.name == "demo_search"))
        assert tool is not None and tool.enabled is False
        ver = db.get(ToolVersion, tool.current_version_id)
        mp = (ver.schema_json or {}).get("model_params") or {}
    assert set(mp) == {"q", "limit", "active"}
    assert mp["q"]["type"] == "string" and mp["q"]["required"] is True and mp["q"]["description"] == "关键词"
    assert mp["limit"]["type"] == "integer" and mp["active"]["type"] == "boolean"


def test_sync_is_idempotent_and_keeps_admin_enabled_flag(admin, installed):
    from oa_agent.db.models import Tool

    _fake(installed)
    assert admin.post(URL, json=stdio_body(tool_prefix="demo_")).status_code == 200
    assert admin.post(f"{URL}/demo_stdio/sync").status_code == 200
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        db.scalar(sa.select(Tool).where(Tool.name == "demo_echo")).enabled = True
    r = admin.post(f"{URL}/demo_stdio/sync", headers={"Idempotency-Key": "again"})
    assert r.status_code == 200 and r.json()["created"] == []
    assert dict((n, e) for n, _, e, _ in _tools(installed)) == {"demo_add": False, "demo_echo": True}


def test_sync_removed_tool_deleted_when_unreferenced_else_disabled(admin, installed):
    from oa_agent.db.models import Skill, SkillVersion, Tool

    fake = _fake(installed)
    assert admin.post(URL, json=stdio_body(tool_prefix="demo_")).status_code == 200
    assert admin.post(f"{URL}/demo_stdio/sync").status_code == 200
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        db.scalar(sa.select(Tool).where(Tool.name == "demo_echo")).enabled = True
        skill = Skill(tenant_id=rt.tenant_id, name="uses_echo", enabled=True)
        db.add(skill)
        db.flush()
        ver = SkillVersion(skill_id=skill.id, version_no=1, content_json={"tools": ["demo_echo"]}, content_hash="h")
        db.add(ver)
        db.flush()
        skill.current_version_id = ver.id
    fake.tools = []  # 远端全部消失
    r = admin.post(f"{URL}/demo_stdio/sync", headers={"Idempotency-Key": "gone"})
    assert r.status_code == 200, r.text
    assert r.json()["removed"] == ["demo_add"] and r.json()["disabled"] == ["demo_echo"]
    assert [(n, e) for n, _, e, _ in _tools(installed)] == [("demo_echo", False)]
    with rt.session() as db:
        err = db.scalar(sa.select(Tool.last_sync_error).where(Tool.name == "demo_echo"))
    assert err and "Skill" in err


def test_sync_name_conflict_with_other_tool_is_skipped(admin, installed):
    from oa_agent.db.models import Tool

    _fake(installed)
    assert admin.post(URL, json=stdio_body(tool_prefix="demo_")).status_code == 200
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        db.add(Tool(tenant_id=rt.tenant_id, name="demo_echo", kind="office"))
    r = admin.post(f"{URL}/demo_stdio/sync")
    assert r.status_code == 200, r.text
    assert r.json()["created"] == ["demo_add"] and r.json()["skipped"][0]["name"] == "demo_echo"
    with rt.session() as db:
        assert db.scalar(sa.select(Tool.kind).where(Tool.name == "demo_echo")) == "office"


def test_sync_failure_records_error_and_keeps_tools(admin, installed):
    from oa_agent.executor.executor import ToolError

    fake = _fake(installed)
    assert admin.post(URL, json=stdio_body(tool_prefix="demo_")).status_code == 200
    assert admin.post(f"{URL}/demo_stdio/sync").status_code == 200
    fake.fail = ToolError("UPSTREAM_TIMEOUT", "demo_stdio 连接超时")
    r = admin.post(f"{URL}/demo_stdio/sync", headers={"Idempotency-Key": "boom"})
    assert r.status_code == 200 and r.json()["ok"] is False
    detail = admin.get(f"{URL}/demo_stdio").json()
    assert detail["last_sync_result"] == "error" and "超时" in detail["last_sync_error"]
    assert len(_tools(installed)) == 2


def test_sync_and_test_404_permission_and_remote_allowlist(admin, installed):
    _fake(installed)
    assert admin.post(f"{URL}/ghost/sync").status_code == 404
    assert admin.post(f"{URL}/ghost/test").status_code == 404
    role = _role(admin, "tool_only2", ["ops.tool.manage"])
    _user(admin, "toolonly2", [role["id"]])
    other = login(TestClient(installed.app), "toolonly2", VIEWER_PASS)
    assert other.post(f"{URL}/demo_stdio/sync").status_code == 403
    assert other.post(f"{URL}/demo_stdio/test").status_code == 403
    # 白名单后来被清空：远程连接不得再被探测
    set_allowlist(admin, ["https://mcp.example.internal"])
    assert admin.post(URL, json=http_body()).status_code == 200
    set_allowlist(admin, ["https://other.example.internal"])
    assert admin.post(f"{URL}/demo_http/test").status_code == 422
