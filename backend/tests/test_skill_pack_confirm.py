"""个人 Skill 创建/更新：确认前不落盘，确认后写入。"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from oa_agent.db.models import (
    Base,
    InterventionTask,
    SkillMarketListing,
    SkillPack,
    SkillPackVersion,
    UserSkillPack,
)
from oa_agent.executor.builtin_runtime import BuiltinRuntime
from oa_agent.executor.executor import Identity, ToolError
from oa_agent.executor.registry import ToolSpec
from oa_agent.runtime import confirmation
from oa_agent.skills import service as skill_packs


SKILL_MD = """---
name: leave-tips
description: Use when the employee asks about leave balance or leave process.
---

# Leave tips

1. Check balance first.
"""


def _session(tmp_path: Path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            SkillPack.__table__,
            SkillPackVersion.__table__,
            UserSkillPack.__table__,
            SkillMarketListing.__table__,
            InterventionTask.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _spec(builtin_id: str) -> ToolSpec:
    short = builtin_id.removeprefix("sys.")
    return ToolSpec(
        name=f"builtin.{short}",
        method="POST",
        path=f"/builtin/{short}",
        version="1",
        schema_hash="test",
        risk_level="medium",
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


def test_skill_create_issues_confirm_without_writing(tmp_path: Path):
    SessionLocal = _session(tmp_path)
    rt = BuiltinRuntime(tenant_id="t1", session_factory=SessionLocal, data_dir=tmp_path)
    identity = Identity(oa="u1", authorization="Bearer x", run_id="run_skill_1")

    out = rt.call(_spec("sys.skill_create"), {"skill_md": SKILL_MD}, identity=identity)
    assert out["pending_confirmation"] is True
    assert out["task_id"]
    assert out["token"]
    assert out["preview"]["name"] == "leave-tips"

    with SessionLocal() as db:
        packs = list(db.scalars(select(SkillPack).where(SkillPack.tenant_id == "t1")))
        assert packs == []
        task = db.scalar(select(InterventionTask).where(InterventionTask.task_id == out["task_id"]))
        assert task is not None
        payload = confirmation.payload_from_binding(task)
        assert payload and payload["kind"] == "skill_pack"


def test_apply_skill_pack_payload_creates_after_confirm(tmp_path: Path):
    SessionLocal = _session(tmp_path)
    with SessionLocal() as db, db.begin():
        applied = skill_packs.apply_skill_pack_payload(
            db,
            tenant_id="t1",
            oa="u1",
            data_dir=tmp_path,
            payload={
                "kind": "skill_pack",
                "action": "create",
                "skill_md": SKILL_MD,
                "name": "leave-tips",
            },
        )
        assert applied["name"] == "leave-tips"
        assert applied["action"] == "create"

    with SessionLocal() as db:
        pack = skill_packs.get_pack_by_name(db, tenant_id="t1", name="leave-tips")
        assert pack is not None
        assert pack.owner_oa == "u1"
        lib = skill_packs.list_user_library(db, tenant_id="t1", oa="u1")
        assert any(i["name"] == "leave-tips" for i in lib)


def test_skill_update_requires_owned_user_pack(tmp_path: Path):
    SessionLocal = _session(tmp_path)
    with SessionLocal() as db, db.begin():
        skill_packs.create_user_pack(
            db, tenant_id="t1", oa="u1", data_dir=tmp_path, skill_md=SKILL_MD,
        )

    rt = BuiltinRuntime(tenant_id="t1", session_factory=SessionLocal, data_dir=tmp_path)
    identity = Identity(oa="u1", authorization="Bearer x", run_id="run_skill_2")
    edited = SKILL_MD.replace("Check balance first.", "Check balance, then ask HR.")
    out = rt.call(
        _spec("sys.skill_update"),
        {"name": "leave-tips", "skill_md": edited},
        identity=identity,
    )
    assert out["pending_confirmation"] is True
    assert out["preview"]["action"] == "update"
    assert out["preview"]["pack_id"]

    other = Identity(oa="u2", authorization="Bearer y", run_id="run_skill_3")
    with pytest.raises(ToolError) as exc:
        rt.call(
            _spec("sys.skill_update"),
            {"name": "leave-tips", "skill_md": edited},
            identity=other,
        )
    assert exc.value.code == "FORBIDDEN"


def test_ensure_system_packs_does_not_seed_skill_creator(tmp_path: Path):
    SessionLocal = _session(tmp_path)
    with SessionLocal() as db, db.begin():
        n = skill_packs.ensure_system_skill_packs(db, tenant_id="t1", data_dir=tmp_path)
        assert n >= 1
    with SessionLocal() as db:
        names = {
            p.name
            for p in db.scalars(select(SkillPack).where(SkillPack.tenant_id == "t1")).all()
        }
        assert "oa-skill-persist" in names
        assert "skill-creator" not in names
