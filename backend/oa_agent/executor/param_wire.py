"""参数放置 / 编码：与前端 admin/paramWire.ts 对齐。

placement: scalar | bag | query | body
encoding: auto | flat | repeat | json
"""

from __future__ import annotations

import json
from typing import Any

PLACEMENTS = frozenset({"scalar", "bag", "query", "body"})
ENCODINGS = frozenset({"auto", "flat", "repeat", "json"})
CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "application/json",
})
_SCALAR = frozenset({"string", "integer", "number", "boolean", "file"})


def recommend_encoding(rule: dict) -> str:
    t = rule.get("type") or "string"
    if t == "object":
        return "json"
    if t == "array":
        item = (rule.get("items") or {}).get("type") or "string"
        if item in _SCALAR and item != "file":
            return "repeat"
        return "json"
    return "flat"


def resolve_encoding(rule: dict, encoding: str | None, content_type: str | None, placement: str) -> str:
    raw = (encoding or "auto").strip() or "auto"
    if raw != "auto":
        if content_type == "application/json" and placement == "body" and raw == "repeat":
            return "json"
        return raw if raw in ENCODINGS else "flat"
    if content_type == "application/json" and placement == "body":
        rec = recommend_encoding(rule)
        return "flat" if rec == "repeat" else rec
    return recommend_encoding(rule)


def infer_placement(
    name: str,
    rule: dict,
    *,
    is_export: bool,
    method: str,
    top_level: set[str] | frozenset[str],
    has_bag: bool,
) -> str:
    explicit = rule.get("placement")
    if explicit in PLACEMENTS:
        if is_export:
            return "bag" if explicit == "bag" else "scalar"
        if explicit == "scalar":
            return "query"
        return str(explicit)
    if name in top_level:
        return "scalar" if is_export else "query"
    if has_bag:
        return "bag"
    if is_export:
        return "bag"
    return "body" if (method or "GET").upper() == "POST" else "query"


def encode_flat_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def encode_param_value(
    name: str,
    value: Any,
    encoding: str,
    *,
    json_body: bool,
) -> dict[str, Any]:
    if json_body and encoding != "json":
        return {name: value}
    if encoding == "json":
        if json_body:
            return {name: value}
        return {name: json.dumps(value, ensure_ascii=False, separators=(",", ":"))}
    if encoding == "repeat":
        items = value if isinstance(value, list) else [value]
        out_list = []
        for v in items:
            if isinstance(v, bool):
                out_list.append("1" if v else "0")
            else:
                out_list.append(v)
        return {f"{name}[]": out_list}
    if isinstance(value, list):
        return {name: ",".join(encode_flat_value(v) for v in value)}
    if isinstance(value, dict):
        return {name: json.dumps(value, ensure_ascii=False, separators=(",", ":"))}
    return {name: encode_flat_value(value)}


def build_wired_parts(
    model_params: dict[str, dict],
    args: dict[str, Any],
    *,
    method: str,
    content_type: str | None,
    bag_field: str | None,
    top_level_fields: tuple[str, ...] | list[str],
    identity_pairs: list[tuple[str, str]],
    identity_into_bag: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """返回 (query, body|None, effective_content_type)。

    identity_pairs: [(param_name, value), ...]
    identity_into_bag: True 时写入袋，否则按独立参数写入 query（或 POST 时与 body 同通道）。
    """
    method_u = (method or "GET").upper()
    has_bag = bool(bag_field and str(bag_field).strip())
    bag_name = str(bag_field).strip() if has_bag else ""
    top = set(top_level_fields or ())
    ct = None
    if method_u == "POST":
        ct = (content_type or "application/x-www-form-urlencoded").strip()
        if ct not in CONTENT_TYPES:
            ct = "application/x-www-form-urlencoded"
    json_body = ct == "application/json"

    query: dict[str, Any] = {}
    body: dict[str, Any] = {}
    bag_obj: dict[str, Any] = {}

    for name, rule in (model_params or {}).items():
        if name not in args:
            continue
        val = args[name]
        if val is None or val == "":
            continue
        placement = infer_placement(
            name, rule, is_export=False, method=method_u, top_level=top, has_bag=has_bag,
        )
        enc = resolve_encoding(rule, rule.get("encoding"), ct, placement if placement != "bag" else "bag")
        target = "query" if method_u == "GET" and placement == "body" else placement
        encoded = encode_param_value(
            name, val, enc, json_body=json_body and target == "body",
        )
        if target == "bag" and has_bag:
            bag_obj[name] = val
        elif target == "body" and method_u == "POST":
            body.update(encoded)
        else:
            query.update(encoded)

    for param, value in identity_pairs:
        if not param:
            continue
        if identity_into_bag and has_bag:
            bag_obj[param] = value
        elif method_u == "POST" and (body or json_body) and not identity_into_bag:
            # 独立身份：有 body 时跟 body 走，否则 query
            if body or json_body:
                body[param] = value
            else:
                query[param] = value
        else:
            query[param] = value

    if has_bag and bag_obj:
        if json_body and method_u == "POST":
            body[bag_name] = bag_obj
        elif method_u == "POST" and ct and "form" in ct and body:
            body[bag_name] = json.dumps(bag_obj, ensure_ascii=False, separators=(",", ":"))
        else:
            # GET 或 POST 但 body 空：袋放 query
            if method_u == "POST" and body:
                body[bag_name] = json.dumps(bag_obj, ensure_ascii=False, separators=(",", ":"))
            else:
                query[bag_name] = json.dumps(bag_obj, ensure_ascii=False, separators=(",", ":"))

    return query, (body if method_u == "POST" else None), ct
