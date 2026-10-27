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


# ---------------- Task 2：ToolSpec.kind 与注册条件分叉 ----------------

def _schema(**over) -> dict:
    base = {
        "name": "travel_probe", "method": "GET", "path": "/x", "summary": "s", "description": "d",
        "risk_level": "low", "requires_confirmation": False, "timeout_seconds": 10,
        "inject_identity_fields": [], "top_level_fields": [], "query_params_field": None,
        "model_params": {}, "result": {"kind": "object", "fields": ["a"], "labels": {}, "list_columns": []},
    }
    base.update(over)
    return base


def _tool(**over):
    from types import SimpleNamespace

    base = dict(kind="office", enabled=True, spec_enabled=True, risk_level="low", requires_confirmation=False,
                builtin_id=None, mcp_server_id=None, mcp_tool_name=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_to_tool_spec_carries_kind_office():
    from oa_agent.executor.catalog import to_tool_spec

    spec = to_tool_spec(_schema(), "1.0", 1, "abc" * 20)
    assert spec.kind == "office"
    assert spec.builtin_id is None and spec.mcp_server_id is None and spec.mcp_tool_name is None
    assert spec.sandbox_policy == {}


def test_to_tool_spec_carries_extension_fields():
    from oa_agent.executor.catalog import to_tool_spec

    spec = to_tool_spec(_schema(), "1.0", 1, "abc" * 20, kind="mcp", mcp_server_id=7, mcp_tool_name="echo",
                        sandbox_policy={"network": False})
    assert (spec.kind, spec.mcp_server_id, spec.mcp_tool_name) == ("mcp", 7, "echo")
    assert spec.sandbox_policy == {"network": False}


def test_registration_blockers_office_unchanged():
    from oa_agent.executor.catalog import registration_blockers

    assert registration_blockers(_tool(), True, "GET") == []
    assert registration_blockers(_tool(risk_level="high"), True, "GET")
    assert registration_blockers(_tool(), True, "POST")
    assert registration_blockers(_tool(), False, "GET")


def test_registration_blockers_builtin_and_mcp():
    from oa_agent.executor.catalog import registration_blockers

    # builtin / mcp 不要求 GET、低风险、免确认、规范启用、版本
    assert registration_blockers(_tool(kind="builtin", builtin_id="sys.time", spec_enabled=False,
                                       risk_level="high", requires_confirmation=True), False) == []
    assert registration_blockers(_tool(kind="builtin", builtin_id="sys.time", enabled=False), False)
    assert registration_blockers(_tool(kind="builtin", builtin_id=None), False)
    assert registration_blockers(_tool(kind="mcp", mcp_server_id=3, mcp_tool_name="echo"), False) == []
    assert registration_blockers(_tool(kind="mcp", mcp_server_id=None, mcp_tool_name="echo"), False)
    assert registration_blockers(_tool(kind="mcp", mcp_server_id=3, mcp_tool_name=None), False)
    assert registration_blockers(_tool(kind="mcp", mcp_server_id=3, mcp_tool_name="echo", enabled=False), False)


def test_registration_blockers_unknown_kind():
    from oa_agent.executor.catalog import registration_blockers

    assert registration_blockers(_tool(kind="weird"), True, "GET")


def test_load_registry_by_kind(rt):
    from oa_agent.db.models import Tool

    with rt.session() as db, db.begin():
        db.add_all([
            Tool(tenant_id=rt.tenant_id, name="b_ok", kind="builtin", builtin_id="sys.time", summary="时间",
                 sandbox_policy_json={"network": False}),
            Tool(tenant_id=rt.tenant_id, name="b_off", kind="builtin", builtin_id="sys.x", enabled=False),
            Tool(tenant_id=rt.tenant_id, name="m_ok", kind="mcp", mcp_server_id=1, mcp_tool_name="echo"),
            Tool(tenant_id=rt.tenant_id, name="m_noserver", kind="mcp", mcp_tool_name="echo"),
            Tool(tenant_id=rt.tenant_id, name="w_unknown", kind="weird", builtin_id="x"),
        ])
    with rt.session() as db:
        reg = rt.engine.catalog.load_registry(db)
    assert reg.get("b_ok").kind == "builtin" and reg.get("b_ok").builtin_id == "sys.time"
    assert reg.get("b_ok").sandbox_policy == {"network": False}
    assert reg.get("m_ok").kind == "mcp" and reg.get("m_ok").mcp_server_id == 1
    assert reg.get("m_ok").mcp_tool_name == "echo"
    for name in ("b_off", "m_noserver", "w_unknown"):
        assert reg.get(name) is None
    assert reg.get("query_my_travel_expense_list").kind == "office"
