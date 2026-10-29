"""M3 Domain Pack — manifest 加载与 PackRegistry 启停。"""

from pathlib import Path

import pytest

from oa_agent.config.schema import GROUPS, default
from oa_agent.packs.loader import discover_packs, validate_pack_files
from oa_agent.packs.registry import PackRegistry
from oa_agent.packs.schema import load_manifest
from oa_agent.packs.state import load_disabled_ids, normalize_disabled_ids, save_disabled_ids
from oa_agent.settings import REPO_ROOT

OA_TRAVEL_MANIFEST = REPO_ROOT / "packs" / "oa_travel" / "pack.yaml"


def test_load_oa_travel_manifest():
    manifest = load_manifest(OA_TRAVEL_MANIFEST)
    assert manifest.id == "oa_travel"
    assert manifest.display_name == "行程报销"
    assert manifest.version == "1"
    assert manifest.connectors == ("office",)
    assert manifest.default_enabled is True
    assert manifest.skills == ("../../skills/travel_expense_query.yaml",)
    assert manifest.tools_openapi == ("../../openapi/travel_expense.yaml",)
    assert manifest.write_contracts == ("../../contracts/travel_expense_write.yaml",)
    assert manifest.rules == "rules/intent.yaml"
    assert len(manifest.workflows) == 1
    wf = manifest.workflows[0]
    assert wf["id"] == "travel_reimburse_submit"
    assert wf["kind"] == "write"
    assert wf["graph"] == "oa_agent.runtime.graphs.travel_reimburse_submit"


def test_load_manifest_missing_id(tmp_path: Path):
    bad = tmp_path / "pack.yaml"
    bad.write_text("display_name: x\nversion: '1'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少必填字段 id"):
        load_manifest(bad)


def test_discover_packs_finds_oa_travel():
    manifests = discover_packs(REPO_ROOT / "packs")
    ids = {m.id for m in manifests}
    assert "oa_travel" in ids


def test_validate_pack_files_oa_travel_no_errors():
    manifest = load_manifest(OA_TRAVEL_MANIFEST)
    pack_dir = OA_TRAVEL_MANIFEST.parent
    assert validate_pack_files(manifest, pack_dir) == []


def test_validate_pack_files_broken_refs(tmp_path: Path):
    pack_dir = tmp_path / "broken"
    pack_dir.mkdir()
    manifest_path = pack_dir / "pack.yaml"
    manifest_path.write_text(
        "\n".join(
            [
                "id: broken",
                "display_name: x",
                'version: "1"',
                "skills: [missing/skill.yaml]",
                "tools_openapi: []",
                "write_contracts: []",
            ]
        ),
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_path)
    errors = validate_pack_files(manifest, pack_dir)
    assert errors
    assert any("skills" in e for e in errors)


def test_packs_setting_schema_has_disabled_ids():
    assert "packs" in GROUPS
    assert default("packs", "disabled_ids") == []


def test_normalize_and_load_disabled_ids_from_override():
    assert normalize_disabled_ids(None) == []
    assert normalize_disabled_ids(["oa_travel", "x", "oa_travel"]) == ["oa_travel", "x"]
    assert load_disabled_ids({"disabled_ids": ["oa_travel"]}) == ["oa_travel"]
    assert load_disabled_ids({}) == []


def test_save_disabled_ids_updates_override_dict():
    store: dict = {}
    save_disabled_ids(["oa_travel"], store)
    assert store["disabled_ids"] == ["oa_travel"]


def test_pack_registry_default_enables_oa_travel():
    manifests = discover_packs(REPO_ROOT / "packs")
    registry = PackRegistry(manifests)
    assert registry.is_enabled("oa_travel") is True
    enabled_ids = {m.id for m in registry.enabled_manifests()}
    assert "oa_travel" in enabled_ids


def test_pack_registry_disabled_ids_disables_oa_travel():
    manifests = discover_packs(REPO_ROOT / "packs")
    registry = PackRegistry(manifests, disabled_ids=["oa_travel"])
    assert registry.is_enabled("oa_travel") is False
    enabled_ids = {m.id for m in registry.enabled_manifests()}
    assert "oa_travel" not in enabled_ids


def test_pack_registry_set_disabled_ids_and_reload():
    manifests = discover_packs(REPO_ROOT / "packs")
    registry = PackRegistry(manifests)
    assert registry.is_enabled("oa_travel") is True

    registry.set_disabled_ids(["oa_travel"])
    assert registry.is_enabled("oa_travel") is False
    assert "oa_travel" not in {m.id for m in registry.enabled_manifests()}

    registry.reload(manifests=manifests, disabled_ids=[])
    assert registry.is_enabled("oa_travel") is True
