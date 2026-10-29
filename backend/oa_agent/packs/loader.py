"""Domain Pack 目录扫描与引用文件校验。"""

from __future__ import annotations

import logging
from pathlib import Path

from oa_agent.packs.schema import PackManifest, load_manifest
from oa_agent.settings import REPO_ROOT

log = logging.getLogger(__name__)

_DEFAULT_PACKS_ROOT = REPO_ROOT / "packs"


def discover_pack_entries(root: Path | None = None) -> list[tuple[PackManifest, Path]]:
    """扫描 root，返回 ``(manifest, pack_dir)``；无效目录记录日志并跳过。"""
    packs_root = root if root is not None else _DEFAULT_PACKS_ROOT
    if not packs_root.is_dir():
        log.warning("pack 根目录不存在或不是目录：%s", packs_root)
        return []

    entries: list[tuple[PackManifest, Path]] = []
    for entry in sorted(packs_root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        manifest_path = entry / "pack.yaml"
        if not manifest_path.is_file():
            continue
        try:
            entries.append((load_manifest(manifest_path), entry))
        except ValueError as exc:
            log.warning("跳过无效 pack %s：%s", entry.name, exc)
    return entries


def discover_packs(root: Path | None = None) -> list[PackManifest]:
    """扫描 root 下各子目录中的 pack.yaml，加载合法 manifest；无效目录记录日志并跳过。"""
    return [manifest for manifest, _ in discover_pack_entries(root)]


def _check_ref(pack_dir: Path, field: str, rel: str) -> str | None:
    target = (pack_dir / rel).resolve()
    if not target.is_file():
        return f"{field}: 文件不存在 {rel!r}（解析为 {target}）"
    return None


def validate_pack_files(manifest: PackManifest, pack_dir: Path) -> list[str]:
    """校验 manifest 引用的 skills/openapi/contracts/rules 相对 pack_dir 均可读且为文件。"""
    errors: list[str] = []
    for rel in manifest.skills:
        err = _check_ref(pack_dir, "skills", rel)
        if err:
            errors.append(err)
    for rel in manifest.tools_openapi:
        err = _check_ref(pack_dir, "tools_openapi", rel)
        if err:
            errors.append(err)
    for rel in manifest.write_contracts:
        err = _check_ref(pack_dir, "write_contracts", rel)
        if err:
            errors.append(err)
    if manifest.rules is not None:
        err = _check_ref(pack_dir, "rules", manifest.rules)
        if err:
            errors.append(err)
    return errors
