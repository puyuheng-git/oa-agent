"""按 Skill 绑定与关键词从候选 Tool 中选取 Top-K（默认 8）。"""

from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_SKILL_BIND_SCORE = 1000
_KEYWORD_HIT_SCORE = 10


def _tokens(query: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(query or "") if len(t) >= 2]


def _tool_text(tool: dict[str, Any]) -> str:
    parts = (tool.get("name") or "", tool.get("summary") or "", tool.get("description") or "")
    return " ".join(str(p) for p in parts).lower()


def select_top_tools(
    query: str,
    *,
    candidates: list[dict[str, Any]],
    skill_tool_names: list[str] | None = None,
    top_k: int = 8,
) -> list[str]:
    """返回按相关度排序的 Tool 名列表，长度不超过 top_k。"""
    if top_k < 1:
        return []
    skill_set = set(skill_tool_names or [])
    by_name: dict[str, dict[str, Any]] = {}
    for item in candidates:
        name = str(item.get("name") or "").strip()
        if name and name not in by_name:
            by_name[name] = item
    if not by_name:
        return []

    tokens = _tokens(query)
    scored: list[tuple[int, str]] = []
    for name, tool in by_name.items():
        score = _SKILL_BIND_SCORE if name in skill_set else 0
        blob = _tool_text(tool)
        for tok in tokens:
            if tok in blob:
                score += _KEYWORD_HIT_SCORE
        scored.append((score, name))

    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    picked: list[str] = []
    for score, name in scored:
        if len(picked) >= top_k:
            break
        if score > 0 or name in skill_set:
            picked.append(name)
    if picked:
        return picked
    return [name for _, name in scored[:top_k]]
