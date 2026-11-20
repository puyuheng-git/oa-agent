"""根据已选 Tool 的契约，用小模型生成 Skill 表单草稿（管理员可改后再保存）。"""

from __future__ import annotations

import json
import re
from typing import Any

from oa_agent.executor.catalog import NAME_RE
from oa_agent.runtime.llm import ModelCallError, complete_json

PROMPT = """你是 OA Agent 的 Skill 文案助手。根据下列 Tool 契约，生成一个 Skill 草稿 JSON（不要 markdown）。

要求：
- name：小写字母开头，仅小写字母/数字/下划线，3～64 位，建议以 _skill 结尾或体现业务
- display_name：员工看到的中文短名
- description：这个能力解决什么问题（模型据此判断何时使用）
- instructions：如何把员工自然语言转成 Tool 参数（日期换算、枚举含义等）
- examples：3～8 条员工可能说的示例问法（中文短句）

只输出 JSON，字段：name, display_name, description, instructions, examples（字符串数组）。

Tool 列表：
{tools_json}
"""


def _tool_brief(schema: dict[str, Any]) -> dict[str, Any]:
    """送给模型的精简契约：不含示例敏感值。"""
    result = schema.get("result") if isinstance(schema.get("result"), dict) else {}
    raw_params = schema.get("model_params")
    params = raw_params if isinstance(raw_params, dict) else {}
    slim_params: dict[str, Any] = {}
    for k, rule in params.items():
        if not isinstance(rule, dict):
            continue
        slim_params[str(k)] = {
            "type": rule.get("type") or "string",
            "label": rule.get("label") or k,
            "required": bool(rule.get("required")),
            "description": (rule.get("description") or "")[:200],
        }
        if rule.get("enum") is not None:
            slim_params[str(k)]["enum"] = rule.get("enum")
        if rule.get("enum_labels"):
            slim_params[str(k)]["enum_labels"] = rule.get("enum_labels")
    # fields/labels 可能因历史契约写成非 dict/list，避免 TypeError 冒成 500
    raw_fields = result.get("fields") if isinstance(result, dict) else None
    if isinstance(raw_fields, list):
        fields = [str(f) for f in raw_fields[:30]]
    elif isinstance(raw_fields, dict):
        fields = [str(f) for f in list(raw_fields.keys())[:30]]
    else:
        fields = []
    raw_labels = result.get("labels") if isinstance(result, dict) else None
    labels = {str(k): str(v) for k, v in raw_labels.items()} if isinstance(raw_labels, dict) else {}
    return {
        "name": schema.get("name"),
        "summary": schema.get("summary") or "",
        "description": (schema.get("description") or "")[:500],
        "model_params": slim_params,
        "result": {
            "kind": (result.get("kind") if isinstance(result, dict) else None) or "object",
            "fields": fields,
            "labels": labels,
        },
        "invoke_service": schema.get("invoke_service") or "",
        "invoke_method": schema.get("invoke_method") or "",
    }


def _normalize_examples(raw: Any) -> list[str]:
    """模型可能返回数组、换行字符串或非法类型；统一成短句列表。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, (list, tuple)):
        items = [str(e).strip() for e in raw if str(e).strip()]
    else:
        items = []
    return [e[:100] for e in items][:10]


def draft_skill_from_tools(chat_model, tool_schemas: list[dict[str, Any]]) -> dict[str, Any]:
    """调用模型生成 Skill 草稿；校验 name，截断长度。"""
    if not tool_schemas:
        raise ModelCallError("未提供 Tool")
    briefs = [_tool_brief(s) for s in tool_schemas if isinstance(s, dict) and s.get("name")]
    if not briefs:
        raise ModelCallError("Tool 契约无效")
    prompt = PROMPT.format(tools_json=json.dumps(briefs, ensure_ascii=False, indent=2))
    out = complete_json(chat_model, [("system", "你只输出 JSON。"), ("human", prompt)])
    if not isinstance(out, dict):
        raise ModelCallError("模型输出不是 JSON 对象")
    name = str(out.get("name") or "").strip()
    if not NAME_RE.match(name):
        base = re.sub(r"[^a-z0-9_]+", "_", str(briefs[0].get("name") or "skill").lower()).strip("_")
        name = f"{base}_skill"[:64]
        if not NAME_RE.match(name):
            name = "new_skill"
    examples = _normalize_examples(out.get("examples"))
    tool_names = [str(b["name"]) for b in briefs]
    return {
        "name": name[:64],
        "display_name": str(out.get("display_name") or briefs[0].get("summary") or name)[:128],
        "description": str(out.get("description") or "")[:2000],
        "instructions": str(out.get("instructions") or "")[:2000],
        "examples": examples,
        "tools": tool_names,
    }
