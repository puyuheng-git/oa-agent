"""Tool 执行器：参数校验 → 身份注入 → office-api（员工 token）→ 精简视图 → 事件。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date

from oa_agent.integrations.office_api import OfficeApiClient, OfficeApiError
from oa_agent.executor.registry import ToolRegistry, ToolSpec
from oa_agent.observability.events import RunRecorder

REMARK_LIMIT = 100
MCP_DROPPED_ARGS = frozenset({"oa", "authorization", "token", "office_token"})  # 身份只由服务端持有，不外传
MSG_NOT_AVAILABLE = "该功能未对你开放。"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ToolError(Exception):
    def __init__(self, code: str, message: str, http_status: int | None = None, user_message: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.user_message = user_message   # office-api 给员工的提示语（已清洗）

    @property
    def retryable(self) -> bool:
        """上游暂时性故障（超时/不可达/5xx），人工确认后重试可能成功。"""
        if self.code in ("UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE"):
            return True
        return self.code == "UPSTREAM_HTTP_ERROR" and (self.http_status or 0) >= 500


@dataclass
class Identity:
    """仅来自服务端会话；模型和客户端无法影响。"""

    oa: str
    authorization: str


def validate_args(spec: ToolSpec, args: dict) -> tuple[dict, list[str]]:
    """返回 (清洗后的参数, 被丢弃的字段)。身份字段与未声明字段一律丢弃。"""
    clean: dict = {}
    dropped = [k for k in args if k not in spec.model_params or k in spec.inject_identity_fields]
    for key, rule in spec.model_params.items():
        value = args.get(key)
        if value is None or value == "":
            if rule.get("required"):
                raise ToolError("INVALID_ARGUMENT", f"缺少参数 {key}")
            if "default" in rule:
                clean[key] = rule["default"]
            continue
        if rule.get("type") == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ToolError("INVALID_ARGUMENT", f"{key} 必须是整数") from None
            if "minimum" in rule and value < rule["minimum"]:
                raise ToolError("INVALID_ARGUMENT", f"{key} 不能小于 {rule['minimum']}")
            if "maximum" in rule and value > rule["maximum"]:
                value = rule["maximum"]  # 上限截断（如 limit ≤ 20）
        else:
            value = str(value).strip()
            if rule.get("format") == "date":
                if not DATE_RE.match(value):
                    raise ToolError("INVALID_ARGUMENT", f"{key} 必须是 YYYY-MM-DD")
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise ToolError("INVALID_ARGUMENT", f"{key} 不是有效日期") from None
        if "enum" in rule and value not in rule["enum"]:
            raise ToolError("INVALID_ARGUMENT", f"{key} 取值无效")
        clean[key] = value
    if clean.get("date_gte") and clean.get("date_lte") and clean["date_gte"] > clean["date_lte"]:
        raise ToolError("INVALID_ARGUMENT", "开始日期晚于结束日期")
    return clean, dropped


def build_request(spec: ToolSpec, args: dict, identity: Identity) -> dict:
    if not spec.query_params_field:  # 没有 JSON 参数字段时全部作为普通查询参数
        params = dict(args)
    else:
        params = {k: args[k] for k in spec.top_level_fields if k in args}
        qp = {k: v for k, v in args.items() if k not in spec.top_level_fields}
        for field in spec.inject_identity_fields:
            qp[field] = getattr(identity, field)
        params[spec.query_params_field] = json.dumps(qp, ensure_ascii=False, separators=(",", ":"))
    for name, field in spec.identity_params.items():  # 最后写入，覆盖任何同名参数
        params[name] = getattr(identity, field)
    return params


def _pick(row: dict, fields: tuple[str, ...], remark_limit: int = REMARK_LIMIT) -> dict:
    out = {f: row.get(f) for f in fields if f in row}
    if isinstance(out.get("remark"), str) and len(out["remark"]) > remark_limit:
        out["remark"] = out["remark"][:remark_limit] + "…"
    return out


def compact(spec: ToolSpec, data: object, args: dict, remark_limit: int = REMARK_LIMIT) -> dict:
    if spec.result_kind == "list":
        rows, total = _extract_list(data)
        return {"list": [_pick(r, spec.result_fields, remark_limit) for r in rows if isinstance(r, dict)],
                "total": total, "page": args.get("page", 1), "limit": args.get("limit", 10)}
    if isinstance(data, dict) and isinstance(data.get("info"), dict):
        data = data["info"]
    if not isinstance(data, dict) or not data:
        return {}
    return _pick(data, spec.result_fields, remark_limit)


def _extract_list(data: object) -> tuple[list, int]:
    if isinstance(data, list):
        return data, len(data)
    if isinstance(data, dict):
        for key in ("list", "data", "items", "rows"):
            if isinstance(data.get(key), list):
                rows = data[key]
                total = data.get("total", data.get("count", len(rows)))
                try:
                    return rows, int(total)
                except (TypeError, ValueError):
                    return rows, len(rows)
    raise ToolError("UPSTREAM_BAD_RESPONSE", "office-api 列表响应结构无法识别")


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, clients: dict[str, OfficeApiClient], remark_limit: int = REMARK_LIMIT,
                 *, mcp_client: object | None = None, builtin_runtime: object | None = None):
        """clients：地址标识 → office-api 客户端（见 office_api.upstream_clients）；mcp_client：出站 MCP 客户端；
        builtin_runtime：内置 Tool 运行时（None → 仅 time/calc 可用，export/memory 需注入带存储的运行时）。"""
        self.registry = registry
        self.clients = clients
        self.remark_limit = remark_limit
        self.mcp_client = mcp_client  # None → 未配置出站连接器（调用即「未对你开放」）
        self.builtin_runtime = builtin_runtime

    def _execute_builtin(self, spec: ToolSpec, args: dict, identity: Identity, rec: RunRecorder,
                         node_name: str) -> dict:
        """kind=builtin：由 BuiltinRuntime 执行；结果一律作为不可信数据围栏后回图（结构化结果不直接进模型）。"""
        from oa_agent.executor.builtin_runtime import BuiltinRuntime
        from oa_agent.security.prompt_guard import scan_flags, wrap_untrusted

        name = spec.name
        clean = {k: v for k, v in (args or {}).items() if k not in MCP_DROPPED_ARGS}
        rec.tool_call_count += 1
        rec.event("tool_call_start", node_name=node_name, tool_name=name, tool_version=spec.version,
                  input_summary={"arg_names": sorted(clean)},
                  metadata={"kind": "builtin", "builtin_id": spec.builtin_id})
        started = time.perf_counter()
        try:
            runtime = self.builtin_runtime or BuiltinRuntime()
            raw = runtime.call(spec, clean, identity=identity)
        except ToolError as exc:
            rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version,
                      status="error", duration_ms=int((time.perf_counter() - started) * 1000),
                      error_code=exc.code, error_summary=exc.message,
                      metadata={"kind": "builtin", "builtin_id": spec.builtin_id})
            raise
        raw = dict(raw)
        flags = {str(f) for f in (raw.pop("guard_flags", None) or [])}  # 运行时清洗阶段的标志；不回给模型
        body = json.dumps(raw, ensure_ascii=False, default=str)
        flags |= scan_flags(body)
        text = wrap_untrusted(body, source="builtin", name=name)
        rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version, status="ok",
                  duration_ms=int((time.perf_counter() - started) * 1000), output_summary={"result_count": 1},
                  metadata={"kind": "builtin", "builtin_id": spec.builtin_id,
                            **({"guard_flags": sorted(flags)} if flags else {})})
        return {"ok": True, "capability": name, "data": {"text": text}, "message": ""}

    def _execute_mcp(self, spec: ToolSpec, args: dict, identity: Identity, rec: RunRecorder, node_name: str) -> dict:
        """kind=mcp：默认由 MCP 服务端校验参数，这里丢弃身份字段；spec.model_params 非空时先本地校验；结果一律作为不可信数据围栏后回图。"""
        from oa_agent.executor.outbound import MAX_RESULT_BYTES, NoopOutboundMcpClient
        from oa_agent.security.prompt_guard import scan_flags, wrap_untrusted

        name = spec.name
        clean = {k: v for k, v in (args or {}).items() if k not in MCP_DROPPED_ARGS}
        rec.tool_call_count += 1
        rec.event("tool_call_start", node_name=node_name, tool_name=name, tool_version=spec.version,
                  input_summary={"arg_names": sorted(clean)}, metadata={"kind": "mcp"})
        started = time.perf_counter()
        try:
            if not spec.mcp_server_id or not spec.mcp_tool_name:
                raise ToolError("TOOL_NOT_AVAILABLE", f"MCP 工具未绑定连接：{name}", user_message=MSG_NOT_AVAILABLE)
            if spec.model_params:  # 仅声明了 model_params 才本地校验；同步来的 MCP Tool 为空（远端 input_schema 未映射）
                clean, _ = validate_args(spec, clean)
            client = self.mcp_client or NoopOutboundMcpClient()
            raw = client.call_tool(spec.mcp_tool_name, clean, identity=identity, server_id=spec.mcp_server_id)
        except ToolError as exc:
            rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version,
                      status="error", duration_ms=int((time.perf_counter() - started) * 1000),
                      error_code=exc.code, error_summary=exc.message, metadata={"kind": "mcp"})
            raise
        raw_text = str(raw.get("text") or "")
        flags = scan_flags(raw_text)
        text = wrap_untrusted(raw_text, source="mcp", name=name, max_chars=MAX_RESULT_BYTES)
        rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version, status="ok",
                  duration_ms=int((time.perf_counter() - started) * 1000),
                  output_summary={"result_count": 1, "truncated": bool(raw.get("truncated"))},
                  metadata={"kind": "mcp", **({"guard_flags": sorted(flags)} if flags else {})})
        # structured 不回图：它不经围栏，直接进模型会绕过不可信数据边界
        return {"ok": True, "capability": name, "data": {"text": text, "truncated": bool(raw.get("truncated"))},
                "message": ""}

    def execute(self, name: str, args: dict, identity: Identity, rec: RunRecorder, node_name: str) -> dict:
        spec = self.registry.get(name)
        if spec is None:
            raise ToolError("TOOL_NOT_AVAILABLE", f"Tool 未注册或未启用：{name}")
        if spec.kind == "mcp":
            return self._execute_mcp(spec, args, identity, rec, node_name)
        if spec.kind == "builtin":
            return self._execute_builtin(spec, args, identity, rec, node_name)
        clean, dropped = validate_args(spec, args)
        rec.tool_call_count += 1
        rec.event("tool_call_start", node_name=node_name, tool_name=name, tool_version=spec.version,
                  input_summary=clean,
                  metadata={"path": spec.path, "upstream": spec.upstream,
                            **({"dropped_fields": dropped} if dropped else {})})
        started = time.perf_counter()
        try:
            client = self.clients.get(spec.upstream)
            if client is None:
                raise ToolError("UPSTREAM_NOT_CONFIGURED", f"未配置 office-api 地址：{spec.upstream}")
            resp = client.get(spec.path, build_request(spec, clean, identity), identity.authorization,
                              timeout=spec.timeout_seconds)
            result = compact(spec, resp.data, clean, self.remark_limit)
        except (OfficeApiError, ToolError) as exc:
            rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version,
                      status="error", duration_ms=int((time.perf_counter() - started) * 1000),
                      error_code=exc.code, error_summary=exc.message,
                      metadata={"http_status": getattr(exc, "http_status", None)})
            raise ToolError(exc.code, exc.message, getattr(exc, "http_status", None),
                            getattr(exc, "user_message", "")) from exc
        count = len(result.get("list", [])) if spec.result_kind == "list" else (1 if result else 0)
        summary = {"result_count": count, "total": result.get("total")}
        rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version, status="ok",
                  duration_ms=resp.duration_ms, output_summary={**summary, "message": resp.message} if resp.message
                  else summary, metadata={"http_status": resp.http_status})
        return {"ok": True, "capability": name, "data": result, "message": resp.message}
