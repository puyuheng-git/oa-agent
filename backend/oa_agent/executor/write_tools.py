"""固定写 Workflow 白名单 Tool：仅 POST，只带 Authorization，不注入 oa query。

不进入 Catalog 自由注册表；规格以内联常量维护。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

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

# 固定 Workflow 可调用的写 Tool 名称
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


_WRITE_SPECS: dict[str, WriteToolSpec] = {
    "create_travel_expense_submit_draft": WriteToolSpec(
        name="create_travel_expense_submit_draft",
        path="/out_attendance/go_out_travel_expense/submit/draft",
        version="1.0.0",
        timeout_seconds=15,
        model_params={
            "source_expense_id": {
                "type": "integer", "minimum": 1, "required": True, "label": "行程报销单号",
            },
        },
        result_fields=("draft_id", "source_expense_id", "total_amount", "status", "status_text"),
        idempotent=False,
        summary="创建行程报销提交草稿",
    ),
    "submit_travel_expense_reimbursement": WriteToolSpec(
        name="submit_travel_expense_reimbursement",
        path="/out_attendance/go_out_travel_expense/submit",
        version="1.0.0",
        timeout_seconds=20,
        model_params={
            "draft_id": {
                "type": "integer", "minimum": 1, "required": True, "label": "草稿号",
            },
        },
        result_fields=("submit_id", "draft_id", "status", "status_text"),
        idempotent=True,
        summary="确认后提交行程报销",
    ),
}


def _parse_write_openapi() -> dict[str, WriteToolSpec]:
    """返回写 Tool 规格（历史名保留；现为内联常量，不再读 YAML）。"""
    missing = WRITE_TOOL_WHITELIST - _WRITE_SPECS.keys()
    if missing:
        raise ToolError("WRITE_SPEC_INVALID", f"写操作契约缺少：{', '.join(sorted(missing))}")
    return dict(_WRITE_SPECS)


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
                raise ToolError("UPSTREAM_NOT_CONFIGURED", f"未配置业务上游地址：{spec.upstream}")
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
