"""测调成功后用默认 LLM 生成完整 Tool schema 候选（管理员核对后再入库）。"""

from __future__ import annotations

import json
from typing import Any

from oa_agent.executor.catalog import NAME_RE, RESULT_FIELD_RE
from oa_agent.runtime.llm import complete_json

MAX_COLUMNS = 6
MAX_FIELDS = 40

ENRICH_PROMPT = """你在帮管理员配置 OA 助手的查询 Tool。根据测调入参、返回样例与当前草稿，输出一个 JSON 对象，不要输出其他文字：
{{"name": "小写字母数字下划线的 Tool 名，以 query_ 开头，3-64 位",
  "summary": "给管理员看的短名称说明（不超过 40 字）",
  "description": "给模型看的用途说明：员工问什么问题时该用它、能查到什么（不超过 120 字）",
  "result_kind": "list 或 object",
  "fields": [{{"field": "返回字段名，支持一层点路径如 user.name", "label": "中文显示名"}}],
  "list_columns": ["列表中优先展示的字段，最多 {max_columns} 个，必须是 fields 中的 field"],
  "params": {{"参数名": {{"label": "显示名", "description": "给模型的填参说明（不超过 60 字）"}}}},
  "skill": {{"name": "小写字母数字下划线的 Skill 名", "display_name": "员工看到的功能名（不超过 10 字）",
            "description": "这个能力解决什么问题", "instructions": "把员工的话转换成参数的指引",
            "examples": ["3 到 5 条员工可能的提问"]}}}}
员工只能查询本人的数据，身份由系统注入，不要在参数说明里让模型填写员工身份。
fields 只能从测调返回样例中出现的键推断（含一层点路径），不要编造不存在的字段。
params 只能补全「当前草稿已有参数」的 label/description，不要新增草稿里没有的参数名。

当前草稿名称：{name}
当前说明：{summary}
路径或方法：{path_hint}
结果类型草稿：{kind}
模型可填参数：{params}
测调入参：{probe_args}
测调返回（截断）：{probe_data}
已有返回字段：{fields}"""


def _truncate_json(obj: Any, limit: int = 6000) -> str:
    text = json.dumps(obj, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _collect_keys(data: Any, out: set[str] | None = None) -> set[str]:
    """从测调返回收集可用字段路径（顶层键 + 一层点路径）。"""
    if out is None:
        out = set()
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            _collect_keys(data[0], out)
        return out
    if not isinstance(data, dict):
        return out
    for key in ("list", "data", "items", "rows", "info"):
        nested = data.get(key)
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            return _collect_keys(nested[0], out)
        if isinstance(nested, dict) and key == "info":
            return _collect_keys(nested, out)
    for k, v in data.items():
        name = str(k)
        if RESULT_FIELD_RE.fullmatch(name):
            out.add(name)
        if isinstance(v, dict):
            for sk in v:
                child = f"{name}.{sk}"
                if RESULT_FIELD_RE.fullmatch(child):
                    out.add(child)
    return out


def enrich_from_probe(chat_model, draft: dict, probe_args: dict, probe_data: Any,
                      *, max_columns: int = MAX_COLUMNS) -> tuple[dict, dict | None, list[str]]:
    """返回 (suggestion, skill|None, warnings)。suggestion 供前端智能 merge。"""
    form = draft if isinstance(draft, dict) else {}
    result = form.get("result") if isinstance(form.get("result"), dict) else {}
    model_params = form.get("model_params") if isinstance(form.get("model_params"), dict) else {}
    existing_fields = [str(f) for f in (result.get("fields") or []) if str(f).strip()]
    path_hint = str(form.get("path") or "").strip()
    inv = f"{form.get('invoke_service') or ''}.{form.get('invoke_method') or ''}".strip(".")
    if inv:
        path_hint = inv or path_hint
    prompt = ENRICH_PROMPT.format(
        max_columns=max_columns,
        name=str(form.get("name") or ""),
        summary=str(form.get("summary") or form.get("description") or ""),
        path_hint=path_hint or "—",
        kind=str(result.get("kind") or form.get("result_kind") or "list"),
        params=json.dumps(
            {k: {"label": (v or {}).get("label"), "description": (v or {}).get("description"),
                 "type": (v or {}).get("type"), "required": (v or {}).get("required")}
             for k, v in model_params.items() if isinstance(v, dict)},
            ensure_ascii=False,
        ) or "无",
        probe_args=_truncate_json(probe_args or {}, 2000),
        probe_data=_truncate_json(probe_data, 6000),
        fields=json.dumps(
            {f: (result.get("labels") or {}).get(f, "") for f in existing_fields},
            ensure_ascii=False,
        ) or "无",
    )
    out = complete_json(chat_model, [("system", "你只输出 JSON。"), ("human", prompt)])
    allowed_keys = _collect_keys(probe_data)
    for f in existing_fields:
        allowed_keys.add(f)

    suggestion: dict[str, Any] = {
        "name": "",
        "summary": "",
        "description": "",
        "result_kind": str(result.get("kind") or "list"),
        "fields": [],
        "list_columns": [],
        "params": {},
    }
    warnings: list[str] = []

    name = str(out.get("name") or "").strip()
    if NAME_RE.match(name):
        suggestion["name"] = name
    summary = str(out.get("summary") or "").strip()
    if summary:
        suggestion["summary"] = summary[:255]
    desc = str(out.get("description") or "").strip()
    if desc:
        suggestion["description"] = desc[:2000]
    kind = str(out.get("result_kind") or "").strip().lower()
    if kind in ("list", "object"):
        suggestion["result_kind"] = kind

    fields_out: list[dict[str, str]] = []
    raw_fields = out.get("fields") or []
    if isinstance(raw_fields, list):
        for item in raw_fields:
            if not isinstance(item, dict):
                continue
            field = str(item.get("field") or "").strip()
            label = str(item.get("label") or "").strip() or field
            if not field:
                continue
            if not RESULT_FIELD_RE.fullmatch(field):
                continue
            if allowed_keys and field not in allowed_keys:
                continue
            fields_out.append({"field": field, "label": label[:64]})
            if len(fields_out) >= MAX_FIELDS:
                break
    # 若模型未给出有效字段，退回从样例推断
    if not fields_out and allowed_keys:
        for field in sorted(allowed_keys):
            if not RESULT_FIELD_RE.fullmatch(field):
                continue
            fields_out.append({"field": field, "label": field})
            if len(fields_out) >= MAX_FIELDS:
                break
    suggestion["fields"] = fields_out
    field_set = {f["field"] for f in fields_out}
    cols = [c for c in (out.get("list_columns") or []) if isinstance(c, str) and c in field_set][:max_columns]
    suggestion["list_columns"] = cols

    params_out: dict[str, dict[str, str]] = {}
    raw_params = out.get("params") or {}
    if isinstance(raw_params, dict):
        for key, val in raw_params.items():
            if key not in model_params:
                continue
            if isinstance(val, str) and val.strip():
                params_out[key] = {"label": "", "description": val.strip()[:200]}
            elif isinstance(val, dict):
                label = str(val.get("label") or "").strip()[:64]
                description = str(val.get("description") or "").strip()[:200]
                if label or description:
                    params_out[key] = {"label": label, "description": description}
    suggestion["params"] = params_out

    skill = None
    raw_skill = out.get("skill") if isinstance(out.get("skill"), dict) else None
    if raw_skill:
        skill_name = str(raw_skill.get("name") or "").strip()
        tool_name = suggestion["name"] or str(form.get("name") or "tool")
        examples = [str(e).strip()[:100] for e in (raw_skill.get("examples") or []) if str(e).strip()][:10]
        skill = {
            "name": skill_name if NAME_RE.match(skill_name) else (tool_name.removeprefix("query_") + "_skill")[:64],
            "display_name": str(raw_skill.get("display_name") or suggestion["summary"] or tool_name)[:128],
            "description": str(raw_skill.get("description") or suggestion["description"] or "")[:2000],
            "instructions": str(raw_skill.get("instructions") or "")[:2000],
            "examples": examples,
            "tools": [tool_name],
        }
    warnings.append("名称、说明、返回字段与配套 Skill 由模型生成，请检查后再保存")
    return suggestion, skill, warnings
