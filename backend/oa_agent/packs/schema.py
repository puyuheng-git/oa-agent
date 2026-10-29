"""Pack manifest 结构与 YAML 加载。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _require_str_list(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError(f"pack manifest 字段 {field!r} 须为非空字符串列表")
    return tuple(value)


def _parse_workflows(value: object) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("pack manifest 字段 'workflows' 须为列表")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"pack manifest workflows[{i}] 须为对象")
        out.append(dict(item))
    return tuple(out)


@dataclass(frozen=True)
class PackManifest:
    id: str
    display_name: str
    version: str
    connectors: tuple[str, ...]
    skills: tuple[str, ...]
    tools_openapi: tuple[str, ...]
    write_contracts: tuple[str, ...]
    rules: str | None
    workflows: tuple[dict[str, Any], ...]
    default_enabled: bool = True


def load_manifest(path: Path) -> PackManifest:
    """从 pack.yaml 加载并校验 PackManifest。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 pack manifest：{path}") from exc

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"pack manifest YAML 无效：{path}") from exc

    if not isinstance(doc, dict):
        raise ValueError(f"pack manifest 根节点须为映射：{path}")

    pack_id = doc.get("id")
    if not pack_id or not isinstance(pack_id, str):
        raise ValueError(f"pack manifest 缺少必填字段 id：{path}")

    display_name = doc.get("display_name")
    version = doc.get("version")
    if display_name is not None and not isinstance(display_name, str):
        raise ValueError(f"pack manifest 字段 display_name 须为字符串：{path}")
    if version is not None and not isinstance(version, str):
        raise ValueError(f"pack manifest 字段 version 须为字符串：{path}")

    default_enabled = doc.get("default_enabled", True)
    if not isinstance(default_enabled, bool):
        raise ValueError(f"pack manifest 字段 default_enabled 须为布尔值：{path}")

    rules = doc.get("rules")
    if rules is not None and not isinstance(rules, str):
        raise ValueError(f"pack manifest 字段 rules 须为字符串或省略：{path}")

    return PackManifest(
        id=pack_id.strip(),
        display_name=str(display_name or ""),
        version=str(version or ""),
        connectors=_require_str_list(doc.get("connectors"), "connectors"),
        skills=_require_str_list(doc.get("skills"), "skills"),
        tools_openapi=_require_str_list(doc.get("tools_openapi"), "tools_openapi"),
        write_contracts=_require_str_list(doc.get("write_contracts"), "write_contracts"),
        rules=rules,
        workflows=_parse_workflows(doc.get("workflows")),
        default_enabled=default_enabled,
    )
