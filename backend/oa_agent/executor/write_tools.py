"""固定写 Workflow 白名单 Tool：仅 POST，只带 Authorization，不注入 oa query。

不进入 Catalog 自由注册表；规格来自 openapi/travel_expense_write.yaml。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from oa_agent.executor.executor import (
    Identity,
    ToolError,
    ToolSpec,
    authorization_for,
    validate_args,
    _pick,
    REMARK_LIMIT,
)
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM, OfficeApiClient, OfficeApiError
from oa_agent.observability.events import RunRecorder
from oa_agent.settings import REPO_ROOT

WRITE_OPENAPI = REPO_ROOT / "contracts" / "travel_expense_write.yaml"

# 固定 Workflow 可调用的写 Tool 名称（与契约 operationId 一致）
WRITE_TOOL_WHITELIST = frozenset({
    "create_travel_expense_submit_draft",
    "submit_travel_expense_reimbursement",
})


@dataclass(frozen=True)
class WriteToolSpec:
    name: str
    path: str
    version: str
    timeout_seconds: float
    model_params: dict
    result_fields: tuple[str, ...]
    idempotent: bool
    upstream: str = DEFAULT_UPSTREAM
    summary: str = ""


def _as_read_spec(spec: WriteToolSpec) -> ToolSpec:
    """复用 validate_args：无身份注入、无 query 拼接。"""
    return ToolSpec(
        name=spec.name,
        method="POST",
        path=spec.path,
        version=spec.version,
        schema_hash="write",
        risk_level="high",
        requires_confirmation=True,
        timeout_seconds=spec.timeout_seconds,
        inject_identity_fields=(),
        top_level_fields=(),
        query_params_field=None,
        model_params=dict(spec.model_params),
        result_kind="object",
        result_fields=spec.result_fields,
        summary=spec.summary,
        upstream=spec.upstream,
    )


def _parse_write_openapi(path: Path = WRITE_OPENAPI) -> dict[str, WriteToolSpec]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ToolError("WRITE_SPEC_INVALID", f"无法解析写操作契约：{type(exc).__name__}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("paths"), dict):
        raise ToolError("WRITE_SPEC_INVALID", "写操作契约缺少 paths")
    version = str((doc.get("info") or {}).get("version", "1"))
    tools: dict[str, WriteToolSpec] = {}
    for api_path, methods in doc["paths"].items():
        if not isinstance(methods, dict):
            continue
        post = methods.get("post")
        if not isinstance(post, dict):
            continue
        name = post.get("operationId")
        if not isinstance(name, str) or name not in WRITE_TOOL_WHITELIST:
            continue
        xa = post.get("x-agent") or {}
        if xa.get("enabled") is not True:
            continue
        params = xa.get("model_params") or {}
        result = xa.get("result") or {}
        fields = tuple(result.get("fields") or ())
        if not fields:
            raise ToolError("WRITE_SPEC_INVALID", f"{name} 缺少 result.fields")
        tools[name] = WriteToolSpec(
            name=name,
            path=api_path,
            version=version,
            timeout_seconds=float(xa.get("timeout_seconds") or 15),
            model_params={k: v for k, v in params.items() if isinstance(v, dict)},
            result_fields=fields,
            idempotent=bool(xa.get("idempotent")),
            upstream=str(xa.get("upstream") or DEFAULT_UPSTREAM),
            summary=str(post.get("summary") or "")[:255],
        )
    missing = WRITE_TOOL_WHITELIST - tools.keys()
    if missing:
        raise ToolError("WRITE_SPEC_INVALID", f"写操作契约缺少：{', '.join(sorted(missing))}")
    return tools


class WriteToolExecutor:
    def __init__(self, clients: dict[str, OfficeApiClient], specs: dict[str, WriteToolSpec] | None = None):
        self._specs = specs if specs is not None else _parse_write_openapi()
        self.clients = clients

    def get(self, name: str) -> WriteToolSpec | None:
        return self._specs.get(name)

    def execute(self, name: str, args: dict, identity: Identity, rec: RunRecorder, node_name: str,
                *, idempotency_key: str | None = None) -> dict:
        if name not in WRITE_TOOL_WHITELIST:
            raise ToolError("TOOL_NOT_AVAILABLE", f"写 Tool 不在白名单：{name}")
        spec = self._specs.get(name)
        if spec is None:
            raise ToolError("TOOL_NOT_AVAILABLE", f"写 Tool 未配置：{name}")
        clean, dropped = validate_args(_as_read_spec(spec), args)
        if spec.idempotent and not idempotency_key:
            raise ToolError("INVALID_ARGUMENT", "提交操作缺少 Idempotency-Key")
        rec.tool_call_count += 1
        rec.event("tool_call_start", node_name=node_name, tool_name=name, tool_version=spec.version,
                  input_summary=clean, metadata={"path": spec.path, "upstream": spec.upstream, "write": True,
                                                 **({"dropped_fields": dropped} if dropped else {})})
        started = time.perf_counter()
        try:
            client = self.clients.get(spec.upstream)
            if client is None:
                raise ToolError("UPSTREAM_NOT_CONFIGURED", f"未配置 office-api 地址：{spec.upstream}")
            # write clients 均来自 OA upstreams 信任域，可回落 office 员工票
            auth = authorization_for(identity, spec.upstream, allow_office_fallback=True)
            resp = client.post(spec.path, clean, auth, timeout=spec.timeout_seconds,
                               idempotency_key=idempotency_key if spec.idempotent else None)
            data = resp.data if isinstance(resp.data, dict) else {}
            picked = _pick(data, spec.result_fields, REMARK_LIMIT)
        except (OfficeApiError, ToolError) as exc:
            rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version,
                      status="error", duration_ms=int((time.perf_counter() - started) * 1000),
                      error_code=exc.code, error_summary=exc.message,
                      metadata={"http_status": getattr(exc, "http_status", None)})
            raise ToolError(exc.code, exc.message, getattr(exc, "http_status", None),
                            getattr(exc, "user_message", "")) from exc
        rec.event("tool_call_end", node_name=node_name, tool_name=name, tool_version=spec.version, status="ok",
                  duration_ms=resp.duration_ms, output_summary={"result_count": 1 if picked else 0,
                                                               "message": resp.message} if resp.message
                  else {"result_count": 1 if picked else 0}, metadata={"http_status": resp.http_status})
        return {"ok": True, "capability": name, "data": picked, "message": resp.message}
