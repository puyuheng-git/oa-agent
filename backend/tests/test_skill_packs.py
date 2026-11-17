"""Agent Skill 包：解析、落盘、GitHub zip 提取。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from oa_agent.skills.github_import import extract_skill_dirs, parse_github_url
from oa_agent.skills.parse import SkillMdError, parse_skill_md
from oa_agent.skills.pack_store import save_pack_version, validate_bundle
from oa_agent.db.models import SkillPack


def test_parse_skill_md_ok():
    text = """---
name: xlsx
description: Use when working with spreadsheets
---

# XLSX
hello
"""
    parsed = parse_skill_md(text)
    assert parsed["name"] == "xlsx"
    assert "spreadsheets" in parsed["description"]
    assert "# XLSX" in parsed["body"]


def test_parse_skill_md_rejects_bad_name():
    with pytest.raises(SkillMdError):
        parse_skill_md("---\nname: Bad_Name\ndescription: x\n---\n\nbody")


def test_validate_bundle_requires_skill_md():
    with pytest.raises(SkillMdError):
        validate_bundle({"scripts/a.py": b"print(1)"})


def test_extract_skill_dirs_from_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "repo-main/skills/xlsx/SKILL.md",
            "---\nname: xlsx\ndescription: spreadsheet skill for excel files\n---\n\n# xlsx\n",
        )
        zf.writestr("repo-main/skills/xlsx/scripts/hi.py", "print('hi')\n")
        zf.writestr(
            "repo-main/skills/pdf/SKILL.md",
            "---\nname: pdf\ndescription: pdf documents\n---\n\n# pdf\n",
        )
    packs = extract_skill_dirs(buf.getvalue(), only_paths=["skills/xlsx", "skills/pdf"])
    names = {parse_skill_md(p["SKILL.md"].decode())["name"] for _, p in packs}
    assert names == {"xlsx", "pdf"}
    xlsx_files = next(f for d, f in packs if "xlsx" in d)
    assert "scripts/hi.py" in xlsx_files


def test_parse_github_url():
    info = parse_github_url("https://github.com/anthropics/skills/tree/main/skills/xlsx")
    assert info["owner"] == "anthropics"
    assert info["repo"] == "skills"
    assert info["ref"] == "main"
    assert info["subpath"] == "skills/xlsx"


def test_save_pack_version_roundtrip(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from oa_agent.db.models import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        SkillPack.__table__,
        __import__("oa_agent.db.models", fromlist=["SkillPackVersion"]).SkillPackVersion.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        pack = SkillPack(tenant_id="t1", name="tmp", kind="user", source="editor", created_by="u")
        db.add(pack)
        db.flush()
        files = {
            "SKILL.md": b"---\nname: demo-skill\ndescription: demo description here\n---\n\n# Demo\n",
            "scripts/run.py": b"print(1)\n",
        }
        version = save_pack_version(db, pack=pack, files=files, data_dir=tmp_path, operator="u")
        db.commit()
        assert pack.name == "demo-skill"
        assert version.storage_path
        assert (tmp_path / version.storage_path / "SKILL.md").is_file()
        assert (tmp_path / version.storage_path / "scripts" / "run.py").is_file()


def test_list_user_library_excludes_system_but_prompt_still_loads(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from oa_agent.db.models import Base, SkillPackVersion, UserSkillPack
    from oa_agent.skills import service as packs

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        SkillPack.__table__, SkillPackVersion.__table__, UserSkillPack.__table__,
        __import__("oa_agent.db.models", fromlist=["SkillMarketListing"]).SkillMarketListing.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        n = packs.ensure_system_skill_packs(db, tenant_id="t1", data_dir=tmp_path)
        assert n >= 1
        db.commit()
        created = packs.create_user_pack(
            db, tenant_id="t1", oa="u1", data_dir=tmp_path,
            skill_md="---\nname: mine\ndescription: my personal skill desc\n---\n\n# Mine\n",
        )
        db.commit()
        items = packs.list_user_library(db, tenant_id="t1", oa="u1")
        names = {i["name"] for i in items}
        # 对话页「我的 Skill」不展示后台系统包
        assert "skill-creator" not in names
        assert "mine" in names
        assert created.name == "mine"
        # 系统包仍注入运行时提示词
        enabled = packs.enabled_packs_for(db, tenant_id="t1", oa="u1")
        kinds = {p.name: p.kind for p in enabled}
        assert kinds.get("skill-creator") == "system"
        assert kinds.get("mine") == "user"


def test_describe_skill_packs_all_enabled_full_text():
    from oa_agent.runtime.graphs.oa_assistant import _describe_skill_packs
    from oa_agent.skills.service import SkillPackState

    text = _describe_skill_packs([
        SkillPackState(
            id=1, name="skill-creator", display_name="Skill 创建助手",
            description="create skills", kind="system", enabled=True,
            skill_md="---\nname: skill-creator\ndescription: x\n---\n\n# BODY_MARKER\n",
        ),
        SkillPackState(
            id=2, name="pdf", display_name="PDF", description="handle pdf files",
            kind="system", enabled=True, skill_md="# PDF_BODY\n",
        ),
        SkillPackState(
            id=3, name="mine", display_name="Mine", description="personal",
            kind="user", enabled=True, skill_md="# USER_BODY\n",
        ),
    ], message="请处理这个 pdf")
    assert "系统内置 Skill" in text
    assert "BODY_MARKER" in text
    assert "PDF_BODY" in text
    assert "员工个人" in text
    assert "USER_BODY" in text  # 已启用的个人包默认全文注入
    # pdf 相关问题时 pdf 包应排在前面
    assert text.index("PDF_BODY") < text.index("BODY_MARKER")
