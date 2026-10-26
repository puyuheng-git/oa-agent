"""迁移：0002 → 0003 回填 failed_node；可降级。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command

from oa_agent.db.migrate import alembic_config, revision_status


def _run(engine, rev: str, down: bool = False) -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        (command.downgrade if down else command.upgrade)(cfg, rev)


def test_0003_backfills_failed_node(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.sqlite'}")
    _run(engine, "0002_p1_run_event")
    with engine.begin() as conn:
        for run_id, code in (("run_a", "UPSTREAM_UNAVAILABLE"), ("run_b", None)):
            conn.execute(sa.text(
                "INSERT INTO agent_run (run_id, thread_id, tenant_id, oa, channel, agent_id, workflow_id,"
                " workflow_version, run_status, started_at, error_code, tool_call_count, model_call_count)"
                " VALUES (:r, 't', 'dscpa', 'zhangsan', 'oa_web', 'a', 'w', '1', 'failed', '2026-10-09 00:00:00',"
                " :c, 0, 0)"), {"r": run_id, "c": code})
            conn.execute(sa.text(
                "INSERT INTO agent_run_event (event_id, run_id, seq, event_type, node_name, occurred_at, retry_count)"
                " VALUES (:e, :r, 1, 'run_end', 'call_tool', '2026-10-09 00:00:01', 0)"),
                {"e": f"evt_{run_id}", "r": run_id})
    _run(engine, "head")
    assert revision_status(engine)["up_to_date"]
    with engine.connect() as conn:
        rows = dict(conn.execute(sa.text("SELECT run_id, failed_node FROM agent_run")).all())
    assert rows == {"run_a": "call_tool", "run_b": None}

    _run(engine, "0002_p1_run_event", down=True)
    with engine.connect() as conn:
        cols = {c["name"] for c in sa.inspect(conn).get_columns("agent_run")}
    assert "failed_node" not in cols


def test_restart_applies_pending_migrations(installed, settings):
    """已安装实例升级代码后直接启动 uvicorn：启动时自动补跑迁移，不依赖启动脚本。"""
    from fastapi.testclient import TestClient

    from oa_agent.main import create_app

    engine = installed.app.state.runtime.db_engine
    _run(engine, "0003_p2_run_failed_node", down=True)
    assert not revision_status(engine)["up_to_date"]
    installed.__exit__(None, None, None)

    with TestClient(create_app(settings)) as c:
        rt = c.app.state.runtime
        assert revision_status(rt.db_engine)["up_to_date"]
        assert "query_my_travel_expense_list" in rt.engine.registry.names()
        assert c.get("/readyz").json()["database"]["status"] == "ok"


def test_head_matches_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from oa_agent.db.models import Base

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'h.sqlite'}")
    _run(engine, "head")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    tables = [d for d in diff if d[0] in ("add_table", "remove_table", "add_column", "remove_column")]
    assert tables == []
