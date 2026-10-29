"""raw_json 信封：HTTP status < 400 时整段 JSON 即为 data，无业务 code。"""

from __future__ import annotations

import json

from oa_agent.connectors.base import ConnectorError
from oa_agent.integrations.office_api import business_hint
from oa_agent.observability.redact import redact_secrets


def _body_snippet(body: object, hint_max: int) -> str:
    """4xx 响应体片段：优先 msg 类字段，否则限长 JSON/文本（已脱敏）。"""
    hint = business_hint(body, hint_max)
    if hint:
        return hint
    if body is None:
        return ""
    if isinstance(body, str):
        text = body.strip()
    else:
        try:
            text = json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(body)
    text = " ".join(text.split())
    return redact_secrets(text, hint_max) if text else ""


def parse_raw_json(
    status_code: int,
    body: object,
    *,
    success_codes: set[str],
    hint_max: int,
    json_decode_ok: bool = True,
) -> tuple[object, str]:
    """返回 (data, 成功提示语)。失败抛 ConnectorError。"""
    _ = success_codes
    if status_code >= 400:
        hint = _body_snippet(body, hint_max) if status_code < 500 else ""
        raise ConnectorError(
            "UPSTREAM_HTTP_ERROR",
            f"上游 HTTP {status_code} {hint}".strip(),
            status_code,
            user_message=hint,
        )
    if not json_decode_ok:
        raise ConnectorError("UPSTREAM_BAD_RESPONSE", "上游返回非 JSON", status_code)
    if body is None:
        return {}, ""
    return body, ""
