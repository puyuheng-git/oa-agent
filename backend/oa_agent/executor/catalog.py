"""Tool / Skill 注册表（设计 §8、§13 P4）。

- Tool 来源：管理后台表单（source_file = "admin"），或从 openapi/*.yaml 的 operation（x-agent 扩展）导入。
  两者走同一套 规范化 → 校验 → 哈希 → 与当前版本比较：unchanged 不动；compatible 自动生效；
  breaking 存为待激活版本，需管理员激活。首次启动表为空时从文件导入一次，之后以后台为准。
- 文件解析/校验失败：该文件的 Tool 记录失败原因，保留最后有效版本（导入失败不覆盖）。
- 运行时注册表只包含：管理员启用 + 规范启用 + 低风险免确认 + GET 只读 + 有当前版本 的 Tool。
- Skill 声明说明、填参指引、示例问题与可用 Tool；依赖不可用时 Skill 校验失败，对话不会使用它。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa
import yaml
from sqlalchemy.orm import Session

from oa_agent.db.models import Skill, SkillVersion, Tool, ToolVersion
from oa_agent.db.types import utcnow
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM, UPSTREAM_KEY_RE
from oa_agent.executor.builtin_catalog import (
    TEXT_RESULT_FIELDS, TEXT_RESULT_KIND, builtin_model_params, ensure_builtin_tools,
)
from oa_agent.executor.registry import ToolRegistry, ToolSpec
from oa_agent.observability.redact import redact
from oa_agent.settings import REPO_ROOT

log = logging.getLogger(__name__)

OPENAPI_DIR = REPO_ROOT / "openapi"
SKILLS_DIR = REPO_ROOT / "skills"
PARAM_TYPES = {"string", "integer"}
IDENTITY_FIELDS = {"oa"}
RESULT_KINDS = {"list", "object"}
RISK_LEVELS = {"low", "medium", "high"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
ADMIN_SOURCE = "admin"
MAX_TEXT = 2000
MAX_EXAMPLES = 10

UNCHANGED, COMPATIBLE, BREAKING, INITIAL = "unchanged", "compatible", "breaking", "initial"


class SpecError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("；".join(errors))
        self.errors = errors


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


# ---------------- Tool：解析与规范化 ----------------

def _normalize_param(name: str, rule: Any, errors: list[str], op: str) -> dict:
    if not isinstance(rule, dict):
        errors.append(f"{op}.model_params.{name} 必须是对象")
        return {}
    out = {k: rule[k] for k in ("type", "format", "enum", "minimum", "maximum", "default", "required", "description",
                                "label", "enum_labels")
           if k in rule and rule[k] not in (None, "", [], {})}
    if out.get("type", "string") not in PARAM_TYPES:
        errors.append(f"{op}.model_params.{name}.type 只支持 string / integer")
    out.setdefault("type", "string")
    out["required"] = bool(out.get("required", False))
    if "enum" in out and not isinstance(out["enum"], list):
        errors.append(f"{op}.model_params.{name}.enum 必须是数组")
    if "enum_labels" in out:
        if not isinstance(out["enum_labels"], dict):
            errors.append(f"{op}.model_params.{name}.enum_labels 必须是 取值→名称 的对象")
        else:
            out["enum_labels"] = {str(k): str(v) for k, v in out["enum_labels"].items()}
    return out


def normalize_operation(api_path: str, method: str, op: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    name = op.get("operationId")
    if not isinstance(name, str) or not name.strip():
        return {}, [f"{method.upper()} {api_path} 缺少 operationId"]
    xa = op.get("x-agent") or {}
    if not isinstance(xa, dict):
        return {}, [f"{name}.x-agent 必须是对象"]
    risk = xa.get("risk_level", "low")
    if risk not in RISK_LEVELS:
        errors.append(f"{name}.risk_level 取值无效：{risk}")
    inject = list(xa.get("inject_identity_fields") or [])
    if not set(inject) <= IDENTITY_FIELDS:
        errors.append(f"{name}.inject_identity_fields 只允许 {sorted(IDENTITY_FIELDS)}")
    params_raw = xa.get("model_params") or {}
    if not isinstance(params_raw, dict):
        errors.append(f"{name}.model_params 必须是对象")
        params_raw = {}
    params = {k: _normalize_param(k, v, errors, name) for k, v in params_raw.items()}
    leaked = set(params) & IDENTITY_FIELDS
    if leaked:
        errors.append(f"{name}.model_params 不得包含身份字段 {sorted(leaked)}（身份只能由服务端注入）")
    result = xa.get("result") or {}
    kind = result.get("kind", "object")
    if kind not in RESULT_KINDS:
        errors.append(f"{name}.result.kind 只支持 list / object")
    fields = list(result.get("fields") or [])
    if not fields:
        errors.append(f"{name}.result.fields 不能为空（只返回白名单字段）")
    labels = result.get("labels") or {}
    if not isinstance(labels, dict):
        errors.append(f"{name}.result.labels 必须是 字段→名称 的对象")
        labels = {}
    labels = {str(k): str(v) for k, v in labels.items() if k in fields and v}
    columns = list(result.get("list_columns") or [])
    if not set(columns) <= set(fields):
        errors.append(f"{name}.result.list_columns 只能从返回字段中选择")
    query_field = xa.get("query_params_field")
    if inject and not query_field:
        errors.append(f"{name} 需要注入身份字段但未声明 query_params_field")
    identity_params = xa.get("identity_params") or {}
    if not isinstance(identity_params, dict):
        errors.append(f"{name}.identity_params 必须是 参数名→身份字段 的对象")
        identity_params = {}
    identity_params = {str(k): str(v) for k, v in identity_params.items()}
    for key, source in identity_params.items():
        if source not in IDENTITY_FIELDS:
            errors.append(f"{name}.identity_params.{key} 只能取 {sorted(IDENTITY_FIELDS)}")
        if key in params:
            errors.append(f"{name} 的身份参数 {key} 不能同时出现在模型可填参数中")
        if key == query_field:
            errors.append(f"{name} 的身份参数 {key} 不能与 JSON 参数字段同名")
    try:
        timeout = float(xa.get("timeout_seconds", 10))
        if not 0 < timeout <= 60:
            raise ValueError
    except (TypeError, ValueError):
        errors.append(f"{name}.timeout_seconds 必须在 (0, 60] 秒内")
        timeout = 10.0
    upstream = str(xa.get("upstream") or DEFAULT_UPSTREAM).strip()
    if not UPSTREAM_KEY_RE.fullmatch(upstream):
        errors.append(f"{name}.upstream 只能用小写字母、数字、下划线，以字母开头，2～32 位")
    spec = {
        "name": name,
        "method": method.upper(),
        "path": api_path,
        "summary": str(op.get("summary") or "")[:255],
        "description": str(xa.get("description") or "")[:MAX_TEXT],
        "spec_enabled": xa.get("enabled") is True,
        "risk_level": risk,
        "requires_confirmation": bool(xa.get("requires_confirmation")),
        "timeout_seconds": timeout,
        "inject_identity_fields": inject,
        "top_level_fields": list(xa.get("top_level_fields") or []),
        "query_params_field": query_field,
        "identity_params": identity_params,
        "model_params": params,
        "result": {"kind": kind, "fields": fields, "labels": labels,
                   "list_columns": [c for c in columns if c in fields]},
    }
    if upstream != DEFAULT_UPSTREAM:  # 默认值不写入，已有版本的哈希保持不变
        spec["upstream"] = upstream
    return spec, errors


def normalize_tool_form(form: dict) -> tuple[dict, list[str]]:
    """后台表单 → 与 OpenAPI 导入相同的规范化定义。表单只开放 GET 只读查询。"""
    name = str(form.get("name") or "").strip()
    errors: list[str] = []
    if not NAME_RE.match(name):
        errors.append("Tool 名只能用小写字母、数字、下划线，以字母开头，3～64 位")
    method = str(form.get("method") or "GET").upper()
    if method != "GET":
        errors.append("一期只支持 GET 只读查询接口（写操作需要员工确认流程）")
    path = str(form.get("path") or "").strip()
    if not path.startswith("/") or path.startswith("//") or " " in path or "://" in path:
        errors.append("接口路径必须是以 / 开头的相对路径（地址在「OA 对接」中配置，Tool 里只选地址）")
    result = form.get("result") or {}
    op = {
        "operationId": name,
        "summary": form.get("summary") or "",
        "x-agent": {
            "enabled": True,
            "description": form.get("description") or "",
            "upstream": form.get("upstream") or DEFAULT_UPSTREAM,
            "risk_level": form.get("risk_level") or "low",
            "requires_confirmation": bool(form.get("requires_confirmation")),
            "timeout_seconds": form.get("timeout_seconds", 10),
            "inject_identity_fields": form.get("inject_identity_fields") or [],
            "top_level_fields": form.get("top_level_fields") or [],
            "query_params_field": form.get("query_params_field") or None,
            "identity_params": form.get("identity_params") or {},
            "model_params": form.get("model_params") or {},
            "result": {"kind": result.get("kind") or "object", "fields": result.get("fields") or [],
                       "labels": result.get("labels") or {}, "list_columns": result.get("list_columns") or []},
        },
    }
    if not str(op["summary"]).strip():
        errors.append("请填写 Tool 名称说明（summary）")
    for key in [*(op["x-agent"]["model_params"] or {}), *(op["x-agent"]["result"]["fields"] or []),
                *(op["x-agent"]["identity_params"] or {})]:
        if not isinstance(key, str) or not FIELD_RE.match(key):
            errors.append(f"字段名 {key!r} 只能用字母、数字、下划线")
    spec, errs = normalize_operation(path or "/", method, op)
    return spec, errors + errs


def parse_openapi(path: Path) -> tuple[str, dict[str, dict]]:
    """返回 (规范版本, {operationId: 规范化定义})。任一错误抛 SpecError（整文件不生效）。"""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SpecError([f"无法解析 {path.name}：{type(exc).__name__}"]) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        raise SpecError([f"{path.name} 不是有效的 OpenAPI 文档（缺少 paths）"])
    version = str((doc.get("info") or {}).get("version", "0"))
    ops: dict[str, dict] = {}
    errors: list[str] = []
    for api_path, methods in doc["paths"].items():
        for method, op in (methods or {}).items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(op, dict):
                continue
            if "x-agent" not in op:
                continue
            spec, errs = normalize_operation(api_path, method, op)
            errors += errs
            if spec:
                if spec["name"] in ops:
                    errors.append(f"operationId 重复：{spec['name']}")
                ops[spec["name"]] = spec
    if errors:
        raise SpecError(errors)
    return version, ops


def schema_part(spec: dict) -> dict:
    """参与版本哈希的部分：spec_enabled 是开关而非契约，单独记录。"""
    return {k: v for k, v in spec.items() if k != "spec_enabled"}


# ---------------- 兼容性 ----------------

def compare(old: dict | None, new: dict) -> tuple[str, list[dict]]:
    if old is None:
        return INITIAL, []
    if canonical_hash(old) == canonical_hash(new):
        return UNCHANGED, []
    diff: list[dict] = []
    breaking = False

    def add(field_: str, change: str, before=None, after=None, is_breaking=False):
        nonlocal breaking
        breaking = breaking or is_breaking
        diff.append({"field": field_, "change": change, "old": before, "new": after, "breaking": is_breaking})

    for key in ("method", "path", "query_params_field", "risk_level", "requires_confirmation"):
        if old.get(key) != new.get(key):
            add(key, "changed", old.get(key), new.get(key), True)
    old_up, new_up = old.get("upstream", DEFAULT_UPSTREAM), new.get("upstream", DEFAULT_UPSTREAM)
    if old_up != new_up:
        add("upstream", "changed", old_up, new_up, True)
    for key in ("inject_identity_fields", "top_level_fields"):
        if old.get(key) != new.get(key):
            add(key, "changed", old.get(key), new.get(key), True)
    if (old.get("identity_params") or {}) != (new.get("identity_params") or {}):
        add("identity_params", "changed", old.get("identity_params"), new.get("identity_params"), True)
    for key in ("summary", "description", "timeout_seconds"):
        if old.get(key) != new.get(key):
            add(key, "changed", old.get(key), new.get(key))

    old_params, new_params = old.get("model_params") or {}, new.get("model_params") or {}
    for name in sorted(set(old_params) | set(new_params)):
        before, after = old_params.get(name), new_params.get(name)
        f = f"model_params.{name}"
        if after is None:
            add(f, "removed", before, None, True)
        elif before is None:
            add(f, "added", None, after, bool(after.get("required")))
        elif before != after:
            is_breaking = (
                before.get("type") != after.get("type")
                or (after.get("required") and not before.get("required"))
                or ("enum" in after and not set(before.get("enum") or after["enum"]) <= set(after["enum"]))
                or before.get("format") != after.get("format")
                or (after.get("maximum") is not None and (before.get("maximum") is None
                                                          or after["maximum"] < before["maximum"]))
                or (after.get("minimum") is not None and (before.get("minimum") is None
                                                          or after["minimum"] > before["minimum"]))
            )
            add(f, "changed", before, after, bool(is_breaking))

    old_res, new_res = old.get("result") or {}, new.get("result") or {}
    if old_res.get("kind") != new_res.get("kind"):
        add("result.kind", "changed", old_res.get("kind"), new_res.get("kind"), True)
    removed = [f for f in old_res.get("fields", []) if f not in new_res.get("fields", [])]
    added = [f for f in new_res.get("fields", []) if f not in old_res.get("fields", [])]
    if removed:
        add("result.fields", "removed", removed, None, True)
    if added:
        add("result.fields", "added", None, added)
    for key in ("labels", "list_columns"):
        if old_res.get(key) != new_res.get(key):
            add(f"result.{key}", "changed", old_res.get(key), new_res.get(key))
    return (BREAKING if breaking else COMPATIBLE), diff


# ---------------- Skill ----------------

def normalize_skill(doc: dict, where: str = "Skill") -> tuple[dict, list[str]]:
    errors = []
    name = doc.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name.strip()):
        errors.append(f"{where} 的 name 只能用小写字母、数字、下划线，以字母开头，3～64 位")
        name = str(name or "")
    tools = doc.get("tools")
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t.strip() for t in tools):
        errors.append(f"{where}.tools 必须是非空的 Tool 名数组")
        tools = []
    examples = doc.get("examples") or []
    if not isinstance(examples, list) or not all(isinstance(e, str) for e in examples):
        errors.append(f"{where}.examples 必须是字符串数组")
        examples = []
    examples = [e.strip()[:100] for e in examples if e.strip()]
    if len(examples) > MAX_EXAMPLES:
        errors.append(f"{where}.examples 最多 {MAX_EXAMPLES} 条")
    description = str(doc.get("description") or "").strip()
    if not description:
        errors.append(f"{where}.description 不能为空（模型据此判断何时使用该 Skill）")
    instructions = str(doc.get("instructions") or "")
    if len(description) > MAX_TEXT or len(instructions) > MAX_TEXT:
        errors.append(f"{where} 的说明和填参指引各不超过 {MAX_TEXT} 字")
    content = {
        "name": name.strip(),
        "display_name": str(doc.get("display_name") or name).strip()[:128],
        "description": description,
        "instructions": instructions.strip(),
        "examples": examples[:MAX_EXAMPLES],
        "workflow": str(doc.get("workflow") or ""),
        "tools": list(dict.fromkeys(t.strip() for t in tools)),
        "spec_enabled": doc.get("enabled", True) is True,
    }
    return content, errors


def parse_skill(path: Path) -> tuple[str, dict]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SpecError([f"无法解析 {path.name}：{type(exc).__name__}"]) from exc
    if not isinstance(doc, dict):
        raise SpecError([f"{path.name} 不是对象"])
    content, errors = normalize_skill(doc, path.name)
    if errors:
        raise SpecError(errors)
    return str(doc.get("version", "0")), content


# ---------------- 运行时视图 ----------------

def to_tool_spec(schema: dict, spec_version: str, version_no: int, schema_hash: str, *, kind: str = "office",
                 builtin_id: str | None = None, mcp_server_id: int | None = None,
                 mcp_tool_name: str | None = None, sandbox_policy: dict | None = None) -> ToolSpec:
    result = schema["result"]
    text_result = (kind or "office") != "office"  # mcp / builtin：结果统一为围栏文本 {"text": ...}
    return ToolSpec(
        kind=kind or "office",
        builtin_id=builtin_id,
        mcp_server_id=mcp_server_id,
        mcp_tool_name=mcp_tool_name,
        sandbox_policy=dict(sandbox_policy or {}),
        summary=schema.get("summary") or "",
        description=schema.get("description") or "",
        result_labels=dict(result.get("labels") or {}),
        list_columns=tuple(result.get("list_columns") or ()),
        name=schema["name"],
        method=schema["method"],
        path=schema["path"],
        version=f"{spec_version}#v{version_no}",
        schema_hash=schema_hash[:16],
        risk_level=schema["risk_level"],
        requires_confirmation=schema["requires_confirmation"],
        timeout_seconds=float(schema["timeout_seconds"]),
        inject_identity_fields=tuple(schema["inject_identity_fields"]),
        top_level_fields=tuple(schema["top_level_fields"]),
        query_params_field=schema.get("query_params_field"),
        identity_params=dict(schema.get("identity_params") or {}),
        upstream=schema.get("upstream") or DEFAULT_UPSTREAM,
        model_params=dict(schema["model_params"]),
        result_kind=TEXT_RESULT_KIND if text_result else schema["result"]["kind"],
        result_fields=TEXT_RESULT_FIELDS if text_result else tuple(schema["result"]["fields"]),
    )


TOOL_KINDS = ("office", "builtin", "mcp")


def _extension_tool_spec(tool: Tool) -> ToolSpec:
    """builtin / mcp Tool 没有 OpenAPI 版本：由 Tool 行直接生成运行时视图（调用面由 Executor 按 kind 分派）。"""
    return ToolSpec(
        name=tool.name, method="", path="", version=tool.kind, schema_hash="",
        risk_level=tool.risk_level or "low", requires_confirmation=bool(tool.requires_confirmation),
        timeout_seconds=10.0, inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params=builtin_model_params(tool.builtin_id) if tool.kind == "builtin" else {},
        result_kind=TEXT_RESULT_KIND, result_fields=TEXT_RESULT_FIELDS, summary=tool.summary or "",
        kind=tool.kind, builtin_id=tool.builtin_id, mcp_server_id=tool.mcp_server_id,
        mcp_tool_name=tool.mcp_tool_name, sandbox_policy=dict(tool.sandbox_policy_json or {}))


def registration_blockers(tool: Tool, has_version: bool, method: str | None = None) -> list[str]:
    kind = getattr(tool, "kind", None) or "office"
    if kind not in TOOL_KINDS:
        return [f"未知 Tool 类型：{kind}"]
    if kind != "office":
        reasons = []
        if not tool.enabled:
            reasons.append("管理员已停用")
        if kind == "builtin" and not tool.builtin_id:
            reasons.append("内置工具缺少 builtin_id")
        if kind == "mcp":
            if not tool.mcp_server_id:
                reasons.append("MCP 工具未绑定 MCP Server")
            if not tool.mcp_tool_name:
                reasons.append("MCP 工具缺少远端工具名")
        return reasons
    reasons = []
    if not tool.enabled:
        reasons.append("管理员已停用")
    if not tool.spec_enabled:
        reasons.append("规范未启用（x-agent.enabled 不为 true 或已从规范移除）")
    if tool.risk_level != "low" or tool.requires_confirmation:
        reasons.append("非低风险或需员工确认（一期只开放低风险只读，确认流待 OA 写操作 API）")
    if method and method.upper() != "GET":
        reasons.append("一期只执行 GET 只读接口")
    if not has_version:
        reasons.append("没有有效版本")
    return reasons


@dataclass
class SkillState:
    name: str
    enabled: bool
    valid: bool
    errors: list[str] = field(default_factory=list)
    display_name: str = ""
    description: str = ""
    instructions: str = ""
    examples: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    # Skill 首次版本入库时间；欢迎示例按近三天新加过滤
    created_at: datetime | None = None
    # 依赖 Tool 中「首次入库」时间的最大值（任一 Tool 近三天新加则示例可展示）
    newest_tool_created_at: datetime | None = None

    @property
    def available(self) -> bool:
        return self.enabled and self.valid


class Catalog:
    def __init__(self, session_factory: Callable[[], Session], tenant_id: str,
                 openapi_dir: Path = OPENAPI_DIR, skills_dir: Path = SKILLS_DIR):
        self._sf = session_factory
        self.tenant = tenant_id
        self.openapi_dir = openapi_dir
        self.skills_dir = skills_dir

    # ---- Tool 同步 ----
    def sync_tools(self, db: Session, operator: str) -> dict:
        report: dict = {"files": [], "tools": []}
        now = utcnow()
        for path in sorted(self.openapi_dir.glob("*.yaml")):
            existing = {t.name: t for t in db.scalars(sa.select(Tool).where(Tool.tenant_id == self.tenant,
                                                                           Tool.source_file == path.name))}
            try:
                spec_version, ops = parse_openapi(path)
            except SpecError as exc:
                msg = redact("；".join(exc.errors), 2000)
                report["files"].append({"file": path.name, "ok": False, "errors": exc.errors})
                for tool in existing.values():
                    tool.last_sync_at, tool.last_sync_result, tool.last_sync_error = now, "error", msg
                    report["tools"].append({"name": tool.name, "result": "error"})
                continue
            report["files"].append({"file": path.name, "ok": True, "errors": []})
            for name, spec in ops.items():
                report["tools"].append(self._sync_tool(db, path.name, spec_version, spec, operator, now))
            for name, tool in existing.items():
                if name not in ops:
                    tool.spec_enabled = False
                    tool.last_sync_at, tool.last_sync_result, tool.last_sync_error = now, "removed", None
                    report["tools"].append({"name": name, "result": "removed"})
        ensure_builtin_tools(db, self.tenant)  # 刷新时补齐缺失的内置工具（不覆盖管理员改动）
        return report

    def _sync_tool(self, db: Session, source: str, spec_version: str, spec: dict, operator: str, now) -> dict:
        schema = schema_part(spec)
        digest = canonical_hash(schema)
        tool = db.scalar(sa.select(Tool).where(Tool.tenant_id == self.tenant, Tool.name == spec["name"]))
        if tool is None:
            tool = Tool(tenant_id=self.tenant, name=spec["name"], source_file=source, enabled=True,
                        updated_by=operator)
            db.add(tool)
            db.flush()
        current = db.get(ToolVersion, tool.current_version_id) if tool.current_version_id else None
        pending = db.get(ToolVersion, tool.pending_version_id) if tool.pending_version_id else None
        tool.source_file, tool.summary, tool.spec_enabled = source, spec["summary"], spec["spec_enabled"]
        tool.last_sync_at, tool.last_sync_error = now, None
        level, diff = compare(current.schema_json if current else None, schema)
        if level == UNCHANGED:
            if pending is not None:  # 规范已回到当前版本：放弃待激活版本
                tool.pending_version_id = None
            self._apply_flags(tool, current.schema_json)
            tool.last_sync_result = UNCHANGED
            return {"name": tool.name, "result": UNCHANGED, "version_no": current.version_no}
        if pending is not None and pending.schema_hash == digest:
            tool.last_sync_result = "breaking_pending"
            return {"name": tool.name, "result": "breaking_pending", "version_no": pending.version_no}
        version_no = (db.scalar(sa.select(sa.func.max(ToolVersion.version_no))
                                .where(ToolVersion.tool_id == tool.id)) or 0) + 1
        version = ToolVersion(tool_id=tool.id, version_no=version_no, spec_version=spec_version, schema_json=schema,
                              schema_hash=digest, compat_level=level, diff_json=diff or None, created_by=operator,
                              created_at=now)
        db.add(version)
        db.flush()
        if level == BREAKING:
            tool.pending_version_id = version.id
            tool.last_sync_result = "breaking_pending"
        else:
            tool.current_version_id, tool.pending_version_id = version.id, None
            self._apply_flags(tool, schema)
            tool.last_sync_result = level
        tool.updated_by = operator
        return {"name": tool.name, "result": tool.last_sync_result, "version_no": version_no, "compat": level}

    @staticmethod
    def _apply_flags(tool: Tool, schema: dict) -> None:
        tool.risk_level = schema["risk_level"]
        tool.requires_confirmation = schema["requires_confirmation"]

    def activate_version(self, db: Session, tool: Tool, version_no: int, operator: str) -> ToolVersion:
        version = db.scalar(sa.select(ToolVersion).where(ToolVersion.tool_id == tool.id,
                                                         ToolVersion.version_no == version_no))
        if version is None:
            raise LookupError(version_no)
        tool.current_version_id = version.id
        if tool.pending_version_id == version.id:
            tool.pending_version_id = None
        self._apply_flags(tool, version.schema_json)
        tool.updated_by = operator
        return version

    # ---- Skill 同步 ----
    def sync_skills(self, db: Session, operator: str) -> dict:
        report: dict = {"files": [], "skills": []}
        now = utcnow()
        for path in sorted(self.skills_dir.glob("*.yaml")):
            existing = db.scalars(sa.select(Skill).where(Skill.tenant_id == self.tenant,
                                                         Skill.source_file == path.name)).all()
            try:
                spec_version, content = parse_skill(path)
            except SpecError as exc:
                report["files"].append({"file": path.name, "ok": False, "errors": exc.errors})
                for skill in existing:
                    skill.last_sync_at, skill.last_sync_result = now, "error"
                    skill.last_sync_error = redact("；".join(exc.errors), 2000)
                continue
            report["files"].append({"file": path.name, "ok": True, "errors": []})
            skill = self._save_skill(db, path.name, spec_version, content, operator, now)
            report["skills"].append({"name": skill.name, "result": skill.last_sync_result})
        db.flush()
        self.revalidate_skills(db)
        return report

    def _save_skill(self, db: Session, source: str, spec_version: str, content: dict, operator: str, now) -> Skill:
        skill = db.scalar(sa.select(Skill).where(Skill.tenant_id == self.tenant, Skill.name == content["name"]))
        if skill is None:
            skill = Skill(tenant_id=self.tenant, name=content["name"], enabled=True, updated_by=operator)
            db.add(skill)
            db.flush()
        body = {k: v for k, v in content.items() if k != "spec_enabled"}
        digest = canonical_hash(body)
        current = db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
        skill.source_file, skill.display_name = source, content["display_name"]
        skill.last_sync_at, skill.last_sync_error = now, None
        if current is not None and current.content_hash == digest:
            skill.last_sync_result = UNCHANGED
        else:
            version_no = (db.scalar(sa.select(sa.func.max(SkillVersion.version_no))
                                    .where(SkillVersion.skill_id == skill.id)) or 0) + 1
            version = SkillVersion(skill_id=skill.id, version_no=version_no, spec_version=spec_version,
                                   content_json=body, content_hash=digest, created_by=operator, created_at=now)
            db.add(version)
            db.flush()
            skill.current_version_id = version.id
            skill.last_sync_result = INITIAL if current is None else "updated"
            skill.updated_by = operator
        skill.validation_errors = None
        # spec 里的 enabled:false 视为规范停用，记为校验错误（不覆盖管理员开关）
        if not content["spec_enabled"]:
            skill.validation_errors = ["规范中 enabled 不为 true"]
        return skill

    # ---- 后台新建 / 编辑 ----
    def exists(self, db: Session, model, name: str) -> bool:
        return db.scalar(sa.select(model.id).where(model.tenant_id == self.tenant, model.name == name)) is not None

    def save_tool(self, db: Session, spec: dict, operator: str) -> dict:
        """后台保存：与文件导入同一套版本规则（兼容变更立即生效，不兼容变更待激活）。"""
        return self._sync_tool(db, ADMIN_SOURCE, ADMIN_SOURCE, spec, operator, utcnow())

    def save_skill(self, db: Session, content: dict, operator: str) -> Skill:
        skill = self._save_skill(db, ADMIN_SOURCE, ADMIN_SOURCE, content, operator, utcnow())
        db.flush()
        self.revalidate_skills(db)
        return skill

    def revalidate_skills(self, db: Session) -> None:
        registry = self.load_registry(db)
        for skill in db.scalars(sa.select(Skill).where(Skill.tenant_id == self.tenant)):
            errors = [e for e in (skill.validation_errors or []) if e.startswith("规范")]
            version = db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
            if version is None:
                errors.append("没有有效版本")
            else:
                for name in version.content_json.get("tools", []):
                    if registry.get(name) is None:
                        errors.append(f"依赖的 Tool {name} 未注册（不存在、已停用或无有效版本）")
            skill.validation_status = "invalid" if errors else "valid"
            skill.validation_errors = errors or None

    def tools_using_upstreams(self, db: Session, keep: set[str]) -> list[str]:
        """当前或待激活版本引用了 keep 之外地址的 Tool，返回「Tool 名（地址标识）」。"""
        used = []
        for tool in db.scalars(sa.select(Tool).where(Tool.tenant_id == self.tenant).order_by(Tool.name)):
            for vid in {tool.current_version_id, tool.pending_version_id} - {None}:
                upstream = (db.get(ToolVersion, vid).schema_json or {}).get("upstream", DEFAULT_UPSTREAM)
                if upstream not in keep:
                    used.append(f"{tool.name}（{upstream}）")
        return list(dict.fromkeys(used))

    # ---- 运行时 ----
    def load_registry(self, db: Session) -> ToolRegistry:
        tools: dict[str, ToolSpec] = {}
        rows = db.execute(
            sa.select(Tool, ToolVersion).outerjoin(ToolVersion, ToolVersion.id == Tool.current_version_id)
            .where(Tool.tenant_id == self.tenant)).all()
        for tool, version in rows:
            kind = tool.kind or "office"
            if kind == "office":
                if version is None or registration_blockers(tool, True, version.schema_json.get("method")):
                    continue
            elif registration_blockers(tool, version is not None):
                continue
            if version is None:  # builtin / mcp 无 OpenAPI 版本
                tools[tool.name] = _extension_tool_spec(tool)
                continue
            tools[tool.name] = to_tool_spec(
                version.schema_json, version.spec_version, version.version_no, version.schema_hash,
                kind=kind, builtin_id=tool.builtin_id, mcp_server_id=tool.mcp_server_id,
                mcp_tool_name=tool.mcp_tool_name, sandbox_policy=tool.sandbox_policy_json)
        return ToolRegistry(tools)

    def skill_states(self, db: Session) -> dict[str, SkillState]:
        states = {}
        tool_first = dict(db.execute(
            sa.select(Tool.name, sa.func.min(ToolVersion.created_at))
            .join(ToolVersion, ToolVersion.tool_id == Tool.id)
            .where(Tool.tenant_id == self.tenant)
            .group_by(Tool.name)).all())
        for s in db.scalars(sa.select(Skill).where(Skill.tenant_id == self.tenant).order_by(Skill.name)):
            version = db.get(SkillVersion, s.current_version_id) if s.current_version_id else None
            body = version.content_json if version else {}
            tools = list(body.get("tools") or [])
            skill_created = db.scalar(
                sa.select(sa.func.min(SkillVersion.created_at)).where(SkillVersion.skill_id == s.id))
            tool_ats = [tool_first[t] for t in tools if t in tool_first and tool_first[t] is not None]
            states[s.name] = SkillState(
                s.name, s.enabled, s.validation_status == "valid", list(s.validation_errors or []),
                display_name=s.display_name or s.name, description=body.get("description") or "",
                instructions=body.get("instructions") or "", examples=list(body.get("examples") or []),
                tools=tools, created_at=skill_created,
                newest_tool_created_at=max(tool_ats) if tool_ats else None)
        return states

    def bootstrap(self) -> None:
        """首次启动（表为空）时从仓库文件同步一次，保证开箱即用。"""
        with self._sf() as db, db.begin():
            if db.scalar(sa.select(sa.func.count()).select_from(Tool).where(Tool.tenant_id == self.tenant)) == 0:
                report = self.sync_tools(db, "system")
                log.info("首次同步 Tool：%s", [t["name"] for t in report["tools"]])
            if db.scalar(sa.select(sa.func.count()).select_from(Skill).where(Skill.tenant_id == self.tenant)) == 0:
                self.sync_skills(db, "system")
            ensure_builtin_tools(db, self.tenant)
