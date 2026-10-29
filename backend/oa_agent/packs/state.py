"""Domain Pack 启停状态：packs.disabled_ids（默认空列表）。"""

from __future__ import annotations

from typing import Any

PACKS_GROUP = "packs"
DISABLED_IDS_KEY = "disabled_ids"


def normalize_disabled_ids(raw: Any) -> list[str]:
    """规范化 disabled_ids：仅保留非空字符串，去重且保序。"""
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        pack_id = item.strip()
        if not pack_id or pack_id in seen:
            continue
        seen.add(pack_id)
        out.append(pack_id)
    return out


def load_disabled_ids(
    source: dict[str, Any] | None = None,
    *,
    db: Any = None,
    settings_service: Any = None,
) -> list[str]:
    """读取禁用列表。

    优先使用 ``source`` 覆盖（便于单测）；否则经 SettingsService.effective(db, "packs")。
    """
    if source is not None:
        return normalize_disabled_ids(source.get(DISABLED_IDS_KEY))
    if db is not None and settings_service is not None:
        values = settings_service.effective(db, PACKS_GROUP)
        return normalize_disabled_ids(values.get(DISABLED_IDS_KEY))
    return []


def save_disabled_ids(
    disabled_ids: list[str],
    target: dict[str, Any] | None = None,
    *,
    db: Any = None,
    settings_service: Any = None,
    actor: str = "system",
) -> list[str]:
    """写入禁用列表；返回规范化后的列表。

    ``target`` 为 dict 时就地更新（单测/内存）；否则经 SettingsService.update。
    """
    normalized = normalize_disabled_ids(disabled_ids)
    if target is not None:
        target[DISABLED_IDS_KEY] = list(normalized)
        return normalized
    if db is not None and settings_service is not None:
        settings_service.update(
            db,
            PACKS_GROUP,
            {DISABLED_IDS_KEY: list(normalized)},
            clear_secrets=[],
            actor=actor,
        )
        return normalized
    raise ValueError("save_disabled_ids 需要 target 字典或 (db, settings_service)")
