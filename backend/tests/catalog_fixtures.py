"""测试用 Catalog 夹具：替代已移除的仓库根 openapi/ / skills/ 首次导入。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "catalog"
OPENAPI_DIR = FIXTURES / "openapi"
SKILLS_DIR = FIXTURES / "skills"


def seed_catalog(client: TestClient) -> None:
    """安装后写入行程报销等业务 Tool/Skill，供依赖存量能力的集成测试使用。"""
    rt = client.app.state.runtime
    catalog = rt.engine.catalog
    catalog.openapi_dir = OPENAPI_DIR
    catalog.skills_dir = SKILLS_DIR
    with rt.session() as db, db.begin():
        catalog.sync_tools(db, "test-seed")
        db.flush()
        catalog.sync_skills(db, "test-seed")
    rt.engine.reload_catalog()
