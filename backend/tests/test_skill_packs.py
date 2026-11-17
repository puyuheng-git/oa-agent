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
        # 短种子不得再写入 skill-creator，以免覆盖 Anthropic 包；改为 oa-skill-persist
        seeded = packs.enabled_packs_for(db, tenant_id="t1", oa="u1")
        assert any(p.name == "oa-skill-persist" and p.kind == "system" for p in seeded)
        assert all(p.name != "skill-creator" for p in seeded)
        created = packs.create_user_pack(
            db, tenant_id="t1", oa="u1", data_dir=tmp_path,
            skill_md="---\nname: mine\ndescription: my personal skill desc\n---\n\n# Mine\n",
        )
        db.commit()
        items = packs.list_user_library(db, tenant_id="t1", oa="u1")
        names = {i["name"] for i in items}
        # 对话页「我的 Skill」不展示后台系统包
        assert "oa-skill-persist" not in names
        assert "mine" in names
        assert created.name == "mine"
        # 系统包仍注入运行时提示词
        enabled = packs.enabled_packs_for(db, tenant_id="t1", oa="u1")
        kinds = {p.name: p.kind for p in enabled}
        assert kinds.get("oa-skill-persist") == "system"
        assert kinds.get("mine") == "user"


def test_describe_skill_packs_l1_catalog_only():
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
        SkillPackState(
            id=4, name="slash-only", display_name="Slash", description="slash only pack",
            kind="user", enabled=True, disable_model_invocation=True, user_invocable=True,
            skill_md="# HIDDEN_BODY\n",
        ),
    ], message="请处理这个 pdf")
    assert "<available_skills>" in text
    assert 'name="pdf"' in text
    assert "handle pdf files" in text
    assert "BODY_MARKER" not in text
    assert "PDF_BODY" not in text
    assert "USER_BODY" not in text
    assert "HIDDEN_BODY" not in text
    assert 'name="slash-only"' not in text  # disable-model-invocation 不进模型目录
    # pdf 相关问题时 pdf 包应排在目录前面
    assert text.index('name="pdf"') < text.index('name="skill-creator"')
    assert "builtin.skill" in text
    assert "builtin.skill_create" in text


def test_parse_dsh_invocation_flags():
    from oa_agent.skills.parse import parse_skill_md, truncate_catalog_description

    parsed = parse_skill_md(
        "---\nname: secret-pack\ndescription: only via slash\n"
        "disable-model-invocation: true\nuser-invocable: yes\n---\n\n# Body\n"
    )
    assert parsed["disable_model_invocation"] is True
    assert parsed["user_invocable"] is True
    long_desc = "x" * 600
    truncated = truncate_catalog_description(long_desc)
    assert len(truncated) <= 500
    assert truncated.endswith("…")


def test_skill_read_path_traversal_rejected(tmp_path: Path):
    from oa_agent.errors import AppError
    from oa_agent.skills.service import assert_skill_read_relpath, read_skill_resource

    with pytest.raises(AppError):
        assert_skill_read_relpath("../etc/passwd")
    with pytest.raises(AppError):
        assert_skill_read_relpath("scripts/run.py")
    root = tmp_path / "pack"
    (root / "references").mkdir(parents=True)
    (root / "references" / "guide.md").write_text("hello guide", encoding="utf-8")
    out = read_skill_resource(root, "references/guide.md")
    assert out["content"] == "hello guide"


def _builtin_spec(builtin_id: str) -> "ToolSpec":
    from oa_agent.executor.registry import ToolSpec

    short = builtin_id.removeprefix("sys.")
    return ToolSpec(
        name=f"builtin.{short}",
        method="POST",
        path=f"/builtin/{short}",
        version="1",
        schema_hash="test",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=30.0,
        inject_identity_fields=(),
        top_level_fields=(),
        query_params_field=None,
        model_params={},
        result_kind="text",
        result_fields=("text",),
        summary=builtin_id,
        builtin_id=builtin_id,
        kind="builtin",
        sandbox_policy={},
    )


def test_resolve_slash_and_skill_load(tmp_path: Path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from oa_agent.db.models import Base, SkillMarketListing, SkillPack, SkillPackVersion, UserSkillPack
    from oa_agent.executor.builtin_runtime import BuiltinRuntime
    from oa_agent.executor.executor import Identity, ToolError
    from oa_agent.skills.pack_store import save_pack_version
    from oa_agent.skills.service import enabled_packs_for, resolve_slash_skills

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        SkillPack.__table__, SkillPackVersion.__table__, UserSkillPack.__table__,
        SkillMarketListing.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        pack = SkillPack(tenant_id="t1", name="pdf", kind="system", source="test",
                         enabled_default=True, created_by="sys")
        db.add(pack)
        db.flush()
        files = {
            "SKILL.md": (
                b"---\nname: pdf\ndescription: pdf docs\n---\n\n# PDF_INSTRUCTIONS\n"
            ),
            "references/a.md": b"ref-a",
        }
        save_pack_version(db, pack=pack, files=files, data_dir=tmp_path, operator="sys")
        locked = SkillPack(
            tenant_id="t1", name="locked", kind="user", source="test",
            owner_oa="u1", created_by="u1",
        )
        db.add(locked)
        db.flush()
        save_pack_version(
            db, pack=locked, files={
                "SKILL.md": (
                    b"---\nname: locked\ndescription: slash only\n"
                    b"disable-model-invocation: true\n---\n\n# LOCKED_BODY\n"
                ),
            }, data_dir=tmp_path, operator="u1",
        )
        db.add(UserSkillPack(tenant_id="t1", oa="u1", pack_id=locked.id, enabled=True, origin="created"))
        db.commit()

        packs = enabled_packs_for(db, tenant_id="t1", oa="u1")
        slash = resolve_slash_skills(db, data_dir=tmp_path, packs=packs, message="please /pdf now")
        assert "PDF_INSTRUCTIONS" in slash
        assert '<skill_content name="pdf">' in slash

    rt = BuiltinRuntime(tenant_id="t1", session_factory=SessionLocal, data_dir=tmp_path)
    identity = Identity(oa="u1", authorization="Bearer x", run_id="run_skill_dsh")
    loaded = rt.call(_builtin_spec("sys.skill"), {"name": "pdf"}, identity=identity)
    assert "PDF_INSTRUCTIONS" in loaded["text"]

    with pytest.raises(ToolError):
        rt.call(_builtin_spec("sys.skill"), {"name": "locked"}, identity=identity)

    read_out = rt.call(
        _builtin_spec("sys.skill_read"),
        {"skill": "pdf", "path": "references/a.md"},
        identity=identity,
    )
    assert "ref-a" in read_out["content"]
