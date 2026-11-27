"""MCP `tools/list` → Tool 行 upsert。

- 新同步的 Tool 一律 `enabled=False`，并挂到该连接的 Server Skill（`mcp_<server.name>`）。
  对员工开放前不进运行时；开放由管理端把 `employee_open` 与 Tool.enabled 一起打开。
- 名称：`<tool_prefix><远端名>`，规范化为小写下划线；与其它来源的同名 Tool 冲突时跳过并如实上报。
- 远端消失：先从本连接 Skill 摘掉，再按其它 Skill 引用决定删除或停用（不静默删除仍被引用的依赖）。
- 每个 Tool 写一条 ToolVersion（含远端 input_schema），方便追溯远端契约变化。
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import McpServer, Skill, SkillVersion, Tool, ToolVersion
from oa_agent.db.types import utcnow
from oa_agent.executor.catalog import NAME_RE, canonical_hash

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SYNC_SOURCE_PREFIX = "mcp:"
SKILL_CATEGORY = "external_mcp"
_MCP_LETTERS = re.compile(r"mcp", re.IGNORECASE)


def local_tool_name(prefix: str, remote_name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", f"{prefix}{remote_name}".lower())


def server_skill_source(server_id: int) -> str:
    return f"mcp:server:{server_id}"


def mcp_skill_name(server_name: str) -> str:
    """稳定 Skill 名：`mcp_<server.name>`，非法字符换成 `_`，并落在 NAME_RE 内。"""
    raw = re.sub(r"[^a-z0-9_]", "_", f"mcp_{server_name}".lower())[:64]
    if NAME_RE.fullmatch(raw):
        return raw
    raw = re.sub(r"_+", "_", raw).strip("_")[:64]
    if not raw[:1].isalpha():
        raw = f"mcp_{raw}"[:64]
    if NAME_RE.fullmatch(raw):
        return raw
    return "mcp_server"


def _strip_mcp_letters(text: str) -> str:
    """去掉员工文案里的 MCP 字母，避免欢迎页露出连接协议名。"""
    cleaned = _MCP_LETTERS.sub("", text or "")
    cleaned = re.sub(r"[\s_\-]+", " ", cleaned)
    return cleaned.strip(" ：:「」\"'`-")


def employee_connection_display(server: McpServer) -> str:
    """员工看到的功能名。内部 Skill 名 mcp_<server> 不出现在这里。"""
    raw = (server.display_name or server.name or "").strip()
    cleaned = _strip_mcp_letters(raw) or "外部服务"
    return f"外部连接：{cleaned}"[:128]


def employee_connection_description(display: str) -> str:
    text = f"{display}提供的工具"
    if _MCP_LETTERS.search(text):
        text = _strip_mcp_letters(text) or "外部连接提供的工具"
    return text[:2000]


def ensure_mcp_server_skill(db: Session, tenant_id: str, server: McpServer, operator: str) -> Skill:
    """按 `mcp:server:<id>` 取或建 Server Skill。名称冲突时加上 server id，不覆盖别人的 Skill。"""
    source = server_skill_source(server.id)
    skill = db.scalar(sa.select(Skill).where(Skill.tenant_id == tenant_id, Skill.source_file == source))
    if skill is not None:
        return skill
    name = mcp_skill_name(server.name)
    taken = db.scalar(sa.select(Skill.id).where(Skill.tenant_id == tenant_id, Skill.name == name))
    if taken is not None:
        suffix = f"_{server.id}"
        name = f"{name[:64 - len(suffix)]}{suffix}"
        if not NAME_RE.fullmatch(name):
            name = f"mcp_srv_{server.id}"
    display = employee_connection_display(server)
    skill = Skill(tenant_id=tenant_id, name=name, display_name=display, source_file=source,
                  enabled=True, updated_by=operator)
    db.add(skill)
    db.flush()
    return skill


def _skill_content(skill: Skill, server: McpServer, names: set[str], previous: dict | None) -> dict:
    prev = previous or {}
    safe_display = employee_connection_display(server)
    prev_display = str(prev.get("display_name") or "").strip()
    # 已有且不含 MCP 字母的展示名留给管理员自定义；否则用「外部连接」文案
    if prev_display and not _MCP_LETTERS.search(prev_display):
        display = prev_display[:128]
    else:
        display = safe_display
    prev_desc = str(prev.get("description") or "").strip()
    if prev_desc and not _MCP_LETTERS.search(prev_desc):
        description = prev_desc
    else:
        description = employee_connection_description(display)
    examples = prev.get("examples") if isinstance(prev.get("examples"), list) else []
    return {
        "name": skill.name,
        "display_name": display,
        "description": description[:2000],
        "instructions": str(prev.get("instructions") or ""),
        "examples": [e for e in examples if isinstance(e, str)],
        "workflow": str(prev.get("workflow") or ""),
        "category": SKILL_CATEGORY,
        "tools": sorted(names),
    }


def _bind_skill_tools(db: Session, skill: Skill, server: McpServer, names: set[str], operator: str, now) -> None:
    """把本次仍存在的工具名写成该 Skill 的 tools；远端已消失的名字从本 Skill 摘掉。"""
    current = db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
    previous = current.content_json if current is not None else None
    body = _skill_content(skill, server, names, previous)
    digest = canonical_hash(body)
    skill.display_name = body["display_name"]
    skill.source_file = server_skill_source(server.id)
    skill.last_sync_at, skill.last_sync_error = now, None
    skill.updated_by = operator
    if current is not None and current.content_hash == digest:
        skill.last_sync_result = "unchanged"
        return
    version_no = (db.scalar(sa.select(sa.func.max(SkillVersion.version_no)).where(SkillVersion.skill_id == skill.id))
                  or 0) + 1
    version = SkillVersion(skill_id=skill.id, version_no=version_no, spec_version="mcp",
                           content_json=body, content_hash=digest, created_by=operator, created_at=now)
    db.add(version)
    db.flush()
    skill.current_version_id = version.id
    skill.last_sync_result = "initial" if current is None else "updated"


def _summary(remote: dict) -> str:
    text = " ".join(str(remote.get("description") or "").split())
    return (text or str(remote.get("name") or ""))[:255]


_PARAM_TYPES = frozenset({"string", "integer", "number", "boolean"})


def _input_schema(remote: dict) -> dict:
    raw = remote.get("input_schema") or remote.get("inputSchema") or {"type": "object"}
    return raw if isinstance(raw, dict) else {"type": "object"}


def _model_params_from_input_schema(schema: dict) -> dict[str, dict[str, Any]]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return {}
    required = {x for x in (schema.get("required") or []) if isinstance(x, str)}
    out: dict[str, dict[str, Any]] = {}
    for name, prop in props.items():
        if not isinstance(name, str) or not isinstance(prop, dict):
            continue
        typ = str(prop.get("type") or "string").lower()
        if typ not in _PARAM_TYPES:
            continue
        rule: dict[str, Any] = {"type": typ, "required": name in required}
        desc = prop.get("description")
        if isinstance(desc, str) and desc.strip():
            rule["description"] = desc.strip()[:200]
        out[name] = rule
    return out


def _schema(local: str, remote: dict, server: McpServer) -> dict:
    inp = _input_schema(remote)
    return {
        "name": local, "method": "", "path": "", "summary": _summary(remote),
        "description": str(remote.get("description") or "")[:2000],
        "risk_level": "low", "requires_confirmation": False, "timeout_seconds": float(server.timeout_seconds or 30),
        "inject_identity_fields": [], "top_level_fields": [], "query_params_field": None, "identity_params": {},
        "model_params": _model_params_from_input_schema(inp),
        "result": {"kind": "object", "fields": [], "labels": {}, "list_columns": []},
        "mcp": {"server": server.name, "tool": remote.get("name"), "input_schema": inp},
    }


def _skill_refs(db: Session, tenant_id: str) -> set[str]:
    used: set[str] = set()
    rows = db.execute(sa.select(SkillVersion.content_json).join(Skill, Skill.current_version_id == SkillVersion.id)
                      .where(Skill.tenant_id == tenant_id)).all()
    for (content,) in rows:
        used.update((content or {}).get("tools") or [])
    return used


def _write_version(db: Session, tool: Tool, schema: dict, operator: str, now) -> bool:
    digest = canonical_hash(schema)
    current = db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
    if current is not None and current.schema_hash == digest:
        return False
    version_no = (db.scalar(sa.select(sa.func.max(ToolVersion.version_no)).where(ToolVersion.tool_id == tool.id))
                  or 0) + 1
    version = ToolVersion(tool_id=tool.id, version_no=version_no, spec_version="mcp", schema_json=schema,
                          schema_hash=digest, compat_level="initial" if current is None else "updated",
                          created_by=operator, created_at=now)
    db.add(version)
    db.flush()
    tool.current_version_id = version.id
    return True


def sync_server_tools(db: Session, tenant_id: str, server: McpServer, remote_tools: list[dict], operator: str) -> dict[str, Any]:
    """在调用方事务内执行。返回 {created, updated, unchanged, removed, disabled, skipped}。"""
    now = utcnow()
    report: dict[str, Any] = {"created": [], "updated": [], "unchanged": [], "removed": [], "disabled": [],
                              "skipped": []}
    seen: set[str] = set()
    bound: set[str] = set()
    for remote in remote_tools:
        local = local_tool_name(server.tool_prefix or "", str(remote.get("name") or ""))
        if not TOOL_NAME_RE.fullmatch(local):
            report["skipped"].append({"name": local or str(remote.get("name")), "reason": "名称不合法（需 3～64 位，字母开头）"})
            continue
        if local in seen:
            report["skipped"].append({"name": local, "reason": "与本次同步中的另一工具重名"})
            continue
        seen.add(local)
        tool = db.scalar(sa.select(Tool).where(Tool.tenant_id == tenant_id, Tool.name == local))
        schema = _schema(local, remote, server)
        if tool is None:
            tool = Tool(tenant_id=tenant_id, name=local, kind="mcp", enabled=False, spec_enabled=True,
                        source_file=f"{SYNC_SOURCE_PREFIX}{server.name}", mcp_server_id=server.id,
                        mcp_tool_name=remote["name"], risk_level="low", requires_confirmation=False,
                        updated_by=operator)
            db.add(tool)
            db.flush()
            outcome = "created"
        elif tool.kind != "mcp" or tool.mcp_server_id != server.id:
            report["skipped"].append({"name": local, "reason": "已存在同名 Tool（来自其它来源），未覆盖"})
            continue
        else:
            outcome = "unchanged"
        bound.add(local)
        changed = _write_version(db, tool, schema, operator, now)
        summary = _summary(remote)
        if tool.mcp_tool_name != remote["name"] or tool.summary != summary:
            tool.mcp_tool_name, tool.summary, changed = remote["name"], summary, True
        if outcome == "unchanged" and changed:
            outcome = "updated"
        tool.last_sync_at, tool.last_sync_result, tool.last_sync_error = now, outcome, None
        tool.updated_by = operator
        report[outcome].append(local)

    # 先把本连接 Skill 收成「本次仍在的工具」，远端消失的工具才可能因无其它引用而被删除
    skill = ensure_mcp_server_skill(db, tenant_id, server, operator)
    _bind_skill_tools(db, skill, server, bound, operator, now)
    referenced = _skill_refs(db, tenant_id)
    gone = db.scalars(sa.select(Tool).where(Tool.tenant_id == tenant_id, Tool.kind == "mcp",
                                            Tool.mcp_server_id == server.id).order_by(Tool.name)).all()
    for tool in gone:
        if tool.name in seen:
            continue
        if tool.name in referenced:
            tool.enabled = False
            tool.last_sync_at, tool.last_sync_result = now, "removed"
            tool.last_sync_error = "远端已不再提供该工具，仍被 Skill 引用，已停用；请先调整相关 Skill"
            report["disabled"].append(tool.name)
        else:
            db.execute(sa.delete(ToolVersion).where(ToolVersion.tool_id == tool.id))
            db.delete(tool)
            report["removed"].append(tool.name)
    return report
