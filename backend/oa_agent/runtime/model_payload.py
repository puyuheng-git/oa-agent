"""构建给模型看的工具结果：脱敏、限行，再压成 JSON 字符串。"""

from __future__ import annotations

import json
from typing import Any

from oa_agent.observability.redact import redact_pii
from oa_agent.security.prompt_guard import unwrap_untrusted, wrap_untrusted

_REDACTED = "[已脱敏]"
_TRUNCATED = "…[截断]"

# 字段名小写后的子串；命中整段值换成「已脱敏」，不靠值的形态。
_SENSITIVE_NAME_PARTS = (
    "id_card",
    "idcard",
    "id_no",
    "身份证",
    "证件号",
    "bank_card",
    "bankcard",
    "bank_account",
    "银行卡",
    "卡号",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "mobile",
    "phone",
    "手机",
    "salary",
    "wage",
    "工资",
    "薪资",
)


def is_sensitive_field_name(name: str) -> bool:
    """字段名是否属于全局敏感黑名单（大小写不敏感，子串匹配）。"""
    lowered = str(name or "").lower()
    for part in _SENSITIVE_NAME_PARTS:
        if part in lowered:
            return True
    # 「银行账号」「卡账号」这类没有标准词根、但两段同时出现的名字。
    if "账号" in lowered and ("银行" in lowered or "卡" in lowered):
        return True
    return False


def scrub_value(field: str, value: Any) -> Any:
    """敏感字段名整值替换；普通字符串只扫身份证/银行卡/手机号等值形态。"""
    if is_sensitive_field_name(field):
        return _REDACTED
    if isinstance(value, str):
        return redact_pii(value)
    return value


def scrub_row(row: dict, columns: list[str]) -> dict:
    """按列白名单取出一行并脱敏，不带行列不会出现在结果里。"""
    source = row if isinstance(row, dict) else {}
    cleaned: dict[str, Any] = {}
    for column in columns:
        cleaned[column] = scrub_value(column, source.get(column))
    return cleaned


def build_model_payload(
    *,
    tool: str,
    kind: str,
    data: dict,
    columns: list[str] | None = None,
    max_rows: int = 20,
    max_chars: int = 6000,
) -> str:
    """把工具结果收成模型可读的 JSON。超长时先缩短正文或行数，结果仍是合法 JSON。"""
    payload_data = data if isinstance(data, dict) else {}
    if kind in ("list", "table"):
        body = _list_payload(tool, kind, payload_data, columns, max_rows)
    elif kind == "record":
        body = _record_payload(tool, payload_data, columns)
    elif kind == "text":
        body = _text_payload(tool, payload_data, max_chars)
    else:
        raise ValueError(f"unsupported payload kind: {kind}")
    return _dump(body, max_chars)


def _source_rows(data: dict) -> list:
    """`list` 键存在且是列表时用它（含空列表）；否则才用 `items`。"""
    if "list" in data and isinstance(data["list"], list):
        return data["list"]
    if "items" in data and isinstance(data["items"], list):
        return data["items"]
    return []


def _list_payload(tool: str, kind: str, data: dict, columns: list[str] | None, max_rows: int) -> dict:
    rows = _source_rows(data)
    total = _as_total(data.get("total"), len(rows))
    shown_rows = rows[:max_rows] if max_rows is not None else rows
    cols = _resolve_columns(columns, data, shown_rows)
    items = [scrub_row(row, cols) for row in shown_rows]
    shown = len(items)
    return {
        "tool": tool,
        "kind": kind,
        "total": total,
        "shown": shown,
        "note": _row_note(total, shown),
        "columns": cols,
        "items": items,
    }


def _record_payload(tool: str, data: dict, columns: list[str] | None) -> dict:
    item = data.get("item")
    if not isinstance(item, dict):
        item = {}
        for key in columns or []:
            if key in data:
                item[key] = data[key]
    cols = _resolve_columns(columns, data, [item])
    cleaned = scrub_row(item, cols)
    shown = 1 if cleaned else 0
    return {
        "tool": tool,
        "kind": "record",
        "total": shown,
        "shown": shown,
        "note": _row_note(shown, shown, record=True),
        "columns": cols,
        "item": cleaned,
    }


_TEXT_NOTE = "正文已脱敏；完整内容已展示给员工。"
_TEXT_NOTE_CLIP = "正文已脱敏，超出字数已截断；完整内容已展示给员工。"
_CHAR_CLIP_NOTE = "超出字数已截断。"


def _text_payload(tool: str, data: dict, max_chars: int | None) -> dict:
    raw = data.get("text")
    if raw is None:
        raw = ""
    elif not isinstance(raw, str):
        raw = str(raw)
    # 先拆掉上游围栏，只对正文脱敏，再按工具结果重新围上。
    plain = redact_pii(unwrap_untrusted(raw))
    if max_chars is None:
        return _compose_text(tool, plain, 8000, None)
    return _fit_text(tool, plain, max_chars)


def _compose_text(
    tool: str,
    plain: str,
    limit: int,
    note: str | None,
    *,
    keep_note: bool = True,
) -> dict:
    """按给定正文上限围栏。保留说明且未指定文案时，按是否截断选择。"""
    clipped = len(plain) > limit
    fenced = wrap_untrusted(plain, source="tool_result", name=tool, max_chars=limit)
    if not keep_note:
        return {
            "tool": tool,
            "kind": "text",
            "total": 1,
            "shown": 1,
            "text": fenced,
        }
    if note is None:
        note = _TEXT_NOTE_CLIP if clipped else _TEXT_NOTE
    return {
        "tool": tool,
        "kind": "text",
        "total": 1,
        "shown": 1,
        "note": note,
        "text": fenced,
    }


def _dumps(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _escaped_len(value: str) -> int:
    """JSON 字符串字面量去掉两端引号后的长度（含转义）。"""
    return len(json.dumps(value, ensure_ascii=False)) - 2


def _text_skeleton_len(tool: str, note: str | None) -> int:
    """空 `text` 时整段 JSON 的长度，用来给围栏正文留预算。"""
    skeleton: dict[str, Any] = {
        "tool": tool,
        "kind": "text",
        "total": 1,
        "shown": 1,
        "text": "",
    }
    if note is not None:
        skeleton = {
            "tool": tool,
            "kind": "text",
            "total": 1,
            "shown": 1,
            "note": note,
            "text": "",
        }
    return len(_dumps(skeleton))


def _inner_body_limit(tool: str, note: str | None, max_chars: int) -> int:
    """围栏外壳和截断标记占用之后，正文还能放多少字，最终 JSON 才不超过 `max_chars`。"""
    room = max_chars - _text_skeleton_len(tool, note)
    shell = wrap_untrusted("", source="tool_result", name=tool, max_chars=0)
    suffix_cost = _escaped_len(_TRUNCATED)
    return max(0, room - _escaped_len(shell) - suffix_cost)


def _fit_text(tool: str, plain: str, max_chars: int) -> dict:
    """先试全文；放不下就按外壳开销缩小传给 `wrap_untrusted` 的上限，围栏头尾保持完整。"""
    payload = _compose_text(tool, plain, len(plain), None)
    if len(_dumps(payload)) <= max_chars:
        return payload
    for note in (_TEXT_NOTE_CLIP, _CHAR_CLIP_NOTE):
        payload = _text_within_budget(tool, plain, note, max_chars)
        if len(_dumps(payload)) <= max_chars:
            return payload
    # 说明也放不下时去掉 note，只留围栏正文。
    return _text_within_budget(tool, plain, None, max_chars, keep_note=False)


def _text_within_budget(
    tool: str,
    plain: str,
    note: str | None,
    max_chars: int,
    *,
    keep_note: bool = True,
) -> dict:
    skeleton_note = note if keep_note else None
    limit = min(_inner_body_limit(tool, skeleton_note, max_chars), len(plain))
    payload = _compose_text(tool, plain, limit, note, keep_note=keep_note)
    # 引号、换行会在 JSON 里变长；按超出的长度再收正文，直到放下或收到 0。
    for _ in range(12):
        size = len(_dumps(payload))
        if size <= max_chars or limit <= 0:
            break
        overflow = size - max_chars
        next_limit = max(0, limit - overflow)
        if next_limit == limit:
            next_limit = limit - 1
        limit = next_limit
        payload = _compose_text(tool, plain, limit, note, keep_note=keep_note)
    return payload


def _resolve_columns(columns: list[str] | None, data: dict, rows: list) -> list[str]:
    if columns is not None:
        return list(columns)
    fields = data.get("fields")
    if isinstance(fields, list) and fields:
        return [str(field) for field in fields]
    for row in rows:
        if isinstance(row, dict) and row:
            return list(row.keys())
    return []


def _as_total(raw: Any, fallback: int) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        return fallback
    return raw


def _row_note(total: int, shown: int, record: bool = False) -> str:
    if record:
        return "单条记录已脱敏；完整内容已展示给员工。"
    if shown < total:
        return f"共 {total} 条，仅展示前 {shown} 条供推理；完整表已展示给员工。敏感字段已脱敏。"
    return f"共 {total} 条，展示 {shown} 条供推理；完整结果已展示给员工。敏感字段已脱敏。"


def _pack_rows(body: dict, items: list, note: str) -> dict:
    total = body.get("total")
    if isinstance(total, bool) or not isinstance(total, int):
        total = len(items)
    columns = body.get("columns")
    if not isinstance(columns, list):
        columns = []
    return {
        "tool": body.get("tool"),
        "kind": body.get("kind"),
        "total": total,
        "shown": len(items),
        "note": note,
        "columns": list(columns),
        "items": items,
    }


def _pack_record(body: dict, item: dict, note: str) -> dict:
    shown = 1 if item else 0
    columns = body.get("columns")
    if not isinstance(columns, list):
        columns = []
    return {
        "tool": body.get("tool"),
        "kind": "record",
        "total": shown,
        "shown": shown,
        "note": note,
        "columns": list(columns),
        "item": item,
    }


def _clip_strings(value: Any, limit: int) -> Any:
    """把字符串收到 `limit` 字以内，并带上截断标记；不改数字等其它类型。"""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        if limit <= len(_TRUNCATED):
            return _TRUNCATED[:limit]
        return value[: limit - len(_TRUNCATED)] + _TRUNCATED
    if isinstance(value, dict):
        return {key: _clip_strings(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_clip_strings(item, limit) for item in value]
    return value


def _largest_prefix(body: dict, items: list, note: str, max_chars: int) -> int:
    """在说明文字不变的前提下，找出还能放进预算的最长前缀。"""
    lo = 0
    hi = len(items)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        packed = _pack_rows(body, items[:mid], note)
        if len(_dumps(packed)) <= max_chars:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _pack_with_best_note(body: dict, items: list, max_chars: int) -> dict:
    total = body.get("total")
    if isinstance(total, bool) or not isinstance(total, int):
        total = len(items)
    packed = _pack_rows(body, items, _row_note(total, len(items)))
    if len(_dumps(packed)) <= max_chars:
        return packed
    return _pack_rows(body, items, _CHAR_CLIP_NOTE)


def _longest_str(value: dict) -> int:
    longest = 0
    for item in value.values():
        if isinstance(item, str) and len(item) > longest:
            longest = len(item)
    return longest


def _fit_one_clipped_item(body: dict, row: dict, max_chars: int) -> dict | None:
    lo = 0
    hi = _longest_str(row)
    best: dict | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        packed = _pack_with_best_note(body, [_clip_strings(row, mid)], max_chars)
        if len(_dumps(packed)) <= max_chars:
            best = packed
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _shrink_items(body: dict, max_chars: int) -> dict:
    items = body.get("items") if isinstance(body.get("items"), list) else []
    # 先减行。一行完整内容仍超长时，再缩短这一行里的字符串。
    count = _largest_prefix(body, items, _CHAR_CLIP_NOTE, max_chars)
    if count == 0 and items and isinstance(items[0], dict):
        clipped = _fit_one_clipped_item(body, items[0], max_chars)
        if clipped is not None:
            return clipped
    packed = _pack_with_best_note(body, items[:count], max_chars)
    if len(_dumps(packed)) <= max_chars:
        return packed
    return _drop_optional(packed, max_chars)


def _shrink_record(body: dict, max_chars: int) -> dict:
    item = body.get("item") if isinstance(body.get("item"), dict) else {}
    shown = 1 if item else 0
    packed = _pack_record(body, item, _row_note(shown, shown, record=True))
    if len(_dumps(packed)) <= max_chars:
        return packed
    packed = _pack_record(body, item, _CHAR_CLIP_NOTE)
    if len(_dumps(packed)) <= max_chars:
        return packed
    lo = 0
    hi = _longest_str(item)
    best: dict | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        clipped = _clip_strings(item, mid)
        shown = 1 if clipped else 0
        candidate = _pack_record(body, clipped, _CHAR_CLIP_NOTE)
        nicer = _pack_record(body, clipped, _row_note(shown, shown, record=True))
        if len(_dumps(nicer)) <= max_chars:
            candidate = nicer
        if len(_dumps(candidate)) <= max_chars:
            best = candidate
            lo = mid + 1
        else:
            hi = mid - 1
    if best is not None:
        return best
    return _drop_optional(_pack_record(body, {}, _CHAR_CLIP_NOTE), max_chars)


def _plain_from_fenced(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    plain = unwrap_untrusted(value)
    if plain.endswith(_TRUNCATED):
        return plain[: -len(_TRUNCATED)]
    return plain


def _drop_optional(body: dict, max_chars: int) -> dict:
    """最后才去掉说明、列名。不去掉正文，也不从 JSON 字符串中间切开。"""
    current = dict(body)
    if len(_dumps(current)) <= max_chars:
        return current
    if current.get("note") != _CHAR_CLIP_NOTE:
        current["note"] = _CHAR_CLIP_NOTE
        if len(_dumps(current)) <= max_chars:
            return current
    for key in ("note", "columns"):
        if key not in current:
            continue
        current.pop(key)
        if len(_dumps(current)) <= max_chars:
            return current
    return current


def _shrink_to_fit(body: dict, max_chars: int) -> dict:
    kind = body.get("kind")
    if kind in ("list", "table"):
        fitted = _shrink_items(body, max_chars)
    elif kind == "record":
        fitted = _shrink_record(body, max_chars)
    elif kind == "text":
        plain = _plain_from_fenced(body.get("text"))
        fitted = _fit_text(str(body.get("tool") or ""), plain, max_chars)
    else:
        fitted = dict(body)
    if len(_dumps(fitted)) <= max_chars:
        return fitted
    return _drop_optional(fitted, max_chars)


def _dump(body: dict, max_chars: int | None) -> str:
    text = _dumps(body)
    if max_chars is None or len(text) <= max_chars:
        return text
    # 只缩短内容再序列化，避免把合法 JSON 从中间切断。
    return _dumps(_shrink_to_fit(body, max_chars))
