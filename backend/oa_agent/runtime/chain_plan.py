"""服务端多轮 Tool 规划：不依赖模型 JSON Schema $ref。"""

from __future__ import annotations

from typing import Any


def plan_list_then_detail(
    list_tool: str,
    detail_tool: str,
    detail_id_field: str,
) -> list[dict[str, Any]]:
    """两轮串联：先 list 再 detail，detail 步从 list 结果取 id 字段。"""
    list_tool = str(list_tool or "").strip()
    detail_tool = str(detail_tool or "").strip()
    detail_id_field = str(detail_id_field or "").strip()
    if not list_tool or not detail_tool or not detail_id_field:
        raise ValueError("list_tool、detail_tool、detail_id_field 均不能为空")
    return [
        {
            "step": 1,
            "tool": list_tool,
            "purpose": "list",
        },
        {
            "step": 2,
            "tool": detail_tool,
            "purpose": "detail",
            "detail_id_field": detail_id_field,
            "id_from_step": 1,
        },
    ]
