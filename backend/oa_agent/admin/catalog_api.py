"""/v1/admin/tools、/v1/admin/skills：新建/编辑、启停、版本与 diff（§9 ops.tool.manage / ops.skill.manage）。

变更提交后立即重载运行时注册表（停用即拒绝调用）；全部写操作带审计，审计与变更同事务。
兼容变更立即生效，不兼容变更存为待激活版本。
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from sqlalchemy.exc import SQLAlchemyError

from oa_agent.admin.wizard_temp_upload import save_wizard_temp_file
from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import McpServer, Skill, SkillVersion, SkillVisibilityRule, Tool, ToolVersion
from oa_agent.errors import AppError
from oa_agent.integrations.open_oa import (
    DEFAULT_UPSTREAM, INVOKE_PATH, LEGACY_UPSTREAM, OpenOaClient, OpenOaError, mint_base_url,
)
from oa_agent.executor import apipost
from oa_agent.executor.builtin_catalog import TEXT_RESULT_FIELDS, TEXT_RESULT_KIND, builtin_guide
from oa_agent.executor.catalog import (
    canonical_hash, compare, enabled_orphans_after_skill_tools, is_orphan_tool,
    iter_skill_tool_bindings,
    normalize_open_oa_catalog_item, normalize_skill, normalize_tool_form,
    recover_open_oa_invoke_schema, registration_blockers, skill_category_kind_errors,
)
# normalize_open_oa_catalog_item：向导 save 复用（由管理员填写的契约组装 Tool schema）
from oa_agent.executor.contract_test import contract_check, is_activatable
from oa_agent.executor.visibility import VisibilityService
from oa_agent.executor.invoke_args import unwrap_bag_args
from oa_agent.executor.skill_draft import draft_skill_from_tools
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


with warnings.catch_warnings():
    # 契约字段名即 schema，pydantic 会提示其遮蔽 BaseModel.schema（已弃用），此处有意为之
    warnings.filterwarnings("ignore", message='Field name "schema"')

    class ToolResultIn(BaseModel):
        kind: str = "object"
        fields: list[str] = Field(default_factory=list, max_length=100)
        labels: dict[str, str] = Field(default_factory=dict)
        list_columns: list[str] = Field(default_factory=list, max_length=20)
        schema: dict[str, Any] | None = None  # 可选：返回结构说明，由 normalize 递归规范化


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
    identity_bindings: list[dict[str, str]] | None = None
    top_level_fields: list[str] = Field(default_factory=list)
    query_params_field: str | None = Field(None, max_length=64)
    identity_params: dict[str, str] = Field(default_factory=dict)
    model_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    result: ToolResultIn
    invoke_service: str = Field("", max_length=128)
    invoke_method: str = Field("", max_length=128)
    invoke_call: str = Field("one_by_params", max_length=32)


class ApipostIn(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    use_llm: bool = True


class ExportWizardServiceIn(BaseModel):
    service: str = Field(min_length=1, max_length=128)


class ExportWizardDescribeIn(ExportWizardServiceIn):
    method: str = Field(min_length=1, max_length=128)


class ExportWizardProbeIn(ExportWizardDescribeIn):
    oa: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    call: str = Field(default="one_by_params", max_length=32)
    op: str = Field(default="read", max_length=16)
    idempotency_key: str = Field(default="", max_length=128)


class HttpProbeIn(BaseModel):
    """普通 HTTP Tool 测调：按表单契约 mint 测试员工身份并向所选上游发请求。"""

    oa: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    upstream: str = Field(default=DEFAULT_UPSTREAM, max_length=32)
    path: str = Field(min_length=1, max_length=255)
    method: str = Field(default="GET", max_length=8)
    timeout_seconds: float = Field(default=10, ge=1, le=60)
    inject_identity_fields: list[str] = Field(default_factory=list)
    identity_bindings: list[dict[str, str]] | None = None
    top_level_fields: list[str] = Field(default_factory=list)
    query_params_field: str | None = Field(None, max_length=64)
    identity_params: dict[str, str] = Field(default_factory=dict)
    model_params: dict[str, dict[str, Any]] = Field(default_factory=dict)


class EnrichSchemaIn(BaseModel):
    """测调成功后用默认 LLM 生成完整 Tool schema 候选。"""

    probe_args: dict[str, Any] = Field(default_factory=dict)
    probe_data: Any = None
    draft: dict[str, Any] = Field(default_factory=dict)
    include_skill: bool = True


class ExportWizardSaveIn(ReasonIn):
    """测通后入库；服务端会用同一参数再 probe 一次。"""

    service: str = Field(min_length=1, max_length=128)
    method: str = Field(min_length=1, max_length=128)
    oa: str = Field(min_length=1, max_length=64)
    args: dict[str, Any] = Field(default_factory=dict)
    call: str = Field(default="one_by_params", max_length=32)
    op: str = Field(default="read", max_length=16)
    risk: str = Field(default="low", max_length=16)
    name: str = Field(min_length=1, max_length=64)
    summary: str = Field(default="", max_length=255)
    model_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    result: ToolResultIn = Field(default_factory=ToolResultIn)
    idempotency_key: str = Field(default="", max_length=128)


class SkillIn(ReasonIn):
    name: str = Field(max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(max_length=2000)
    instructions: str = Field("", max_length=100_000)
    examples: list[str] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(min_length=1, max_length=20)
    # 空串不限制 Tool.kind；写入 content_json.category
    category: str = Field(default="", max_length=32)


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
            "调用时由 ToolExecutor 用员工会话里的 OA token，向所选业务上游发 HTTP；"
            "路径只存相对 path，完整 URL 由上游 base_url 拼出。业务授权与校验在上游 / Service，"
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
        "runtime": "业务上游 HTTP（员工 token）",
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
        "edit_hint": "实现在远端 MCP；本系统可改摘要、启停与删除，定义以 MCP 同步为准。",
    }


def _open_oa_invoke_guide(tool: Tool, schema: dict | None) -> dict:
    schema = schema or {}
    return {
        "kind": "open_oa_invoke",
        "summary": tool.summary or schema.get("summary") or "",
        "how": (
            "调用时由 ToolExecutor 以员工 token POST open-oa /agent/invoke，"
            "固定转发 invoke_service / invoke_method 到 Service ANew；身份由 open-oa 从 token 解析并强制本人。"
        ),
        "constraints": [
            "模型不可改 service/method，不可伪造 oa",
            "参数与返回字段以 catalog 契约为准，可再从清单覆盖导入",
            "写操作须确认 + Idempotency-Key（高风险默认不启用）",
        ],
        "http": {
            "method": "POST",
            "path": schema.get("path") or "/agent/invoke",
            "upstream": schema.get("upstream") or DEFAULT_UPSTREAM,
            "invoke_service": schema.get("invoke_service"),
            "invoke_method": schema.get("invoke_method"),
            "timeout_seconds": schema.get("timeout_seconds"),
        },
        "model_params": dict(schema.get("model_params") or {}),
        "result": dict(schema.get("result") or {}),
        "runtime": "OpenOaClient POST /agent/invoke",
        "edit_hint": "可在本页编辑契约，也可用「接入 Export 向导」覆盖；支持删除。",
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
                "edit_hint": "可改摘要、启停与删除；实现细节见代码 BuiltinRuntime。",
            }
        guide = dict(guide)
        guide["sandbox_policy"] = dict(tool.sandbox_policy_json or {}) or guide.get("default_sandbox_policy")
        return guide
    if kind == "mcp":
        return _mcp_guide(ctx, tool, schema)
    if kind == "open_oa_invoke":
        return _open_oa_invoke_guide(tool, schema)
    return _office_guide(tool, schema)


def _tool_view(ctx: AdminCtx, tool: Tool, *, skill_bound: bool | None = None) -> dict:
    current = ctx.db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
    schema = current.schema_json if current else {}
    blockers = registration_blockers(tool, current is not None, schema.get("method"))
    pending = ctx.db.get(ToolVersion, tool.pending_version_id) if tool.pending_version_id else None
    kind = tool.kind or "office"
    # builtin 不要求绑 Skill；其余未传入 skill_bound 时按引用表现算
    if skill_bound is None:
        skill_bound = kind == "builtin" or not is_orphan_tool(
            ctx.db, ctx.runtime.tenant_id, tool.name, kind,
        )
    return {
        "name": tool.name, "kind": kind,
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
        "skill_bound": bool(skill_bound),
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
        out.append({"key": DEFAULT_UPSTREAM, "label": "open-oa", "base_url": base})
    out.extend(values.get("extra_upstreams") or [])
    return out


@tools_router.get("")
def list_tools(kind: Literal["office", "open_oa_invoke", "builtin", "mcp"] | None = None,
               ctx: AdminCtx = Depends(admin_read(TOOL))):
    stmt = sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id)
    if kind:
        stmt = stmt.where(Tool.kind == kind)
    tools = ctx.db.scalars(stmt.order_by(Tool.name)).all()
    bindings = iter_skill_tool_bindings(ctx.db, ctx.runtime.tenant_id)
    oa = ctx.runtime.settings_svc.view(ctx.db, "oa")["values"]
    default_key = (oa.get("default_upstream_key") or DEFAULT_UPSTREAM).strip() or DEFAULT_UPSTREAM
    ups = _upstreams(ctx)
    if ups and default_key not in {u["key"] for u in ups}:
        default_key = ups[0]["key"]
    items = []
    for t in tools:
        kind_val = t.kind or "office"
        bound = kind_val == "builtin" or t.name in bindings
        items.append(_tool_view(ctx, t, skill_bound=bound))
    return {"items": items, "upstreams": ups, "default_upstream_key": default_key}


@tools_router.get("/orphans")
def list_orphan_tools(ctx: AdminCtx = Depends(admin_read(TOOL))):
    """未出现在任何 Skill 当前 tools 里的非 builtin Tool。

    必须注册在 /{name} 之前，否则 orphans 会被当成 Tool 名。
    """
    bindings = iter_skill_tool_bindings(ctx.db, ctx.runtime.tenant_id)
    tools = ctx.db.scalars(
        sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id).order_by(Tool.name)
    ).all()
    items = []
    for tool in tools:
        kind = tool.kind or "office"
        # builtin 允许不绑 Skill；已有引用的业务 Tool 也不是孤儿
        if kind == "builtin" or tool.name in bindings:
            continue
        items.append({"name": tool.name, "kind": kind, "enabled": bool(tool.enabled)})
    return {"items": items}


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


def _upstream_configured(ctx: AdminCtx, upstream: str) -> bool:
    """open_oa 与 office 互认：任一已配置即视为可用。"""
    keys = {u["key"] for u in _upstreams(ctx)}
    if upstream in keys:
        return True
    if upstream == DEFAULT_UPSTREAM and LEGACY_UPSTREAM in keys:
        return True
    if upstream == LEGACY_UPSTREAM and DEFAULT_UPSTREAM in keys:
        return True
    return False


def _save_tool(ctx: AdminCtx, body: ToolIn, create: bool) -> dict:
    engine = ctx.runtime.engine
    with ctx.db.begin():
        existing = None
        form_data = body.model_dump(exclude={"reason"})
        if not create:
            existing = ctx.db.scalar(
                sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id, Tool.name == body.name)
            )
            if existing is None:
                raise AppError(404, "NOT_FOUND", "Tool 不存")
            # 内置 / MCP：实现不在表单里，只改摘要等元数据
            if (existing.kind or "office") in ("builtin", "mcp"):
                before = {"summary": existing.summary}
                existing.summary = body.summary.strip()
                existing.updated_by = ctx.user.username
                ctx.audit(
                    "tool.update", "tool", existing.name,
                    before=before,
                    after={"summary": existing.summary, "kind": existing.kind or "builtin"},
                    reason=body.reason,
                )
                name = existing.name
                result = {"result": "updated"}
            else:
                # open-oa 调用：表单不展示 invoke；从当前或历史版本带回，避免被改成普通 GET
                if (existing.kind or "office") == "open_oa_invoke" and existing.current_version_id:
                    cur = ctx.db.get(ToolVersion, existing.current_version_id)
                    schema = (cur.schema_json if cur else None) or {}
                    schema, _ = recover_open_oa_invoke_schema(ctx.db, existing, schema)
                    if schema.get("invoke_service") and schema.get("invoke_method"):
                        form_data["invoke_service"] = schema["invoke_service"]
                        form_data["invoke_method"] = schema["invoke_method"]
                        form_data["method"] = "POST"
                        form_data["path"] = INVOKE_PATH
                existing = None  # 走下方契约保存
        if existing is None or create:
            spec, errors = normalize_tool_form(form_data)
            if errors:
                raise AppError(422, "VALIDATION_ERROR", "".join(errors))
            exists = engine.catalog.exists(ctx.db, Tool, spec["name"])
            if create and exists:
                raise AppError(409, "ALREADY_EXISTS", f"Tool {spec['name']} 已存在，请改为编")
            if not create and not exists:
                raise AppError(404, "NOT_FOUND", "Tool 不存")
            upstream = spec.get("upstream", DEFAULT_UPSTREAM)
            if not _upstream_configured(ctx, upstream):
                raise AppError(422, "VALIDATION_ERROR", f"业务上游 {upstream} 未在「连接配置 → 业务上游 / 连接器」中配置")
            result = engine.catalog.save_tool(ctx.db, spec, ctx.user.username)
            ctx.db.flush()
            engine.catalog.revalidate_skills(ctx.db)
            ctx.audit("tool.create" if create else "tool.update", "tool", spec["name"],
                      after={"result": result["result"], "version_no": result.get("version_no"),
                             "method": spec["method"], "upstream": upstream, "path": spec["path"]},
                      reason=body.reason)
            name = spec["name"]
    engine.reload_catalog()
    return {**result, "tool": _tool_view(ctx, _get_tool(ctx, name))}


def _delete_tool(ctx: AdminCtx, name: str, reason: str) -> dict:
    """删除 Tool 及其版本；依赖它的 Skill 会在重载后标为不可用。"""
    engine = ctx.runtime.engine
    with ctx.db.begin():
        tool = _get_tool(ctx, name)
        before = {
            "name": tool.name, "kind": tool.kind or "office", "summary": tool.summary,
            "enabled": tool.enabled,
        }
        versions = list(ctx.db.scalars(sa.select(ToolVersion).where(ToolVersion.tool_id == tool.id)).all())
        for v in versions:
            ctx.db.delete(v)
        ctx.db.delete(tool)
        ctx.db.flush()
        engine.catalog.revalidate_skills(ctx.db)
        ctx.audit("tool.delete", "tool", name, before=before, reason=reason)
    engine.reload_catalog()
    return {"ok": True, "name": name}


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


def _open_oa_wizard_client(ctx: AdminCtx) -> tuple[OpenOaClient, str]:
    """用 mint_base_url + gateway_secret 访问 open-oa 向导接口。"""
    from oa_agent.chat import service as chat_service

    oa = chat_service.load_settings(ctx.runtime, "oa")
    base = mint_base_url(oa)
    secret = oa.get("gateway_secret")
    if not base:
        raise AppError(503, "OPEN_OA_NOT_CONFIGURED", "未配置 open-oa 签发/业务地址（mint_base_url）")
    if not secret:
        raise AppError(503, "OPEN_OA_NOT_CONFIGURED", "未配置 AGENT_GATEWAY_SECRET")
    try:
        return OpenOaClient(base, oa.get("success_codes")), str(secret)
    except OpenOaError as exc:
        raise AppError(503, "OPEN_OA_NOT_CONFIGURED", exc.message) from exc


def _wizard_upstream_error(exc: OpenOaError) -> AppError:
    """向导/测调上游失败：优先展示上游真实错误；仅配置类问题才提示核对 mint/密钥。"""
    detail = (exc.user_message or exc.message or "").strip() or "未知错误"
    config_codes = {
        "OFFICE_API_NOT_CONFIGURED",
        "MINT_FAILED",
        "OPEN_OA_NOT_CONFIGURED",
    }
    # 登录/密钥类失败才附配置核对提示；业务/SQL/非 JSON 正文本身已是实际原因
    if exc.code in config_codes or "AGENT_GATEWAY_SECRET" in detail or "未配置" in detail:
        msg = f"调用 open-oa 失败：{detail}。请核对 mint_base_url 与 AGENT_GATEWAY_SECRET 是否与 open-oa 一致。"
    else:
        msg = f"调用业务接口失败：{detail}"
    return AppError(502, "IMPORT_FAILED", msg)


def _added_invoke_methods(ctx: AdminCtx, service: str) -> dict[str, str]:
    """当前租户已接入的 open_oa_invoke：invoke_method → tool.name。"""
    rows = ctx.db.scalars(
        sa.select(Tool).where(
            Tool.tenant_id == ctx.runtime.tenant_id,
            Tool.kind == "open_oa_invoke",
        )
    ).all()
    mapping: dict[str, str] = {}
    for tool in rows:
        current = ctx.db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
        schema = (current.schema_json if current else None) or {}
        inv_s = str(schema.get("invoke_service") or "").strip()
        inv_m = str(schema.get("invoke_method") or "").strip()
        if inv_s == service and inv_m:
            mapping[inv_m] = tool.name
    return mapping


@tools_router.post("/export-wizard/discover")
def export_wizard_discover(body: ExportWizardServiceIn, ctx: AdminCtx = Depends(admin_read(TOOL))):
    """向导：输入 a/b/c，列出 Export public 方法；并标记本系统已添加的方法。"""
    service = body.service.strip()
    client, secret = _open_oa_wizard_client(ctx)
    ctx.db.rollback()
    try:
        methods = client.discover_exports(service, gateway_secret=secret)
    except OpenOaError as exc:
        raise _wizard_upstream_error(exc) from exc
    added = _added_invoke_methods(ctx, service)
    enriched = []
    for raw in methods if isinstance(methods, list) else []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        name = str(item.get("name") or "").strip()
        tool_name = added.get(name)
        item["already_added"] = bool(tool_name)
        item["tool_name"] = tool_name
        enriched.append(item)
    return {"methods": enriched, "service": service}


@tools_router.post("/export-wizard/describe")
def export_wizard_describe(body: ExportWizardDescribeIn, ctx: AdminCtx = Depends(admin_read(TOOL))):
    """向导：选中方法后拉取参数/call 草稿。"""
    client, secret = _open_oa_wizard_client(ctx)
    ctx.db.rollback()
    try:
        draft = client.describe_export(body.service.strip(), body.method.strip(), gateway_secret=secret)
    except OpenOaError as exc:
        raise _wizard_upstream_error(exc) from exc
    return draft


@tools_router.post("/export-wizard/probe")
def export_wizard_probe(body: ExportWizardProbeIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """向导：指定测试员工试调。"""
    client, secret = _open_oa_wizard_client(ctx)
    ctx.db.rollback()
    call = body.call.strip() or "one_by_params"
    # 整包 call 摊平 params|data，避免业务方法多套一层
    args = unwrap_bag_args(call, dict(body.args or {}))
    try:
        data = client.probe_export(
            service=body.service.strip(),
            method=body.method.strip(),
            oa=body.oa.strip(),
            args=args,
            call=call,
            op=body.op.strip() or "read",
            gateway_secret=secret,
            idempotency_key=body.idempotency_key.strip(),
        )
    except OpenOaError as exc:
        raise _wizard_upstream_error(exc) from exc
    return {"data": data}


def _http_probe_spec(body: HttpProbeIn):
    """从表单契约片段构造临时 ToolSpec，供 build_request 与运行时一致。"""
    from oa_agent.executor.catalog import synthesize_identity_bindings, to_tool_spec

    path = body.path.strip()
    if not path.startswith("/") or path.startswith("//") or " " in path or "://" in path:
        raise AppError(422, "VALIDATION_ERROR", "接口路径必须是以 / 开头的相对路径")
    method = (body.method or "GET").upper()
    if method != "GET":
        raise AppError(422, "VALIDATION_ERROR", "HTTP 测调一期仅支持 GET")
    inject = [str(x) for x in (body.inject_identity_fields or []) if str(x).strip()]
    bindings = body.identity_bindings
    if bindings is None and inject:
        bindings = synthesize_identity_bindings(inject)
    schema = {
        "name": "http_probe_tmp",
        "summary": "http probe",
        "description": "",
        "method": method,
        "path": path,
        "upstream": (body.upstream or DEFAULT_UPSTREAM).strip() or DEFAULT_UPSTREAM,
        "risk_level": "low",
        "requires_confirmation": False,
        "timeout_seconds": float(body.timeout_seconds or 10),
        "inject_identity_fields": inject,
        "top_level_fields": [str(x) for x in (body.top_level_fields or []) if str(x).strip()],
        "query_params_field": (body.query_params_field or None),
        "identity_params": {str(k): str(v) for k, v in (body.identity_params or {}).items()},
        "identity_bindings": list(bindings or []),
        "model_params": dict(body.model_params or {}),
        "result": {"kind": "object", "fields": [], "labels": {}, "list_columns": []},
    }
    return to_tool_spec(schema, "probe", 0, "http-probe", kind="office")


@tools_router.post("/http-probe")
def http_probe(body: HttpProbeIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """普通 HTTP Tool 测调：mint 测试员工 token，按契约注入身份后请求所选上游。"""
    from oa_agent.chat import service as chat_service
    from oa_agent.executor.executor import Identity, ToolError, build_request, validate_args

    oa = body.oa.strip()
    if not oa:
        raise AppError(422, "VALIDATION_ERROR", "请填写测试员工 OA 账号")
    spec = _http_probe_spec(body)
    clients = chat_service.tool_clients(ctx.runtime)
    upstream = spec.upstream or DEFAULT_UPSTREAM
    client = clients.get(upstream) or clients.get(DEFAULT_UPSTREAM) or clients.get(LEGACY_UPSTREAM)
    if client is None:
        raise AppError(503, "UPSTREAM_NOT_CONFIGURED", f"未配置业务上游：{upstream}")
    oa_cfg = chat_service.load_settings(ctx.runtime, "oa")
    secret = oa_cfg.get("gateway_secret")
    mint_client = chat_service.office_client(ctx.runtime)
    ctx.db.rollback()
    try:
        minted = mint_client.mint(oa, secret)
    except OpenOaError as exc:
        raise AppError(502, "MINT_FAILED", f"签发测试员工令牌失败：{exc.message}") from exc
    identity = Identity(oa=minted.oa or oa, authorization=minted.authorization)
    try:
        clean, _ = validate_args(spec, dict(body.args or {}))
        params = build_request(spec, clean, identity)
        resp = client.get(spec.path, params, identity.authorization, timeout=spec.timeout_seconds)
    except ToolError as exc:
        raise AppError(422, exc.code, exc.message) from exc
    except OpenOaError as exc:
        detail = (exc.user_message or exc.message or "").strip() or "未知错误"
        raise AppError(502, "IMPORT_FAILED", f"调用业务接口失败：{detail}") from exc
    return {"data": resp.data}


@tools_router.post("/enrich-schema")
def enrich_schema(body: EnrichSchemaIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """测调成功后：用默认 LLM 生成完整 Tool schema 候选（不入库）。"""
    from oa_agent.executor.schema_enrich import enrich_from_probe

    model = _draft_model(ctx)
    if model is None:
        raise AppError(503, "LLM_NOT_CONFIGURED", "未配置默认对话模型，无法生成 Schema")
    ctx.db.rollback()
    try:
        suggestion, skill, warnings = enrich_from_probe(
            model, dict(body.draft or {}), dict(body.probe_args or {}), body.probe_data,
        )
    except ModelCallError as exc:
        raise AppError(502, "LLM_FAILED", f"模型补全失败：{exc}") from exc
    if not body.include_skill:
        skill = None
    with ctx.db.begin():
        ctx.audit(
            "tool.enrich_schema", "tool", str((body.draft or {}).get("name") or "draft"),
            after={"has_skill": bool(skill), "field_count": len((suggestion or {}).get("fields") or [])},
        )
    return {"suggestion": suggestion, "skill": skill, "warnings": warnings}


@tools_router.post("/export-wizard/upload-temp")
async def export_wizard_upload_temp(file: UploadFile = File(...), ctx: AdminCtx = Depends(admin_write(TOOL))):
    """向导：文件型参数测试用，上传到本机临时目录并返回 ref。"""
    # 读取并校验大小（空文件/超 20MB 拒绝）
    data = await file.read()
    if not data:
        raise AppError(400, "VALIDATION_ERROR", "空文件")
    if len(data) > 20 * 1024 * 1024:
        raise AppError(400, "VALIDATION_ERROR", "文件过大，上限 20MB")
    out = save_wizard_temp_file(data, file.filename or "file")
    # 审计：仅记元数据，不记路径外内容
    with ctx.db.begin():
        ctx.audit("tool.export_wizard_upload_temp", "tool", "export-wizard",
                  after={"filename": out["filename"], "sha256": out["sha256"], "size": out["size"]})
    return {"data": out}


@tools_router.post("/export-wizard/save")
def export_wizard_save(body: ExportWizardSaveIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """向导：用同一参数再 probe 一次，成功后写入 open_oa_invoke Tool。"""
    if not (body.result.fields or []):
        raise AppError(422, "VALIDATION_ERROR", "入库前须配置 result.fields")
    client, secret = _open_oa_wizard_client(ctx)
    ctx.db.rollback()
    call = body.call.strip() or "one_by_params"
    args = unwrap_bag_args(call, dict(body.args or {}))
    try:
        client.probe_export(
            service=body.service.strip(),
            method=body.method.strip(),
            oa=body.oa.strip(),
            args=args,
            call=call,
            op=body.op.strip() or "read",
            gateway_secret=secret,
            idempotency_key=body.idempotency_key.strip(),
        )
    except OpenOaError as exc:
        raise AppError(422, "PROBE_FAILED", f"测通失败，未入库：{exc.message}") from exc

    params_list = []
    for pname, rule in (body.model_params or {}).items():
        if not isinstance(rule, dict):
            continue
        # 落库不再保留整包袋名，避免 Agent 再套一层
        if call in ("one_by_params", "page_list") and pname in ("params", "data"):
            if rule.get("type") == "object" and isinstance(rule.get("properties"), dict):
                for ck, cv in rule["properties"].items():
                    if isinstance(cv, dict):
                        params_list.append({"name": str(ck), **cv})
            continue
        row = {"name": pname, **rule}
        params_list.append(row)
    item = {
        "service": body.service.strip(),
        "method": body.method.strip(),
        "tool_name": body.name.strip(),
        "summary": body.summary.strip() or body.name.strip(),
        "op": body.op.strip() or "read",
        "risk": body.risk.strip() or "low",
        "call": call,
        "params": params_list,
        "returns": {
            "kind": body.result.kind,
            "fields": list(body.result.fields or []),
            "labels": dict(body.result.labels or {}),
            "list_columns": list(body.result.list_columns or []),
            "schema": body.result.schema,
        },
    }
    spec, errs = normalize_open_oa_catalog_item(item)
    if errs or not spec:
        raise AppError(422, "VALIDATION_ERROR", "；".join(errs or ["契约无效"]))

    engine = ctx.runtime.engine
    with ctx.db.begin():
        result = engine.catalog.save_tool(ctx.db, spec, ctx.user.username)
        tool = ctx.db.scalar(
            sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id, Tool.name == spec["name"])
        )
        if tool is not None:
            tool.kind = "open_oa_invoke"
            tool.updated_by = ctx.user.username
        engine.catalog.revalidate_skills(ctx.db)
        ctx.audit(
            "tool.export_wizard_save",
            "tool",
            spec["name"],
            after={
                "result": result.get("result"),
                "version_no": result.get("version_no"),
                "service": spec.get("invoke_service"),
                "method": spec.get("invoke_method"),
                "call": spec.get("invoke_call"),
            },
            reason=body.reason,
        )
    engine.reload_catalog()
    return {
        "name": spec["name"],
        "result": result.get("result"),
        "version_no": result.get("version_no"),
        "kind": "open_oa_invoke",
    }


@tools_router.post("")
def create_tool(body: ToolIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    return _save_tool(ctx, body, create=True)


@tools_router.put("/{name}")
def update_tool(name: str, body: ToolIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    if body.name != name:
        raise AppError(422, "VALIDATION_ERROR", "Tool 名创建后不能修改")
    return _save_tool(ctx, body, create=False)


@tools_router.delete("/{name}")
def delete_tool(name: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    return _delete_tool(ctx, name, body.reason)


def _toggle(ctx: AdminCtx, name: str, enabled: bool, reason: str) -> dict:
    with ctx.db.begin():
        tool = _get_tool(ctx, name)
        # 允许未绑 Skill 时启用；对话只加载 Skill，未绑定 Tool 不会出现在对话候选里
        before = tool.enabled
        tool.enabled, tool.updated_by = enabled, ctx.user.username
        if enabled:
            ctx.runtime.engine.catalog.revalidate_skills(ctx.db)
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
        # open_oa_invoke：激活前尽量从历史补回 invoke，并允许 POST 激活
        schema, repaired = recover_open_oa_invoke_schema(ctx.db, tool, schema)
        if repaired:
            version.schema_json = schema
            if (tool.kind or "office") in ("office", "open_oa_invoke", None, ""):
                tool.kind = "open_oa_invoke"
        check = contract_check(schema)
        for warning in check.warnings:
            log.warning("Tool %s v%s 契约检查：%s", name, body.version_no, warning)
        if not is_activatable(schema):
            raise AppError(
                400, "CONTRACT_NOT_ACTIVATABLE",
                "契约检查未通过，不可激活该 Tool 版本（GET 只读，或 POST 且须含 invoke_service/method）",
            )
        before = _version_no(ctx, tool.current_version_id)
        try:
            engine.catalog.activate_version(ctx.db, tool, body.version_no, ctx.user.username)
        except LookupError:
            raise AppError(404, "NOT_FOUND", f"版本 v{body.version_no} 不存在") from None
        ctx.audit("tool.activate", "tool", name, before={"version_no": before},
                  after={"version_no": body.version_no, "repaired_invoke": repaired}, reason=body.reason)
    _reload(ctx)
    return _tool_view(ctx, tool)


class RepairOpenOaIn(ReasonIn):
    """修复损坏的 open_oa_invoke：可从历史恢复，或显式指定 ANew 目标。"""

    invoke_service: str | None = Field(default=None, max_length=128)
    invoke_method: str | None = Field(default=None, max_length=128)


@tools_router.post("/{name}/repair-open-oa")
def repair_open_oa_tool(name: str, body: RepairOpenOaIn, ctx: AdminCtx = Depends(admin_write(TOOL))):
    """把缺 invoke 的 open_oa_invoke Tool 修回可注册状态（就地修补当前版本）。"""
    with ctx.db.begin():
        tool = _get_tool(ctx, name)
        current = ctx.db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
        if current is None:
            raise AppError(404, "NOT_FOUND", "Tool 没有有效版本，请用「接入业务接口」重新入库")
        schema = dict(current.schema_json or {})
        inv_s = (body.invoke_service or "").strip()
        inv_m = (body.invoke_method or "").strip()
        source = "body"
        if not inv_s or not inv_m:
            schema, _ = recover_open_oa_invoke_schema(ctx.db, tool, schema)
            inv_s = str(schema.get("invoke_service") or "").strip()
            inv_m = str(schema.get("invoke_method") or "").strip()
            source = "history"
        if not inv_s or not inv_m:
            raise AppError(
                422, "VALIDATION_ERROR",
                "无法自动恢复：请传入 invoke_service / invoke_method，"
                "例如 out_attendance/go_out_application + searchApplicationList；"
                "或用「接入业务接口」按同名覆盖。",
            )
        schema["invoke_service"] = inv_s
        schema["invoke_method"] = inv_m
        schema["method"] = "POST"
        schema["path"] = INVOKE_PATH
        schema.setdefault("name", tool.name)
        schema.setdefault("summary", tool.summary or tool.name)
        schema.setdefault("risk_level", tool.risk_level or "low")
        schema.setdefault("requires_confirmation", bool(tool.requires_confirmation))
        current.schema_json = schema
        current.schema_hash = canonical_hash(schema)
        tool.kind = "open_oa_invoke"
        tool.spec_enabled = True
        tool.summary = schema.get("summary") or tool.summary
        tool.risk_level = schema["risk_level"]
        tool.requires_confirmation = bool(schema["requires_confirmation"])
        tool.pending_version_id = None
        tool.updated_by = ctx.user.username
        ctx.db.flush()
        ctx.runtime.engine.catalog.revalidate_skills(ctx.db)
        ctx.audit(
            "tool.repair_open_oa", "tool", name,
            after={"invoke_service": inv_s, "invoke_method": inv_m, "source": source},
            reason=body.reason,
        )
    _reload(ctx)
    view = _tool_view(ctx, _get_tool(ctx, name))
    if not view.get("registered"):
        raise AppError(
            422, "VALIDATION_ERROR",
            f"已写入 invoke，但仍未注册：{'；'.join(view.get('unregistered_reasons') or [])}",
        )
    return view


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
        "category": (current.content_json or {}).get("category") or "" if current else "",
        "description": (current.content_json or {}).get("description") if current else None,
        "instructions": (current.content_json or {}).get("instructions") or "" if current else "",
        "examples": (current.content_json or {}).get("examples") or [] if current else [],
        "tools": [{"name": t, "registered": registry.get(t) is not None} for t in tools],
        "last_sync_at": skill.last_sync_at, "last_sync_result": skill.last_sync_result,
        "last_sync_error": skill.last_sync_error, "updated_by": skill.updated_by, "updated_at": skill.updated_at,
    }


class SkillDraftFromToolsIn(BaseModel):
    """先选 Tool，再让小模型根据契约生成 Skill 表单草稿。"""

    tools: list[str] = Field(min_length=1, max_length=20)


def _draft_skill_model(ctx: AdminCtx):
    """优先 text/small；没有小模型则回落默认模型。复用请求 session，避免嵌套连接。"""
    rt = ctx.runtime
    try:
        # 读路径可能留下隐式事务；解析模型前先干净回滚
        ctx.db.rollback()
        cfg = resolve_model(ctx.db, rt.vault, rt.tenant_id, capability="text", model_tier="small")
        if cfg is None:
            cfg = resolve_model(ctx.db, rt.vault, rt.tenant_id)
        ctx.db.rollback()
    except Exception:  # noqa: BLE001 — vault/路由异常统一视为未配置，由上层给可操作提示
        log.exception("resolve draft skill model failed")
        return None
    if cfg is None:
        return None
    try:
        return build_chat_model(cfg)
    except Exception:  # noqa: BLE001 — 客户端构造失败也按未配置/不可用处理
        log.exception("build_chat_model for skill draft failed")
        return None


@skills_router.get("")
def list_skills(ctx: AdminCtx = Depends(admin_read(SKILL))):
    skills = ctx.db.scalars(sa.select(Skill).where(Skill.tenant_id == ctx.runtime.tenant_id)
                            .order_by(Skill.name)).all()
    return {"items": [_skill_view(ctx, s) for s in skills]}


@skills_router.post("/draft-from-tools")
def draft_skill_from_tools_api(body: SkillDraftFromToolsIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    """根据已选 Tool 当前契约，调用小模型生成 Skill 草稿（不落库）。"""
    names = [n.strip() for n in body.tools if n and n.strip()]
    if not names:
        raise AppError(422, "VALIDATION_ERROR", "请至少选择一个 Tool")
    schemas: list[dict] = []
    for name in names:
        tool = _get_tool(ctx, name)
        current = ctx.db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
        # schema_json 可能非 dict（坏数据）；兜底成空契约再补 name/summary
        raw = current.schema_json if current else None
        schema = dict(raw) if isinstance(raw, dict) else {}
        schema.setdefault("name", tool.name)
        if not schema.get("summary"):
            schema["summary"] = tool.summary or tool.name
        schemas.append(schema)
    model = _draft_skill_model(ctx)
    if model is None:
        raise AppError(422, "LLM_NOT_CONFIGURED", "未配置可用的文本模型（建议配置 text/small），无法自动生成")
    try:
        draft = draft_skill_from_tools(model, schemas)
    except ModelCallError as exc:
        raise AppError(422, "LLM_FAILED", f"模型生成失败：{exc}") from None
    except Exception as exc:  # noqa: BLE001 — 契约畸形等不得冒成 INTERNAL_ERROR
        log.exception("draft_skill_from_tools failed")
        raise AppError(422, "LLM_FAILED", f"模型生成失败：{type(exc).__name__}: {exc}") from None
    with ctx.db.begin():
        ctx.audit("skill.draft_from_tools", "skill", draft.get("name") or "*", after={
            "tools": names, "draft_name": draft.get("name")})
    return {"draft": draft}


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
        # 非空种类按已入库 Tool.kind 收紧；空种类不查
        if content.get("category"):
            kind_rows = ctx.db.scalars(
                sa.select(Tool).where(Tool.tenant_id == ctx.runtime.tenant_id, Tool.name.in_(list(content["tools"])))
            ).all()
            kind_by_name = {row.name: (row.kind or "office") for row in kind_rows}
            pairs = [(name, kind_by_name[name]) for name in content["tools"] if name in kind_by_name]
            kind_errors = skill_category_kind_errors(content["category"], pairs)
            if kind_errors:
                raise AppError(422, "VALIDATION_ERROR", "；".join(kind_errors))
        # 拿掉某 Tool 后若再无 Skill 引用、且该 Tool 仍启用，先让管理员改绑或禁用
        if not create:
            orphaned = enabled_orphans_after_skill_tools(
                ctx.db, ctx.runtime.tenant_id, content["name"], list(content["tools"]),
            )
            if orphaned:
                names = "、".join(orphaned)
                raise AppError(400, "TOOL_WOULD_BE_ORPHAN", f"请先改绑或先禁用 Tool：{names}")
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


def _delete_skill(ctx: AdminCtx, name: str, reason: str) -> dict:
    """删除目录 Skill、版本与可见性规则。"""
    engine = ctx.runtime.engine
    with ctx.db.begin():
        skill = _get_skill(ctx, name)
        before = {"name": skill.name, "display_name": skill.display_name, "enabled": skill.enabled}
        ctx.db.execute(
            sa.delete(SkillVisibilityRule).where(
                SkillVisibilityRule.tenant_id == ctx.runtime.tenant_id,
                SkillVisibilityRule.skill_id == skill.id,
            )
        )
        versions = list(ctx.db.scalars(sa.select(SkillVersion).where(SkillVersion.skill_id == skill.id)).all())
        for v in versions:
            ctx.db.delete(v)
        ctx.db.delete(skill)
        ctx.audit("skill.delete", "skill", name, before=before, reason=reason)
    engine.reload_catalog()
    return {"ok": True, "name": name}


@skills_router.delete("/{name}")
def delete_skill(name: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    return _delete_skill(ctx, name, body.reason)


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
