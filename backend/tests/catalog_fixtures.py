"""测试用 Catalog 夹具：替代已移除的仓库根 openapi/ / skills/ 首次导入。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "catalog"
OPENAPI_DIR = FIXTURES / "openapi"
SKILLS_DIR = FIXTURES / "skills"


def seed_catalog(client: TestClient) -> None:
    """安装后写入行程报销等业务 Tool/Skill，供依赖存量能力的集成测试使用。"""
    import sqlalchemy as sa

    from oa_agent.db.models import Tool
    from oa_agent.executor.catalog import iter_skill_tool_bindings

    rt = client.app.state.runtime
    catalog = rt.engine.catalog
    catalog.openapi_dir = OPENAPI_DIR
    catalog.skills_dir = SKILLS_DIR
    with rt.session() as db, db.begin():
        catalog.sync_tools(db, "test-seed")
        db.flush()
        catalog.sync_skills(db, "test-seed")
        # 夹具是已经绑定并启用的存量目录；管理端新建仍保持停用
        bound = set(iter_skill_tool_bindings(db, rt.tenant_id))
        rows = db.scalars(sa.select(Tool).where(Tool.tenant_id == rt.tenant_id)).all()
        for tool in rows:
            if (tool.kind or "office") == "builtin" or tool.name not in bound:
                continue
            tool.enabled = True
        catalog.revalidate_skills(db)
    rt.engine.reload_catalog()
