"""将 Tool 返回的标量/列表/对象格式化为员工可见的中文文本（避免 JSON 数组进对话）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oa_agent.executor.registry import ToolSpec

TRAVEL_EXPENSE_DETAIL = "query_my_travel_expense_detail"

# 行程报销详情：对话正文必须优先展示的核心字段（顺序固定）
TRAVEL_DETAIL_BODY_KEYS: tuple[str, ...] = (
    "id",
    "status_text",
    "total_amount",
    "date",
    "transport_types_desc",
    "travel_route",
)

_ROUTE_DICT_KEYS = ("name", "place", "city", "address", "label", "title", "desc", "location")


def format_field_value(value: object) -> str:
    """将 office-api 字段值转为可读中文；列表路线用「→」连接，不用 JSON。"""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        parts = [_format_route_segment(x) for x in value]
        parts = [p for p in parts if p]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return " → ".join(parts)
    if isinstance(value, dict):
        for key in _ROUTE_DICT_KEYS:
            if value.get(key) not in (None, ""):
                return str(value[key]).strip()
        flat = [str(v).strip() for v in value.values() if v not in (None, "")]
        return "、".join(flat)
    return str(value).replace("\n", " ").strip()


def _format_route_segment(item: object) -> str:
    if item is None or item == "":
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return format_field_value(item)
    if isinstance(item, (list, tuple)):
        return format_field_value(list(item))
    return str(item).strip()


def format_record_item(data: dict) -> dict:
    """返回与 data 同键；列表/对象字段格式化为展示用字符串，标量保持原类型。"""
    out: dict = {}
    for key, raw in data.items():
        if isinstance(raw, (list, dict)):
            text = format_field_value(raw)
            if text:
                out[key] = text
        elif raw not in (None, ""):
            out[key] = raw
    return out


def _status_label(spec: ToolSpec, data: dict) -> str:
    if data.get("status_text") not in (None, ""):
        return str(data["status_text"])
    status = data.get("status")
    if status in (None, ""):
        return ""
    rule = (spec.model_params.get("status") or {}).get("enum_labels") or {}
    return str(rule.get(str(status), status))


def travel_expense_detail_body(spec: ToolSpec, data: dict) -> str:
    """行程报销详情：满足外置聊天 UI 首屏要求的纯文本行（不以 - / | / > 开头）。"""
    lines: list[str] = []

    def line(label: str, text: str) -> None:
        lines.append(f"{label}：{text}" if text else f"{label}：暂无")

    id_text = format_field_value(data.get("id"))
    line("单号", id_text)

    status = _status_label(spec, data) or format_field_value(data.get("status"))
    line("状态", status)

    line("金额", format_field_value(data.get("total_amount")))
    line("行程日期", format_field_value(data.get("date")))

    transport = data.get("transport_types_desc")
    if transport not in (None, ""):
        line("交通", format_field_value(transport))

    route = data.get("travel_route")
    if route not in (None, ""):
        line("路线", format_field_value(route))

    return "\n".join(lines)


def record_reply_body(spec: ToolSpec, title: str, data: dict) -> str:
    if spec.name == TRAVEL_EXPENSE_DETAIL:
        return travel_expense_detail_body(spec, data)
    shown = [f for f in spec.result_fields if f in spec.result_labels] or list(spec.result_fields)
    fields = [f for f in shown if data.get(f) not in (None, "")]
    if not fields:
        return f"{title}：未返回可展示字段。"
    lines = [f"{title}" + (f"（单号 {data['id']}）" if data.get("id") not in (None, "") else "")]
    lines += [f"{spec.label(f)}：{format_field_value(data.get(f))}" for f in fields
            if format_field_value(data.get(f)) or data.get(f) not in (None, "")]
    return "\n".join(lines)


def record_human_summary(spec: ToolSpec, title: str, data: dict) -> str:
    """工具结果里附带的一行/多行可读摘要（与 reply.content 主体一致）。"""
    return record_reply_body(spec, title, data).strip()
