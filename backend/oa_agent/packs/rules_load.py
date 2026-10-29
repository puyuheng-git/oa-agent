"""从 Pack rules YAML 加载意图 → Tool 映射。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_intent_rules(path: Path) -> dict[str, Any]:
    """加载 intent.yaml，返回至少含 ``rule_tools`` 的字典。

    期望形态::
        rule_tools:
          list: query_my_travel_expense_list
          detail: query_my_travel_expense_detail
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 intent rules：{path}") from exc

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"intent rules YAML 无效：{path}") from exc

    if doc is None:
        return {"rule_tools": {}}
    if not isinstance(doc, dict):
        raise ValueError(f"intent rules 根节点须为映射：{path}")

    rule_tools_raw = doc.get("rule_tools") or {}
    if not isinstance(rule_tools_raw, dict):
        raise ValueError(f"intent rules 字段 rule_tools 须为映射：{path}")

    rule_tools: dict[str, str] = {}
    for key, value in rule_tools_raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise ValueError(f"intent rules rule_tools[{key!r}] 须为非空字符串：{path}")
        rule_tools[key] = value.strip()

    out = dict(doc)
    out["rule_tools"] = rule_tools
    return out
