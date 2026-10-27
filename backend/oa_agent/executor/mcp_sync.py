"""MCP `tools/list` → Tool 行 upsert（Task 7）。

- 新同步的 Tool 一律 `enabled=False`：须管理员在 Tool 管理中启用并绑到 Skill，才会进入运行时注册表。
- 名称：`<tool_prefix><远端名>`，规范化为小写下划线；与其它来源的同名 Tool 冲突时跳过并如实上报。
- 远端消失：无 Skill 引用 → 删除；仍被 Skill 引用 → 停用并写 `last_sync_error`（不静默删除依赖）。
- 每个 Tool 写一条 ToolVersion（含远端 input_schema），方便追溯远端契约变化。
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import McpServer, Skill, SkillVersion, Tool, ToolVersion
from oa_agent.db.types import utcnow
from oa_agent.executor.catalog import canonical_hash

TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
SYNC_SOURCE_PREFIX = "mcp:"


def local_tool_name(prefix: str, remote_name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", f"{prefix}{remote_name}".lower())


def _summary(remote: dict) -> str:
    text = " ".join(str(remote.get("description") or "").split())
    return (text or str(remote.get("name") or ""))[:255]


def _schema(local: str, remote: dict, server: McpServer) -> dict:
    return {
        "name": local, "method": "", "path": "", "summary": _summary(remote),
        "description": str(remote.get("description") or "")[:2000],
        "risk_level": "low", "requires_confirmation": False, "timeout_seconds": float(server.timeout_seconds or 30),
        "inject_identity_fields": [], "top_level_fields": [], "query_params_field": None, "identity_params": {},
        "model_params": {}, "result": {"kind": "object", "fields": [], "labels": {}, "list_columns": []},
        "mcp": {"server": server.name, "tool": remote.get("name"),
                "input_schema": remote.get("input_schema") or {"type": "object"}},
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
                          schema_hash=digest, compat_level="initial" if current is None else "compatible",
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
        changed = _write_version(db, tool, schema, operator, now)
        summary = _summary(remote)
        if tool.mcp_tool_name != remote["name"] or tool.summary != summary:
            tool.mcp_tool_name, tool.summary, changed = remote["name"], summary, True
        if outcome == "unchanged" and changed:
            outcome = "updated"
        tool.last_sync_at, tool.last_sync_result, tool.last_sync_error = now, outcome, None
        tool.updated_by = operator
        report[outcome].append(local)

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
