"""Tool 契约测试 stub：激活前检查样例请求/响应是否齐全。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContractCheckResult:
    passed: bool
    warnings: list[str]


def _has_sample(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list)):
        return len(value) > 0
    return True


def contract_check(schema: dict[str, Any] | None) -> ContractCheckResult:
    """有 sample_request 与 sample_response 视为契约测试通过；缺样例仅告警。"""
    schema = schema or {}
    warnings: list[str] = []
    has_req = _has_sample(schema.get("sample_request"))
    has_resp = _has_sample(schema.get("sample_response"))
    if not has_req and not has_resp:
        warnings.append("缺少 sample_request 与 sample_response，契约测试未执行（一期 GET 仍可激活）")
    elif not has_req:
        warnings.append("缺少 sample_request，契约测试未执行")
    elif not has_resp:
        warnings.append("缺少 sample_response，契约测试未执行")
    passed = has_req and has_resp
    return ContractCheckResult(passed=passed, warnings=warnings)


def is_activatable(schema: dict[str, Any] | None) -> bool:
    """可激活：GET 只读；或带 invoke_service/method 的 open-oa POST。"""
    schema = schema or {}
    method = str(schema.get("method") or "GET").upper()
    if method == "GET":
        return True
    if method == "POST" and str(schema.get("invoke_service") or "").strip() and str(schema.get("invoke_method") or "").strip():
        return True
    return False
