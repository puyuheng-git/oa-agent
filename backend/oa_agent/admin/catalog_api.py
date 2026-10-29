"""/v1/admin/tools"v1/admin/skills：新"编辑、从文件导入、启停、版本与 diff（设"§9 ops.tool.manage / ops.skill.manage）"

变更提交后立即重载运行时注册表（停用即拒绝调用）；全部写操作带审计，审计与变更同事务"
后台编辑与文件导入走同一套校验与版本规则：兼容变更立即生效，不兼容变更存为待激活版本"
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from sqlalchemy.exc import SQLAlchemyError

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import McpServer, Skill, SkillVersion, Tool, ToolVersion
from oa_agent.errors import AppError
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM
from oa_agent.executor import apipost
from oa_agent.executor.builtin_catalog import TEXT_RESULT_FIELDS, TEXT_RESULT_KIND, builtin_guide
from oa_agent.executor.catalog import compare, normalize_skill, normalize_tool_form, registration_blockers
from oa_agent.executor.contract_test import contract_check, is_activatable
from oa_agent.executor.visibility import VisibilityService
from oa_agent.runtime.llm import ModelCallError, build_chat_model, resolve_model

tools_router = APIRouter(prefix="/v1/admin/tools", tags=["admin-tools"])
skills_router = APIRouter(prefix="/v1/admin/skills", tags=["admin-skills"])
visibility_router = APIRouter(prefix="/v1/admin/visibility", tags=["admin-skills"])

TOOL = "ops.tool.manage"
SKILL = "ops.skill.manage"

log = logging.getLogger(__name__)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


class ActivateIn(ReasonIn):
    version_no: int = Field(ge=1)


class ToolResultIn(BaseModel):
    kind: str = "object"
    fields: list[str] = Field(default_factory=list, max_length=100)
    labels: dict[str, str] = Field(default_factory=dict)
    list_columns: list[str] = Field(default_factory=list, max_length=20)


class ToolIn(ReasonIn):
    """后台表单只开"GET 只读、低风险、免确认的查"Tool"""

    name: str = Field(max_length=64)
    summary: str = Field(max_length=255)
    description: str = Field("", max_length=2000)
    method: str = "GET"
    upstream: str = Field(DEFAULT_UPSTREAM, max_length=32)
    path: str = Field(max_length=255)
    timeout_seconds: float = 10
    inject_identity_fields: list[str] = Field(default_factory=list)
    top_level_fields: list[str] = Field(default_factory=list)
    query_params_field: str | None = Field(None, max_length=64)
    identity_params: dict[str, str] = Field(default_factory=dict)
    model_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    result: ToolResultIn


class ApipostIn(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    use_llm: bool = True


class SkillIn(ReasonIn):
    name: str = Field(max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(max_length=2000)
    instructions: str = Field("", max_length=2000)
    examples: list[str] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(min_length=1, max_length=20)


class VisibilityRuleIn(BaseModel):
    effect: str = Field(max_length=8)
    principal_type: str = Field(max_length=16)
    principal_value: str = Field(default="", max_length=128)


class VisibilityPutIn(ReasonIn):
    rules: list[VisibilityRuleIn] = Field(default_factory=list, max_length=50)


def _reload(ctx: AdminCtx) -> None:
    engine = ctx.runtime.engine
    with ctx.runtime.session() as db, db.begin():
        engine.catalog.revalidate_skills(db)
    engine.reload_catalog()


# ---------------- Tool ----------------

def _get_tool(ctx: AdminCtx, name: str) -> Tool:
    tool = ctx.db.scalar(sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id, Tool.name == name))
    if tool is None:
        raise AppError(404, "NOT_FOUND", "Tool 不存")
    return tool


def _version_no(ctx: AdminCtx, version_id: int | None) -> int | None:
    if version_id is None:
        return None
    return ctx.db.scalar(sa.select(ToolVersion.version_no).where(ToolVersion.id == version_id))


def _mcp_server_label(ctx: AdminCtx, server_id: int | None) -> dict | None:
    if not server_id:
        return None
    row = ctx.db.get(McpServer, server_id)
    if row is None or row.tenant_id != ctx.runtime.tenant_id:
        return {"id": server_id, "name": None, "display_name": None, "transport": None, "missing": True}
    return {
        "id": row.id, "name": row.name, "display_name": row.display_name or row.name,
        "transport": row.transport, "enabled": row.enabled, "missing": False,
    }


def _office_guide(tool: Tool, schema: dict | None) -> dict:
    schema = schema or {}
    method = (schema.get("method") or "").upper() or None
    path = schema.get("path") or None
    upstream = schema.get("upstream") or DEFAULT_UPSTREAM
    return {
        "kind": "office",
        "summary": tool.summary or schema.get("summary") or "",
        "how": (
            "调用时由 ToolExecutor 用员工会话里的 OA token，向所选上游 office-api 发 HTTP；"
            "路径只存相对 path，完整 URL 由上游 base_url 拼出。业务授权与校验在 office-api / Service，"
            "本系统不访问 OA 业务库，模型输出不参与权限判定。"
        ),
        "constraints": [
            "身份字段由服务端注入，模型不可伪造 oa / token",
            "只允许契约内 method + path + 参数白名单",
            "结果按 result.fields 白名单回图",
        ],
        "http": {"method": method, "path": path, "upstream": upstream,
                 "timeout_seconds": schema.get("timeout_seconds")},
        "model_params": dict(schema.get("model_params") or {}),
        "identity_params": dict(schema.get("identity_params") or {}),
        "result": dict(schema.get("result") or {}),
        "runtime": "OfficeApiClient（员工 token）",
        "edit_hint": "可在本页编辑 method/path/参数与结果字段，并走版本激活。",
    }


def _mcp_guide(ctx: AdminCtx, tool: Tool, schema: dict | None) -> dict:
    schema = schema or {}
    mcp = dict(schema.get("mcp") or {})
    server = _mcp_server_label(ctx, tool.mcp_server_id)
    transport = (server or {}).get("transport")
    how = (
        "定义来自 MCP 服务器 tools/list 同步。调用时由 McpRuntime 按连接配置（stdio / SSE / HTTP）"
        "向远端 tools/call，把模型参数原样转发；结果围栏为文本块回图。"
        "连接密钥只写不读，不出现在错误信息与审计明文中。"
    )
    constraints = [
        "不能在本页改远端工具参数定义；请到「MCP 连接」改配置并重新同步",
        "默认停用，须管理员启用后才可注册到运行时",
        "员工身份不会自动注入到 MCP 参数（与 OA Tool 不同）",
    ]
    if transport == "stdio":
        constraints.append("stdio 在本机起子进程，环境变量密钥经 Vault 注入")
    elif transport in ("sse", "http"):
        constraints.append("出站 URL/Headers 由 MCP 连接配置；Headers 密钥经 Vault")
    return {
        "kind": "mcp",
        "summary": tool.summary or schema.get("summary") or schema.get("description") or "",
        "how": how,
        "constraints": constraints,
        "mcp_server": server,
        "mcp_tool_name": tool.mcp_tool_name or mcp.get("tool"),
        "description": (schema.get("description") or "")[:2000] or None,
        "model_params": dict(schema.get("model_params") or {}),
        "input_schema": mcp.get("input_schema"),
        "result": {
            "kind": TEXT_RESULT_KIND,
            "fields": list(TEXT_RESULT_FIELDS),
            "note": "MCP 原始返回会围栏为 text，不走 OA 字段白名单。",
        },
        "runtime": "McpRuntime（出站 MCP）",
        "edit_hint": "实现在远端 MCP 服务；本系统只同步清单与启停。",
    }


def _tool_guide(ctx: AdminCtx, tool: Tool, schema: dict | None) -> dict | None:
    kind = tool.kind or "office"
    if kind == "builtin":
        guide = builtin_guide(tool.builtin_id)
        if guide is None:
            return {
                "kind": "builtin",
                "builtin_id": tool.builtin_id,
                "summary": tool.summary or "",
                "how": "内置工具，实现位于 Agent 进程 BuiltinRuntime；目录中未找到对应 builtin_id。",
                "constraints": ["后台不能改实现代码"],
                "sandbox_policy": dict(tool.sandbox_policy_json or {}) or None,
                "runtime": "BuiltinRuntime（进程内）",
                "edit_hint": "请用启停与 Skill 绑定控制是否开放。",
            }
        guide = dict(guide)
        guide["sandbox_policy"] = dict(tool.sandbox_policy_json or {}) or guide.get("default_sandbox_policy")
        return guide
    if kind == "mcp":
        return _mcp_guide(ctx, tool, schema)
    return _office_guide(tool, schema)


def _tool_view(ctx: AdminCtx, tool: Tool) -> dict:
    current = ctx.db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
    schema = current.schema_json if current else {}
    blockers = registration_blockers(tool, current is not None, schema.get("method"))
    pending = ctx.db.get(ToolVersion, tool.pending_version_id) if tool.pending_version_id else None
    return {
        "name": tool.name, "kind": tool.kind or "office",
        "summary": tool.summary, "method": schema.get("method"), "path": schema.get("path"),
        "upstream": schema.get("upstream", DEFAULT_UPSTREAM) if current else None,
        "source_file": tool.source_file, "enabled": tool.enabled,
        "spec_enabled": tool.spec_enabled, "risk_level": tool.risk_level,
        "requires_confirmation": tool.requires_confirmation,
        "builtin_id": tool.builtin_id,
        "mcp_server_id": tool.mcp_server_id,
        "mcp_tool_name": tool.mcp_tool_name,
        "sandbox_policy": dict(tool.sandbox_policy_json or {}) or None,
        "registered": ctx.runtime.engine.registry.get(tool.name) is not None,
        "unregistered_reasons": blockers,
        "current_version_no": _version_no(ctx, tool.current_version_id),
        "pending_version_no": pending.version_no if pending else None,
        "pending_compat": pending.compat_level if pending else None,
        "last_sync_at": tool.last_sync_at, "last_sync_result": tool.last_sync_result,
        "last_sync_error": tool.last_sync_error, "updated_by": tool.updated_by, "updated_at": tool.updated_at,
    }


def _upstreams(ctx: AdminCtx) -> list[dict]:
    """Tool 可选的业务上游（只读视图，供表单下拉；配置在连接配置 → 业务上游 / 连接器）"""
    values = ctx.runtime.settings_svc.view(ctx.db, "oa")["values"]
    items = list(values.get("upstreams") or [])
    if items:
        return [{"key": u["key"], "label": u.get("label") or u["key"], "base_url": u.get("base_url")} for u in items]
    base = values.get("office_api_base_url") or values.get("mint_base_url")
    out = []
    if base:
        out.append({"key": DEFAULT_UPSTREAM, "label": "office-api", "base_url": base})
    out.extend(values.get("extra_upstreams") or [])
    return out


@tools_router.get("")
def list_tools(kind: Literal["office", "builtin", "mcp"] | None = None, ctx: AdminCtx = Depends(admin_read(TOOL))):
    stmt = sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id)
    if kind:
        stmt = stmt.where(Tool.kind == kind)
    tools = ctx.db.scalars(stmt.order_by(Tool.name)).all()
    oa = ctx.runtime.settings_svc.view(ctx.db, "oa")["values"]
    default_key = (oa.get("default_upstream_key") or DEFAULT_UPSTREAM).strip() or DEFAULT_UPSTREAM
    ups = _upstreams(ctx)
    if ups and default_key not in {u["key"] for u in ups}:
        default_key = ups[0]["key"]
    return {"items": [_tool_view(ctx, t) for t in tools], "upstreams": ups, "default_upstream_key": default_key}


@tools_router.get("/{name}")
def tool_detail(name: str, ctx: AdminCtx = Depends(admin_read(TOOL))):
    tool = _get_tool(ctx, name)
    out = _tool_view(ctx, tool)
    versions = ctx.db.scalars(sa.select(ToolVersion).where(ToolVersion.tool_id == tool.id)
                              .order_by(ToolVersion.version_no.desc())).all()
    out["versions"] = [{"version_no": v.version_no, "spec_version": v.spec_version, "schema_hash": v.schema_hash[:16],
                        "compat_level": v.compat_level, "created_by": v.created_by, "created_at": v.created_at,
                        "is_current": v.id == tool.current_version_id, "is_pending": v.id == tool.pending_version_id}
                       for v in versions]
    current = next((v for v in versions if v.id == tool.current_version_id), None)
    schema = current.schema_json if current else None
    out["current_schema"] = schema
    out["guide"] = _tool_guide(ctx, tool, schema)
    return out


def _tool_version(ctx: AdminCtx, tool: Tool, no: int) -> ToolVersion:
    v = ctx.db.scalar(sa.select(ToolVersion).where(ToolVersion.tool_id == tool.id, ToolVersion.version_no == no))
    if v is None:
        raise AppError(404, "NOT_FOUND", f"版本 v{no} 不存")
    return v


@tools_router.get("/{name}/versions/{version_no}")
def tool_version(name: str, version_no: int, ctx: AdminCtx = Depends(admin_read(TOOL))):
    v = _tool_version(ctx, _get_tool(ctx, name), version_no)
    return {"version_no": v.version_no, "spec_version": v.spec_version, "schema": v.schema_json,
            "schema_hash": v.schema_hash, "compat_level": v.compat_level, "diff": v.diff_json,
            "created_by": v.created_by, "created_at": v.created_at}


@tools_router.get("/{name}/diff")
def tool_diff(name: str, from_no: int, to_no: int, ctx: AdminCtx = Depends(admin_read(TOOL))):
    tool = _get_tool(ctx, name)
    a, b = _tool_version(ctx, tool, from_no), _tool_version(ctx, tool, to_no)
    level, diff = compare(a.schema_json, b.schema_json)
    return {"from": from_no, "to": to_no, "compat_level": level, "changes": diff}


@tools_router.post("/sync")
def sync_tools(ctx: AdminCtx = Depends(admin_write(TOOL))):
    engine = ctx.runtime.engine
    with ctx.db.begin():
        report = engine.catalog.sync_tools(ctx.db, ctx.user.username)
        ctx.db.flush()
        engine.catalog.revalidate_skills(ctx.db)
        ctx.audit("tool.sync", "tool", "*", after={
            "files": [{"file": f["file"], "ok": f["ok"]} for f in report["files"]],
            "tools": report["tools"]})
    engine.reload_catalog()
    return report


def _save_tool(ctx: AdminCtx, body: ToolIn, create: bool) -> dict:
    spec, errors = normalize_tool_form(body.model_dump(exclude={"reason"}))
    if errors:
        raise AppError(422, "VALIDATION_ERROR", "".join(errors))
    engine = ctx.runtime.engine
    with ctx.db.begin():
        exists = engine.catalog.exists(ctx.db, Tool, spec["name"])
        if create and exists:
            raise AppError(409, "ALREADY_EXISTS", f"Tool {spec['name']} 已存在，请改为编")
        if not create and not exists:
            raise AppError(404, "NOT_FOUND", "Tool 不存")
        if exists and (_get_tool(ctx, spec["name"]).kind or "office") != "office":
            raise AppError(422, "VALIDATION_ERROR",
                           "内置 / MCP 工具不可改 method、path、builtin_id 等核心字段；请用启停开关或「MCP 连接」页同步")
        upstream = spec.get("upstream", DEFAULT_UPSTREAM)
        if upstream not in {u["key"] for u in _upstreams(ctx)}:
            raise AppError(422, "VALIDATION_ERROR", f"业务上游 {upstream} 未在「连接配置 → 业务上游 / 连接器」中配置")
        result = engine.catalog.save_tool(ctx.db, spec, ctx.user.username)
        ctx.db.flush()
        engine.catalog.revalidate_skills(ctx.db)
        ctx.audit("tool.create" if create else "tool.update", "tool", spec["name"],
                  after={"result": result["result"], "version_no": result.get("version_no"),
                         "method": spec["method"], "upstream": upstream, "path": spec["path"]}, reason=body.reason)
    engine.reload_catalog()
    return {**result, "tool": _tool_view(ctx, _get_tool(ctx, spec["name"]))}


def _draft_model(ctx: AdminCtx):
    """生成草稿用的模型（默认模型）；未配置返回 None"""
    rt = ctx.runtime
    try:
        with rt.session() as db:
            cfg = resolve_model(db, rt.vault, rt.tenant_id)
    except SQLAlchemyError:
        return None
    return build_chat_model(cfg) if cfg else None


@tools_router.post("/import/apipost")
def import_apipost(body: ApipostIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """"Apipost 分享链接生成 Tool 草稿（不保存）；管理员检查后再走新建 Tool"""
    cfg = ctx.runtime.settings_svc.effective(ctx.db, "import")
    ctx.db.rollback()
    columns = int(cfg.get("list_columns") or apipost.MAX_COLUMNS)
    try:
        issue_id, target_ids = apipost.parse_share_url(body.url, int(cfg.get("max_targets") or apipost.MAX_TARGETS))
        apis = apipost.fetch(issue_id, target_ids, timeout=float(cfg.get("timeout_seconds") or apipost.TIMEOUT),
                             max_bytes=int(cfg.get("max_kb") or apipost.MAX_BYTES // 1000) * 1000)
    except apipost.ApipostError as exc:
        raise AppError(422, "IMPORT_FAILED", exc.message) from None
    drafts, errors = [], []
    for api in apis:
        try:
            drafts.append(apipost.to_draft(api, columns))
        except apipost.ApipostError as exc:
            errors.append(exc.message)
    used_llm = False
    if body.use_llm and drafts:
        model = _draft_model(ctx)
        if model is None:
            for d in drafts:
                d["warnings"].append("未配置 LLM：名称、用途说明与配套 Skill 需手工填写")
        for d in drafts if model is not None else []:
            try:
                d["warnings"] += apipost.enrich(model, d, columns)
                used_llm = True
            except ModelCallError as exc:
                d["warnings"].append(f"模型补全失败（{exc}），已使用直接映射结")
    with ctx.db.begin():
        ctx.audit("tool.import_draft", "tool", "apipost", after={
            "issue_id": issue_id, "target_ids": target_ids, "drafts": [d["form"]["name"] for d in drafts],
            "errors": errors, "llm": used_llm})
    return {"drafts": drafts, "errors": errors}


@tools_router.post("")
def create_tool(body: ToolIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    return _save_tool(ctx, body, create=True)


@tools_router.put("/{name}")
def update_tool(name: str, body: ToolIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    if body.name != name:
        raise AppError(422, "VALIDATION_ERROR", "Tool 名创建后不能修改")
    return _save_tool(ctx, body, create=False)


def _toggle(ctx: AdminCtx, name: str, enabled: bool, reason: str) -> dict:
    with ctx.db.begin():
        tool = _get_tool(ctx, name)
        before = tool.enabled
        tool.enabled, tool.updated_by = enabled, ctx.user.username
        ctx.audit("tool.enable" if enabled else "tool.disable", "tool", name, before={"enabled": before},
                  after={"enabled": enabled}, reason=reason)
    _reload(ctx)
    return _tool_view(ctx, tool)


@tools_router.post("/{name}/enable")
def enable_tool(name: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    return _toggle(ctx, name, True, body.reason)


@tools_router.post("/{name}/disable")
def disable_tool(name: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    return _toggle(ctx, name, False, body.reason)


@tools_router.post("/{name}/activate")
def activate_tool_version(name: str, body: ActivateIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """激活指定版本：接受待激活的不兼容版本，或回退到历史版本"""
    engine = ctx.runtime.engine
    with ctx.db.begin():
        tool = _get_tool(ctx, name)
        version = _tool_version(ctx, tool, body.version_no)
        schema = version.schema_json or {}
        check = contract_check(schema)
        for warning in check.warnings:
            log.warning("Tool %s v%s 契约检查：%s", name, body.version_no, warning)
        if not is_activatable(schema):
            raise AppError(400, "CONTRACT_NOT_ACTIVATABLE", "契约检查未通过，不可激活该 Tool 版本")
        before = _version_no(ctx, tool.current_version_id)
        try:
            engine.catalog.activate_version(ctx.db, tool, body.version_no, ctx.user.username)
        except LookupError:
            raise AppError(404, "NOT_FOUND", f"版本 v{body.version_no} 不存在") from None
        ctx.audit("tool.activate", "tool", name, before={"version_no": before},
                  after={"version_no": body.version_no}, reason=body.reason)
    _reload(ctx)
    return _tool_view(ctx, tool)


# ---------------- Skill ----------------

def _get_skill(ctx: AdminCtx, name: str) -> Skill:
    skill = ctx.db.scalar(sa.select(Skill).where(Skill.tenant_id == ctx.runtime.tenant_id, Skill.name == name))
    if skill is None:
        raise AppError(404, "NOT_FOUND", "Skill 不存")
    return skill


def _skill_view(ctx: AdminCtx, skill: Skill) -> dict:
    current = ctx.db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
    tools = (current.content_json or {}).get("tools", []) if current else []
    registry = ctx.runtime.engine.registry
    return {
        "name": skill.name, "display_name": skill.display_name, "source_file": skill.source_file,
        "enabled": skill.enabled, "validation_status": skill.validation_status,
        "validation_errors": skill.validation_errors or [],
        "current_version_no": current.version_no if current else None,
        "workflow": (current.content_json or {}).get("workflow") if current else None,
        "description": (current.content_json or {}).get("description") if current else None,
        "instructions": (current.content_json or {}).get("instructions") or "" if current else "",
        "examples": (current.content_json or {}).get("examples") or [] if current else [],
        "tools": [{"name": t, "registered": registry.get(t) is not None} for t in tools],
        "last_sync_at": skill.last_sync_at, "last_sync_result": skill.last_sync_result,
        "last_sync_error": skill.last_sync_error, "updated_by": skill.updated_by, "updated_at": skill.updated_at,
    }


@skills_router.get("")
def list_skills(ctx: AdminCtx = Depends(admin_read(SKILL))):
    skills = ctx.db.scalars(sa.select(Skill).where(Skill.tenant_id == ctx.runtime.tenant_id)
                            .order_by(Skill.name)).all()
    return {"items": [_skill_view(ctx, s) for s in skills]}


@skills_router.get("/{name}")
def skill_detail(name: str, ctx: AdminCtx = Depends(admin_read(SKILL))):
    skill = _get_skill(ctx, name)
    out = _skill_view(ctx, skill)
    versions = ctx.db.scalars(sa.select(SkillVersion).where(SkillVersion.skill_id == skill.id)
                              .order_by(SkillVersion.version_no.desc())).all()
    out["versions"] = [{"version_no": v.version_no, "spec_version": v.spec_version, "content": v.content_json,
                        "content_hash": v.content_hash[:16], "created_by": v.created_by, "created_at": v.created_at}
                       for v in versions]
    return out


@skills_router.post("/sync")
def sync_skills(ctx: AdminCtx = Depends(admin_write(SKILL))):
    engine = ctx.runtime.engine
    with ctx.db.begin():
        report = engine.catalog.sync_skills(ctx.db, ctx.user.username)
        ctx.audit("skill.sync", "skill", "*", after={
            "files": [{"file": f["file"], "ok": f["ok"]} for f in report["files"]], "skills": report["skills"]})
    engine.reload_catalog()
    return report


def _save_skill(ctx: AdminCtx, body: SkillIn, create: bool) -> dict:
    content, errors = normalize_skill({**body.model_dump(exclude={"reason"}), "workflow": "oa_assistant"})
    if errors:
        raise AppError(422, "VALIDATION_ERROR", "".join(errors))
    engine = ctx.runtime.engine
    with ctx.db.begin():
        exists = engine.catalog.exists(ctx.db, Skill, content["name"])
        if create and exists:
            raise AppError(409, "ALREADY_EXISTS", f"Skill {content['name']} 已存在，请改为编")
        if not create and not exists:
            raise AppError(404, "NOT_FOUND", "Skill 不存")
        unknown = [t for t in content["tools"] if not engine.catalog.exists(ctx.db, Tool, t)]
        if unknown:
            raise AppError(422, "VALIDATION_ERROR", f"Tool 不存在：{', '.join(unknown)}")
        skill = engine.catalog.save_skill(ctx.db, content, ctx.user.username)
        ctx.audit("skill.create" if create else "skill.update", "skill", skill.name,
                  after={"result": skill.last_sync_result, "tools": content["tools"]}, reason=body.reason)
    engine.reload_catalog()
    return _skill_view(ctx, _get_skill(ctx, content["name"]))


@skills_router.post("")
def create_skill(body: SkillIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    return _save_skill(ctx, body, create=True)


@skills_router.put("/{name}")
def update_skill(name: str, body: SkillIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    if body.name != name:
        raise AppError(422, "VALIDATION_ERROR", "Skill 名创建后不能修改")
    return _save_skill(ctx, body, create=False)


def _toggle_skill(ctx: AdminCtx, name: str, enabled: bool, reason: str) -> dict:
    with ctx.db.begin():
        skill = _get_skill(ctx, name)
        before = skill.enabled
        skill.enabled, skill.updated_by = enabled, ctx.user.username
        ctx.audit("skill.enable" if enabled else "skill.disable", "skill", name, before={"enabled": before},
                  after={"enabled": enabled}, reason=reason)
    _reload(ctx)
    return _skill_view(ctx, skill)


@skills_router.post("/{name}/enable")
def enable_skill(name: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    return _toggle_skill(ctx, name, True, body.reason)


@skills_router.post("/{name}/disable")
def disable_skill(name: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    return _toggle_skill(ctx, name, False, body.reason)


def _rule_view(rule) -> dict:
    return {
        "effect": rule.effect,
        "principal_type": rule.principal_type,
        "principal_value": rule.principal_value,
        "created_by": rule.created_by,
        "created_at": rule.created_at,
    }


def _rules_snapshot(rules: list) -> list[dict]:
    return [{"effect": r.effect, "principal_type": r.principal_type, "principal_value": r.principal_value}
            for r in rules]


@skills_router.get("/{name}/visibility")
def get_skill_visibility(name: str, ctx: AdminCtx = Depends(admin_read(SKILL))):
    skill = _get_skill(ctx, name)
    rules = VisibilityService.list_rules(ctx.db, tenant_id=ctx.runtime.tenant_id, skill_id=skill.id)
    return {"name": skill.name, "rules": [_rule_view(r) for r in rules]}


@skills_router.put("/{name}/visibility")
def put_skill_visibility(name: str, body: VisibilityPutIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    raw_rules = [r.model_dump() for r in body.rules]
    try:
        for raw in raw_rules:
            VisibilityService._normalize_rule(raw)
    except ValueError as exc:
        raise AppError(422, "VALIDATION_ERROR", str(exc)) from None
    with ctx.db.begin():
        skill = _get_skill(ctx, name)
        before_rules = VisibilityService.list_rules(ctx.db, tenant_id=ctx.runtime.tenant_id, skill_id=skill.id)
        before = _rules_snapshot(before_rules)
        try:
            VisibilityService.replace_rules(
                ctx.db,
                tenant_id=ctx.runtime.tenant_id,
                skill_id=skill.id,
                rules=raw_rules,
                created_by=ctx.user.username,
            )
        except ValueError as exc:
            raise AppError(422, "VALIDATION_ERROR", str(exc)) from None
        after_rules = VisibilityService.list_rules(ctx.db, tenant_id=ctx.runtime.tenant_id, skill_id=skill.id)
        ctx.audit(
            "skill.visibility.update",
            "skill",
            name,
            before={"rules": before},
            after={"rules": _rules_snapshot(after_rules)},
            reason=body.reason,
        )
    return {"name": skill.name, "rules": [_rule_view(r) for r in after_rules]}


@visibility_router.get("/preview")
def visibility_preview(oa: str, ctx: AdminCtx = Depends(admin_read(SKILL))):
    from oa_agent.chat.service import visible_skills_for

    if not oa.strip():
        raise AppError(422, "VALIDATION_ERROR", "oa 不能为空")
    skills = visible_skills_for(ctx.runtime, oa.strip(), office_token="")
    return {"oa": oa.strip(), "skills": sorted(s.name for s in skills)}
