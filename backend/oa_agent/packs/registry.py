"""Domain Pack 注册表：启停判定与已启用 manifest 聚合。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import yaml

from oa_agent.packs.loader import discover_pack_entries
from oa_agent.packs.rules_load import load_intent_rules
from oa_agent.packs.schema import PackManifest
from oa_agent.packs.state import (
    load_disabled_ids,
    load_enabled_ids,
    normalize_disabled_ids,
    normalize_enabled_ids,
)
from oa_agent.settings import REPO_ROOT

log = logging.getLogger(__name__)

_DEFAULT_PACKS_ROOT = REPO_ROOT / "packs"


def _skill_name_from_yaml(path: Path) -> str | None:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("读取 skill yaml 失败 %s：%s", path, exc)
        return None
    if not isinstance(doc, dict):
        return None
    name = doc.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def _skill_tool_names_from_yaml(path: Path) -> set[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("读取 skill yaml 失败 %s：%s", path, exc)
        return set()
    if not isinstance(doc, dict):
        return set()
    tools = doc.get("tools") or []
    if not isinstance(tools, list):
        return set()
    return {t.strip() for t in tools if isinstance(t, str) and t.strip()}


def _operation_ids_from_openapi(path: Path) -> set[str]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        log.warning("读取 openapi yaml 失败 %s：%s", path, exc)
        return set()
    if not isinstance(doc, dict):
        return set()
    out: set[str] = set()
    paths = doc.get("paths") or {}
    if not isinstance(paths, dict):
        return out
    for item in paths.values():
        if not isinstance(item, dict):
            continue
        for method_body in item.values():
            if not isinstance(method_body, dict):
                continue
            op = method_body.get("operationId")
            if isinstance(op, str) and op.strip():
                out.add(op.strip())
    return out


class PackRegistry:
    """内存中的 Pack 启停注册表。

    ``is_enabled(pack_id)``：disabled_ids 优先，其次 enabled_ids，最后取 manifest.default_enabled。
    未知 pack_id 视为未启用。
    """

    def __init__(
        self,
        manifests: list[PackManifest] | tuple[PackManifest, ...] | None = None,
        disabled_ids: list[str] | tuple[str, ...] | None = None,
        enabled_ids: list[str] | tuple[str, ...] | None = None,
        *,
        pack_dirs: dict[str, Path] | None = None,
    ) -> None:
        self._manifests: dict[str, PackManifest] = {}
        self._pack_dirs: dict[str, Path] = {}
        self._disabled_ids: list[str] = []
        self._enabled_ids: list[str] = []
        self.reload(
            manifests=manifests,
            disabled_ids=disabled_ids,
            enabled_ids=enabled_ids,
            pack_dirs=pack_dirs,
        )

    @classmethod
    def from_disk(
        cls,
        root: Path | None = None,
        disabled_ids: list[str] | tuple[str, ...] | None = None,
        enabled_ids: list[str] | tuple[str, ...] | None = None,
    ) -> PackRegistry:
        """扫描磁盘 packs 根目录，保留 id → (manifest, pack_dir)。"""
        packs_root = root if root is not None else _DEFAULT_PACKS_ROOT
        entries = discover_pack_entries(packs_root)
        manifests = [m for m, _ in entries]
        pack_dirs = {m.id: d for m, d in entries}
        return cls(
            manifests=manifests,
            disabled_ids=disabled_ids or [],
            enabled_ids=enabled_ids or [],
            pack_dirs=pack_dirs,
        )

    def reload(
        self,
        *,
        manifests: list[PackManifest] | tuple[PackManifest, ...] | None = None,
        disabled_ids: list[str] | tuple[str, ...] | None = None,
        enabled_ids: list[str] | tuple[str, ...] | None = None,
        settings: dict | None = None,
        pack_dirs: dict[str, Path] | None = None,
    ) -> None:
        """刷新 manifests 与/或启停覆盖列表。

        ``settings`` 为 packs 组值字典时，从中读取两份覆盖列表（覆盖显式参数）。
        """
        if manifests is not None:
            self._manifests = {m.id: m for m in manifests}
            if pack_dirs is None:
                # 仅刷新 manifests 时保留已有目录映射中仍存在的项
                self._pack_dirs = {
                    pid: path for pid, path in self._pack_dirs.items() if pid in self._manifests
                }
        if pack_dirs is not None:
            self._pack_dirs = {pid: Path(path) for pid, path in pack_dirs.items()}
        if settings is not None:
            self._disabled_ids = load_disabled_ids(settings)
            self._enabled_ids = load_enabled_ids(settings)
        elif disabled_ids is not None:
            self._disabled_ids = normalize_disabled_ids(disabled_ids)
        if settings is None and enabled_ids is not None:
            self._enabled_ids = normalize_enabled_ids(enabled_ids)

    @property
    def disabled_ids(self) -> list[str]:
        return list(self._disabled_ids)

    @property
    def enabled_ids(self) -> list[str]:
        return list(self._enabled_ids)

    def pack_dir(self, pack_id: str) -> Path | None:
        return self._pack_dirs.get(pack_id)

    def set_disabled_ids(self, disabled_ids: list[str] | tuple[str, ...]) -> None:
        """内存更新禁用列表（持久化由调用方 / state.save_disabled_ids 负责）。"""
        self._disabled_ids = normalize_disabled_ids(disabled_ids)

    def set_enabled_ids(self, enabled_ids: list[str] | tuple[str, ...]) -> None:
        """内存更新显式启用列表（持久化由调用方负责）。"""
        self._enabled_ids = normalize_enabled_ids(enabled_ids)

    def set_disabled(self, pack_id: str, disabled: bool = True) -> None:
        """启用或禁用单个 pack（仅改内存）。"""
        if disabled:
            self.set_enabled(pack_id, False)
        else:
            self.set_enabled(pack_id, True)

    def set_enabled(self, pack_id: str, enabled: bool = True) -> None:
        """按 manifest 默认值维护互斥的显式启用/禁用覆盖。"""
        disabled = [pid for pid in self._disabled_ids if pid != pack_id]
        explicit_enabled = [pid for pid in self._enabled_ids if pid != pack_id]
        manifest = self._manifests.get(pack_id)
        if enabled:
            if manifest is not None and not manifest.default_enabled:
                explicit_enabled.append(pack_id)
        else:
            disabled.append(pack_id)
        self._disabled_ids = disabled
        self._enabled_ids = explicit_enabled

    def is_enabled(self, pack_id: str) -> bool:
        manifest = self._manifests.get(pack_id)
        if manifest is None:
            return False
        if pack_id in self._disabled_ids:
            return False
        if pack_id in self._enabled_ids:
            return True
        return bool(manifest.default_enabled)

    def enabled_manifests(self) -> list[PackManifest]:
        return [m for m in self._manifests.values() if self.is_enabled(m.id)]

    def all_manifests(self) -> list[PackManifest]:
        return list(self._manifests.values())

    def aggregated_rule_tools(self) -> dict[str, str]:
        """合并已启用 Pack 的 ``rule_tools``；后加载的 pack 覆盖同名 key。"""
        merged: dict[str, str] = {}
        for manifest in self.enabled_manifests():
            if not manifest.rules:
                continue
            pack_dir = self._pack_dirs.get(manifest.id)
            if pack_dir is None:
                log.warning("pack %s 无 pack_dir，跳过 rules 加载", manifest.id)
                continue
            rules_path = pack_dir / manifest.rules
            try:
                loaded = load_intent_rules(rules_path)
            except ValueError as exc:
                log.warning("加载 pack %s rules 失败：%s", manifest.id, exc)
                continue
            rule_tools = loaded.get("rule_tools") or {}
            if isinstance(rule_tools, dict):
                merged.update(rule_tools)
        return merged

    def owned_skill_names(self, pack_id: str) -> set[str]:
        """解析 pack 声明的 skill yaml ``name`` 字段。"""
        manifest = self._manifests.get(pack_id)
        pack_dir = self._pack_dirs.get(pack_id)
        if manifest is None or pack_dir is None:
            return set()
        names: set[str] = set()
        for rel in manifest.skills:
            path = (pack_dir / rel).resolve()
            if not path.is_file():
                log.warning("pack %s skill 文件不存在：%s", pack_id, rel)
                continue
            name = _skill_name_from_yaml(path)
            if name:
                names.add(name)
        return names

    def owned_tool_names(self, pack_id: str) -> set[str]:
        """OpenAPI operationId 与 skill.tools 声明的 Tool 名并集。"""
        manifest = self._manifests.get(pack_id)
        pack_dir = self._pack_dirs.get(pack_id)
        if manifest is None or pack_dir is None:
            return set()
        names: set[str] = set()
        for rel in manifest.tools_openapi:
            path = (pack_dir / rel).resolve()
            if not path.is_file():
                log.warning("pack %s openapi 文件不存在：%s", pack_id, rel)
                continue
            names |= _operation_ids_from_openapi(path)
        for rel in manifest.skills:
            path = (pack_dir / rel).resolve()
            if path.is_file():
                names |= _skill_tool_names_from_yaml(path)
        return names

    def disabled_pack_ids(self) -> list[str]:
        """已加载且当前判定为禁用的 pack id。"""
        return [pid for pid in self._manifests if not self.is_enabled(pid)]

    def disabled_owned_skill_names(self) -> set[str]:
        names: set[str] = set()
        for pack_id in self.disabled_pack_ids():
            names |= self.owned_skill_names(pack_id)
        return names

    def disabled_owned_tool_names(self) -> set[str]:
        names: set[str] = set()
        for pack_id in self.disabled_pack_ids():
            names |= self.owned_tool_names(pack_id)
        return names

    def filter_skills(self, skills: Iterable) -> list:
        """去掉属于已禁用 Pack 的 Skill（按 name）。"""
        blocked = self.disabled_owned_skill_names()
        if not blocked:
            return list(skills)
        return [s for s in skills if getattr(s, "name", None) not in blocked]

    def pack_id_for_workflow(self, workflow_id: str) -> str | None:
        wid = (workflow_id or "").strip()
        if not wid:
            return None
        for manifest in self._manifests.values():
            for wf in manifest.workflows:
                if isinstance(wf, dict) and wf.get("id") == wid:
                    return manifest.id
        return None

    def is_workflow_pack_enabled(self, workflow_id: str) -> bool:
        """未声明归属的 workflow 视为可用；归属 pack 禁用则不可用。"""
        pack_id = self.pack_id_for_workflow(workflow_id)
        if pack_id is None:
            return True
        return self.is_enabled(pack_id)
