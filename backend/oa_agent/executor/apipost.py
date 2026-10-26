"""从 Apipost 分享文档生成 Tool 草稿（设计 §8.1）。

只访问 docs.apipost.net 的公开分享数据接口；生成的是表单草稿，管理员检查后走正常的新建 Tool 校验与审计。
映射是确定性的（方法、路径、参数、返回字段及其说明）；可选的模型补全只拿到字段名与说明，不拿示例数据。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

import httpx

from oa_agent.executor.catalog import FIELD_RE, NAME_RE

HOST = "docs.apipost.net"
DETAILS_URL = f"https://{HOST}/doc/details"
TIMEOUT = 10.0
MAX_BYTES = 2_000_000
MAX_TARGETS = 20
MAX_COLUMNS = 6

# 这些参数代表“当前用户”：不给模型填，改由服务端注入员工 oa
IDENTITY_KEYS = {"oa", "user_id", "userid", "uid", "user", "oa_id", "oaid", "username", "user_name", "emp_no"}
IDENTITY_HINT = re.compile(r"oa\s*号|oa\s*账号|工号|用户\s*id|用户编号|员工编号|当前用户|登录用户", re.I)
# 这些返回字段像凭证，默认不进白名单
SENSITIVE = re.compile(r"(^|_)(key|token|secret|password|passwd|pwd|sign|signature|auth)(_|$)|密钥|口令|凭证|签名", re.I)
INT_TYPES = {"integer", "int", "int32", "int64", "long"}


class ApipostError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def parse_share_url(url: str, max_targets: int = MAX_TARGETS) -> tuple[str, list[str]]:
    """https://docs.apipost.net/docs/detail/<issue_id>?target_id=<id>[,<id>] → (issue_id, target_ids)。"""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        raise ApipostError("链接格式不正确") from None
    if parts.scheme != "https" or parts.hostname != HOST:
        raise ApipostError(f"只支持 https://{HOST} 的分享链接")
    m = re.fullmatch(r"/docs/(?:detail/)?([A-Za-z0-9]{6,40})/?", parts.path)
    if not m:
        if parts.path.startswith("/docs/password/"):
            raise ApipostError("该文档设置了访问密码，暂不支持；请在 Apipost 中关闭密码后再导入")
        raise ApipostError("无法识别的 Apipost 分享链接，请复制具体接口页面的地址")
    targets = [t for v in urllib.parse.parse_qs(parts.query).get("target_id", []) for t in v.split(",") if t]
    if not targets:
        raise ApipostError("链接里没有 target_id：请在分享文档中点开具体接口，再复制地址栏链接")
    if any(not re.fullmatch(r"[A-Za-z0-9]{4,40}", t) for t in targets):
        raise ApipostError("链接里的 target_id 无效")
    if len(targets) > max_targets:
        raise ApipostError(f"一次最多导入 {max_targets} 个接口（可在「配置中心 → Apipost 导入」调整）")
    return m.group(1), targets


def fetch(issue_id: str, target_ids: list[str], client: httpx.Client | None = None,
          timeout: float = TIMEOUT, max_bytes: int = MAX_BYTES) -> list[dict]:
    body = {"issue_id": issue_id, "target_ids": target_ids}
    try:
        if client is None:
            with httpx.Client(timeout=timeout, follow_redirects=False) as c:
                resp = c.post(DETAILS_URL, json=body)
        else:
            resp = client.post(DETAILS_URL, json=body)
    except httpx.HTTPError as exc:
        raise ApipostError(f"访问 Apipost 失败：{type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise ApipostError(f"Apipost 返回 HTTP {resp.status_code}")
    if len(resp.content) > max_bytes:
        raise ApipostError("Apipost 返回内容过大")
    try:
        doc = resp.json()
    except ValueError:
        raise ApipostError("Apipost 返回的不是 JSON") from None
    if not isinstance(doc, dict) or doc.get("code") != 0:
        raise ApipostError(f"Apipost 拒绝了请求：{(doc or {}).get('msg') or '未知原因'}（文档可能已取消分享或需要密码）")
    apis = [t for t in ((doc.get("data") or {}).get("list") or [])
            if isinstance(t, dict) and t.get("target_type") == "api"]
    if not apis:
        raise ApipostError("没有找到接口定义（链接指向的可能是目录）")
    return apis


# ---------------- 映射 ----------------

def _label(description: str) -> str:
    """说明的第一句作为显示名称：「合同标识，接收合同接口需要」→「合同标识」。"""
    text = re.split(r"[，,；;。（(\n]", str(description or "").strip(), maxsplit=1)[0].strip()
    return text[:20]


def _path(url: str) -> str:
    url = re.sub(r"\{\{[^}]*\}\}", "", str(url or "")).strip()
    parts = urllib.parse.urlsplit(url if "://" in url else "http://x/" + url.lstrip("/"))
    path = "/" + parts.path.lstrip("/")
    return re.sub(r"/{2,}", "/", path)


def _tool_name(path: str) -> str:
    segs = [re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") for s in path.split("/") if s]
    name = "query_" + "_".join(s for s in segs[-2:] if s)
    name = re.sub(r"_+", "_", name)[:64].rstrip("_")
    return name if NAME_RE.match(name) else "query_imported_api"


def _find_list_schema(schema: dict) -> tuple[str, dict]:
    """在返回 schema 中找结果：data.list / data.items / data.rows / data 数组 → list；data(.info) 对象 → object。"""
    props = (schema or {}).get("properties") or {}
    data = props.get("data") or schema or {}
    if data.get("type") == "array":
        return "list", data.get("items") or {}
    inner = data.get("properties") or {}
    for key in ("list", "items", "rows", "data"):
        node = inner.get(key) or {}
        if node.get("type") == "array":
            return "list", node.get("items") or {}
    if isinstance(inner.get("info"), dict) and inner["info"].get("properties"):
        return "object", inner["info"]
    return "object", data


def _ordered_props(node: dict) -> list[tuple[str, dict]]:
    props = node.get("properties") or {}
    order = node.get("x-schema-orders") or list(props)
    return [(k, props[k]) for k in order if k in props and isinstance(props[k], dict)]


def _from_example(raw: str) -> tuple[str, list[str]]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return "object", []
    data = value.get("data", value) if isinstance(value, dict) else value
    if isinstance(data, list):
        return "list", list(data[0]) if data and isinstance(data[0], dict) else []
    if isinstance(data, dict):
        for key in ("list", "items", "rows", "data"):
            if isinstance(data.get(key), list):
                rows = data[key]
                return "list", list(rows[0]) if rows and isinstance(rows[0], dict) else []
        if isinstance(data.get("info"), dict):
            return "object", list(data["info"])
        return "object", list(data)
    return "object", []


def _default_example(api: dict) -> dict:
    examples = ((api.get("response") or {}).get("example")) or []
    return next((e for e in examples if (e.get("expect") or {}).get("is_default") == 1),
                examples[0] if examples else {})


def to_draft(api: dict, max_columns: int = MAX_COLUMNS) -> dict:
    """单个 Apipost 接口 → {form, warnings, source}；form 与后台「新建 Tool」接口的请求体同形。"""
    warnings: list[str] = []
    method = str(api.get("method") or "GET").upper()
    path = _path(api.get("url") or "")
    if method != "GET":
        raise ApipostError(f"「{api.get('name')}」是 {method} 接口：一期只支持 GET 只读查询")
    request = api.get("request") or {}

    params: dict[str, dict] = {}
    identity: dict[str, str] = {}
    query_field = ""
    for p in ((request.get("query") or {}).get("parameter") or []):
        key = str(p.get("key") or "").strip()
        if not key or p.get("is_checked") == -1:
            continue
        if not FIELD_RE.match(key):
            warnings.append(f"参数 {key} 名称含特殊字符，已跳过")
            continue
        desc = str(p.get("description") or "").strip()
        if key.lower() in IDENTITY_KEYS or IDENTITY_HINT.search(desc):
            identity[key] = "oa"
            warnings.append(f"参数 {key}（{desc or '无说明'}）识别为员工身份：改由服务端注入当前员工 oa，模型不可填。"
                            "请确认 office-api 会校验它与员工 token 一致")
            continue
        if key == "queryParams":
            query_field = key
            warnings.append("接口使用 queryParams JSON 传参：其中的字段 Apipost 未描述，请在参数表中手工补充")
            continue
        rule: dict[str, Any] = {"type": "integer" if str(p.get("field_type") or "").lower() in INT_TYPES else "string",
                                "required": p.get("not_null") == 1}
        if desc:
            rule["label"] = _label(desc)
            rule["description"] = desc[:200]
        if re.search(r"日期|date", desc + key, re.I) and rule["type"] == "string":
            rule["format"] = "date"
        params[key] = rule
    required = [k for k, r in params.items() if r["required"]]
    if required:
        warnings.append(f"Apipost 中标为必填的参数：{', '.join(required)}。员工提问时往往给不出这些值，"
                        "如接口实际可不传，请改为非必填")
    for kind in ("restful", "header", "cookie"):
        extra = [p.get("key") for p in ((request.get(kind) or {}).get("parameter") or []) if p.get("key")]
        if extra:
            warnings.append(f"{kind} 参数 {', '.join(map(str, extra))} 未导入（Authorization 由系统使用员工 token）")
    if ((request.get("body") or {}).get("parameter")):
        warnings.append("GET 接口带有 body 参数，未导入")

    example = _default_example(api)
    schema = ((example.get("expect") or {}).get("schema")) or {}
    kind, node = _find_list_schema(schema) if schema.get("properties") else ("", {})
    fields: list[str] = []
    labels: dict[str, str] = {}
    if node.get("properties"):
        for key, prop in _ordered_props(node):
            fields.append(key)
            if prop.get("description"):
                labels[key] = _label(prop["description"])
    else:
        kind, fields = _from_example(example.get("raw") or "")
        if fields:
            warnings.append("返回字段来自示例数据，没有说明，请补充显示名称")
    if not fields:
        warnings.append("没有找到返回字段定义，请手工填写返回字段")
    fields = [f for f in fields if FIELD_RE.match(f)]
    removed = [f for f in fields if SENSITIVE.search(f) or SENSITIVE.search(labels.get(f, ""))]
    if removed:
        warnings.append(f"返回字段 {', '.join(removed)} 像凭证/密钥，默认不返回给员工")
    fields = [f for f in fields if f not in removed]
    labels = {k: v for k, v in labels.items() if k in fields}
    columns = [f for f in fields if f in labels][:max_columns] if kind == "list" else []

    name = str(api.get("name") or "").strip()
    description = re.sub(r"<[^>]+>", "", str(api.get("description") or "")).strip()
    form = {
        "name": _tool_name(path),
        "summary": name[:255] or path,
        "description": (description or name)[:2000],
        "method": "GET",
        "path": path,
        "timeout_seconds": 10,
        "inject_identity_fields": ["oa"] if query_field else [],
        "top_level_fields": [],
        "query_params_field": query_field or None,
        "identity_params": identity,
        "model_params": params,
        "result": {"kind": kind or "object", "fields": fields, "labels": labels, "list_columns": columns},
    }
    if not identity and not query_field:
        warnings.append("没有识别到身份参数：office-api 只能凭员工 token 判断本人，请确认接口确实如此")
    return {"form": form, "warnings": warnings,
            "source": {"target_id": api.get("target_id"), "name": name, "method": method, "url": api.get("url")}}


# ---------------- 模型补全 ----------------

ENRICH_PROMPT = """你在帮管理员配置 OA 助手的查询 Tool。根据接口信息输出一个 JSON 对象，不要输出其他文字：
{{"name": "小写字母数字下划线的 Tool 名，以 query_ 开头，3-64 位",
  "description": "给模型看的用途说明：员工问什么问题时该用它、能查到什么（不超过 120 字）",
  "list_columns": ["列表中最值得展示的字段，最多 {max_columns} 个，只能从返回字段中选"],
  "params": {{"参数名": "给模型的填参说明（不超过 60 字）"}},
  "skill": {{"name": "小写字母数字下划线的 Skill 名", "display_name": "员工看到的功能名（不超过 10 字）",
            "description": "这个能力解决什么问题", "instructions": "把员工的话转换成参数的指引",
            "examples": ["3 到 5 条员工可能的提问"]}}}}
员工只能查询本人的数据，身份由系统注入，不要在参数说明里让模型填写员工身份。

接口：{summary}
说明：{description}
路径：GET {path}
结果类型：{kind}
模型可填参数：{params}
返回字段：{fields}"""


def enrich(chat_model, draft: dict, max_columns: int = MAX_COLUMNS) -> list[str]:
    """用模型补全名称、用途说明、列表列、参数说明与配套 Skill；只发送字段名和说明，不发送示例数据。"""
    from oa_agent.runtime.llm import complete_json

    form = draft["form"]
    result = form["result"]
    prompt = ENRICH_PROMPT.format(
        max_columns=max_columns,
        summary=form["summary"], description=form["description"], path=form["path"], kind=result["kind"],
        params=json.dumps({k: {"label": r.get("label"), "description": r.get("description"), "type": r["type"],
                               "required": r["required"]} for k, r in form["model_params"].items()},
                          ensure_ascii=False) or "无",
        fields=json.dumps({f: result["labels"].get(f, "") for f in result["fields"]}, ensure_ascii=False))
    out = complete_json(chat_model, [("system", "你只输出 JSON。"), ("human", prompt)])
    notes = []
    name = str(out.get("name") or "")
    if NAME_RE.match(name):
        form["name"] = name
    if isinstance(out.get("description"), str) and out["description"].strip():
        form["description"] = out["description"].strip()[:2000]
    cols = [c for c in (out.get("list_columns") or []) if c in result["fields"]][:max_columns]
    if result["kind"] == "list" and cols:
        result["list_columns"] = cols
    for key, text in (out.get("params") or {}).items():
        if key in form["model_params"] and isinstance(text, str) and text.strip():
            form["model_params"][key]["description"] = text.strip()[:200]
    skill = out.get("skill") if isinstance(out.get("skill"), dict) else None
    if skill:
        skill_name = str(skill.get("name") or "")
        examples = [str(e).strip()[:100] for e in (skill.get("examples") or []) if str(e).strip()][:10]
        draft["skill"] = {
            "name": skill_name if NAME_RE.match(skill_name) else (form["name"].removeprefix("query_") + "_skill")[:64],
            "display_name": str(skill.get("display_name") or form["summary"])[:128],
            "description": str(skill.get("description") or form["description"])[:2000],
            "instructions": str(skill.get("instructions") or "")[:2000],
            "examples": examples,
            "tools": [form["name"]],
        }
    notes.append("名称、用途说明、列表列、参数说明与配套 Skill 由模型生成，请检查")
    return notes
