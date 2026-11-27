"""参数放置 / 编码：与前端 admin/paramWire.ts 对齐。

placement: scalar | bag | query | body
encoding: auto | flat | repeat | json
  - form/query 下 object / 袋参数用 PHP 多维数组（name[key]=），不用 JSON 字符串
  - application/json body 仍保真嵌套对象
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

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
        return "json"  # form 下实际展开为 name[key]= 多维数组
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


def flatten_php_form(prefix: str, value: Any) -> dict[str, Any]:
    """把 dict/list 展成 PHP 多维表单键：a[b]=1、a[b][c]=2、a[]=1。

    OA PHP 的 $_GET/$_POST 会还原成多维数组，无需 json_decode。
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if v is None or v == "":
                continue
            key = f"{prefix}[{k}]"
            out.update(flatten_php_form(key, v))
        return out
    if isinstance(value, list):
        out = {}
        scalar_items: list[Any] = []
        for i, v in enumerate(value):
            if v is None or v == "":
                continue
            if isinstance(v, (dict, list)):
                out.update(flatten_php_form(f"{prefix}[{i}]", v))
            else:
                scalar_items.append(encode_flat_value(v))
        if scalar_items:
            out[f"{prefix}[]"] = scalar_items
        return out
    return {prefix: encode_flat_value(value)}


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
        # form/query：多维数组，不用 JSON 字符串
        return flatten_php_form(name, value)
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
        return flatten_php_form(name, value)
    return {name: encode_flat_value(value)}


def normalize_request_charset(charset: str | None, content_type: str | None) -> str:
    """解析有效字符集：gbk | utf-8。"""
    raw = (charset or "").strip().lower()
    if raw in ("gb2312", "gbk"):
        return "gbk"
    if raw in ("utf-8", "utf8"):
        return "utf-8"
    ct = (content_type or "").strip().lower()
    if ct.startswith("application/json"):
        return "utf-8"
    # OA PHP 默认 GBK（GET query 与 form-urlencoded）
    return "gbk"


def encode_www_form(data: dict[str, Any], charset: str = "utf-8") -> tuple[bytes, str]:
    """按指定字符集做 application/x-www-form-urlencoded。

    返回 (body_bytes, Content-Type 含 charset)。OA 端读 $_POST 时字节按 GBK 解释。
    """
    enc = "gbk" if (charset or "").lower() in ("gbk", "gb2312") else "utf-8"
    # doseq：list 值展开为多键（配合 ids[]= / name[key][]=）
    text = urlencode(data or {}, doseq=True, encoding=enc, errors="replace")
    return text.encode("ascii"), f"application/x-www-form-urlencoded; charset={enc}"


def encode_query_string(params: dict[str, Any] | None, charset: str = "utf-8") -> str:
    """查询串（不含 ?）；空 params 返回空串。"""
    if not params:
        return ""
    enc = "gbk" if (charset or "").lower() in ("gbk", "gb2312") else "utf-8"
    return urlencode(params, doseq=True, encoding=enc, errors="replace")


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

    袋 / 对象在 form、query 下展开为 PHP 多维数组键（name[key]=），不用 JSON 字符串。
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
        # POST form：全部进 body（$_POST）；POST JSON：仅显式 placement=query 留 query
        if method_u == "POST":
            if placement == "bag":
                target = "bag"
            elif json_body and rule.get("placement") == "query":
                target = "query"
            else:
                target = "body"
        else:
            target = "query" if placement == "body" else placement
        enc = resolve_encoding(rule, rule.get("encoding"), ct, target if target != "bag" else "bag")
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
        elif method_u == "POST" and not identity_into_bag:
            body[param] = value
        else:
            query[param] = value

    if has_bag and bag_obj:
        if json_body and method_u == "POST":
            body[bag_name] = bag_obj
        else:
            # form/query：queryParams[status]=1&queryParams[oa]=zhang
            flat = flatten_php_form(bag_name, bag_obj)
            if method_u == "POST":
                body.update(flat)
            else:
                query.update(flat)

    return query, (body if method_u == "POST" else None), ct
