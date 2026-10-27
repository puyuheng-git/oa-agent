"""Tool.kind 扩展、agent_mcp_server 表与 ops.mcp.manage 权限种子。"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

pytest_plugins = ("tests.test_chat",)


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def test_tool_has_kind_default_office(rt):
    from oa_agent.db.models import Tool

    with rt.session() as db, db.begin():
        db.add(Tool(tenant_id=rt.tenant_id, name="kind_default_probe"))
    with rt.session() as db:
        tool = db.scalar(sa.select(Tool).where(Tool.name == "kind_default_probe"))
        assert tool is not None
        assert tool.kind == "office"
        assert tool.builtin_id is None
        assert tool.mcp_server_id is None
        assert tool.mcp_tool_name is None
        assert tool.sandbox_policy_json is None


def test_tool_extension_columns_roundtrip(rt):
    from oa_agent.db.models import Tool

    with rt.session() as db, db.begin():
        db.add(
            Tool(
                tenant_id=rt.tenant_id,
                name="sys.time",
                kind="builtin",
                builtin_id="sys.time",
                sandbox_policy_json={"network": False},
            )
        )
    with rt.session() as db:
        tool = db.scalar(sa.select(Tool).where(Tool.name == "sys.time"))
        assert tool.kind == "builtin"
        assert tool.builtin_id == "sys.time"
        assert tool.sandbox_policy_json == {"network": False}


def test_mcp_server_table_insert(rt):
    from oa_agent.db.models import McpServer

    with rt.session() as db, db.begin():
        db.add(
            McpServer(
                tenant_id=rt.tenant_id,
                name="demo",
                display_name="Demo",
                transport="http",
                url="https://mcp.example.internal/mcp",
                enabled=False,
                created_by="test",
            )
        )
    with rt.session() as db:
        row = db.scalar(sa.select(McpServer).where(McpServer.name == "demo"))
        assert row is not None and row.transport == "http"
        assert row.enabled is False
        assert row.timeout_seconds > 0
        assert row.tool_prefix == ""


def test_mcp_server_name_unique_per_tenant(rt):
    from sqlalchemy.exc import IntegrityError

    from oa_agent.db.models import McpServer

    def mk() -> McpServer:
        return McpServer(
            tenant_id=rt.tenant_id, name="dup", display_name="Dup",
            transport="stdio", command="npx", created_by="test",
        )

    with rt.session() as db, db.begin():
        db.add(mk())
    with pytest.raises(IntegrityError):
        with rt.session() as db, db.begin():
            db.add(mk())


def test_ops_mcp_manage_in_catalog_and_super_admin_seed(rt):
    from oa_agent.auth.perms import PERMISSIONS, SUPER_ADMIN_ROLE

    assert "ops.mcp.manage" in PERMISSIONS
    with rt.session() as db:
        count = db.scalar(
            sa.text(
                "SELECT COUNT(*) FROM agent_admin_role_perm rp "
                "JOIN agent_admin_role r ON r.id = rp.role_id "
                "WHERE r.code = :code AND rp.perm_code = 'ops.mcp.manage'"
            ),
            {"code": SUPER_ADMIN_ROLE},
        )
        assert count == 1
