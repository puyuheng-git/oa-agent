"""open_oa_invoke / 向导 probe：整包 call 时摊平 params|data 袋。

Service one_by_params → $method($clean)；page_list → $method($clean, $page, $limit)。
若 args 为 {params: {a: 1}}，业务方法会多套一层。
"""

from __future__ import annotations

from typing import Any

BAG_KEYS = ("params", "data")
BAG_CALLS = frozenset({"one_by_params", "page_list"})


def unwrap_bag_args(call: str, args: dict[str, Any] | None) -> dict[str, Any]:
    """整包 call 且存在 params|data 对象时，将其字段合并到顶层；顶层键优先。"""
    raw = dict(args or {})
    if (call or "").strip() not in BAG_CALLS:
        return raw
    for bag in BAG_KEYS:
        inner = raw.get(bag)
        if not isinstance(inner, dict):
            continue
        rest = {k: v for k, v in raw.items() if k != bag}
        return {**inner, **rest}
    return raw
