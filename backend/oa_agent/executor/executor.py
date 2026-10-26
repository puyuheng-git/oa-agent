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
    def __init__(self, registry: ToolRegistry, clients: dict[str, OfficeApiClient], remark_limit: int = REMARK_LIMIT):
        """clients：地址标识 → office-api 客户端（见 office_api.upstream_clients）。"""
        self.registry = registry
        self.clients = clients
        self.remark_limit = remark_limit

    def execute(self, name: str, args: dict, identity: Identity, rec: RunRecorder, node_name: str) -> dict:
        spec = self.registry.get(name)
        if spec is None:
            raise ToolError("TOOL_NOT_AVAILABLE", f"Tool 未注册或未启用：{name}")
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
