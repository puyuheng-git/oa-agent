"""Task 9：BUILTIN_CATALOG 与启动 upsert（规格 §5.1）。"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

pytest_plugins = ("tests.test_chat",)

EXPECTED = {
    "sys.time": ("low", True), "sys.calc": ("low", True), "sys.export": ("medium", True),
    "sys.memory": ("medium", True), "sys.cron": ("high", False), "sys.http": ("high", False),
    "sys.web_search": ("high", False), "sys.fs_read": ("high", False), "sys.fs_write": ("high", False),
}


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def _builtin_rows(rt) -> dict:
    from oa_agent.db.models import Tool

    with rt.session() as db:
        rows = db.scalars(sa.select(Tool).where(Tool.tenant_id == rt.tenant_id, Tool.kind == "builtin")).all()
        return {r.name: r for r in rows}


def test_tool_name_mapping():
    from oa_agent.executor.builtin_catalog import tool_name

    assert tool_name("sys.time") == "builtin.time"
    assert tool_name("sys.web_search") == "builtin.web_search"
    assert tool_name("sys.http") == "builtin.http"
    with pytest.raises(ValueError):
        tool_name("time")


def test_catalog_covers_spec_ids_and_defaults():
    from oa_agent.executor.builtin_catalog import BUILTIN_CATALOG

    assert {d.builtin_id: (d.risk_level, d.enabled) for d in BUILTIN_CATALOG} == EXPECTED
    assert len({d.builtin_id for d in BUILTIN_CATALOG}) == len(BUILTIN_CATALOG)


def test_startup_upserts_builtin_tools(rt):
    rows = _builtin_rows(rt)
    assert "builtin.time" in rows
    assert rows["builtin.time"].builtin_id == "sys.time"
    assert rows["builtin.time"].enabled is True
    assert rows["builtin.http"].builtin_id == "sys.http"
    assert rows["builtin.http"].enabled is False
    assert set(rows) == {f"builtin.{k[4:]}" for k in EXPECTED}
    reg = rt.engine.registry
    assert reg.get("builtin.time") is not None and reg.get("builtin.time").builtin_id == "sys.time"
    assert reg.get("builtin.http") is None  # 默认关闭：不进运行时注册表


def test_ensure_is_idempotent_and_keeps_admin_changes(rt):
    from oa_agent.db.models import Tool
    from oa_agent.executor.builtin_catalog import ensure_builtin_tools

    with rt.session() as db, db.begin():
        db.scalar(sa.select(Tool).where(Tool.name == "builtin.time")).enabled = False
        db.scalar(sa.select(Tool).where(Tool.name == "builtin.http")).enabled = True
        ensure_builtin_tools(db, rt.tenant_id)
    with rt.session() as db, db.begin():
        assert ensure_builtin_tools(db, rt.tenant_id) == 0
    rows = _builtin_rows(rt)
    assert len(rows) == len(EXPECTED)
    assert rows["builtin.time"].enabled is False
    assert rows["builtin.http"].enabled is True


def test_ensure_restores_deleted_row_with_defaults(rt):
    from oa_agent.db.models import Tool
    from oa_agent.executor.builtin_catalog import ensure_builtin_tools

    with rt.session() as db, db.begin():
        db.execute(sa.delete(Tool).where(Tool.name == "builtin.calc"))
    with rt.session() as db, db.begin():
        assert ensure_builtin_tools(db, rt.tenant_id) == 1
    assert _builtin_rows(rt)["builtin.calc"].enabled is True


def test_sync_refresh_reensures(rt):
    from oa_agent.db.models import Tool

    with rt.session() as db, db.begin():
        db.execute(sa.delete(Tool).where(Tool.name == "builtin.export"))
    with rt.session() as db, db.begin():
        rt.engine.catalog.sync_tools(db, "tester")
    assert "builtin.export" in _builtin_rows(rt)
