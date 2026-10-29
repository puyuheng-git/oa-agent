"""oa_office 信封：与 OfficeApiClient._unwrap 对齐的 {code, msg, data} 解析。"""

from __future__ import annotations

from oa_agent.connectors.base import ConnectorError
from oa_agent.integrations.office_api import business_hint


def parse_oa_office(
    status_code: int,
    body: object,
    *,
    success_codes: set[str],
    hint_max: int,
    json_decode_ok: bool = True,
) -> tuple[object, str]:
    """返回 (data, 成功提示语)。失败抛 ConnectorError。"""
    if status_code in (401, 403):
        raise ConnectorError(
            "OFFICE_TOKEN_EXPIRED",
            f"office-api 拒绝访问（HTTP {status_code}）",
            status_code,
        )
    if status_code >= 400:
        hint = business_hint(body, hint_max) if status_code < 500 else ""
        raise ConnectorError(
            "UPSTREAM_HTTP_ERROR",
            f"office-api HTTP {status_code} {hint}".strip(),
            status_code,
            user_message=hint,
        )
    if not json_decode_ok:
        raise ConnectorError("UPSTREAM_BAD_RESPONSE", "office-api 返回非 JSON", status_code)
    if not isinstance(body, dict):
        return body, ""
    code = next((body[k] for k in ("code", "errCode", "err_code") if k in body), None)
    hint = business_hint(body, hint_max)
    if code is not None and str(code) not in success_codes:
        raise ConnectorError(
            "UPSTREAM_BIZ_ERROR",
            f"office-api 业务错误 code={code} {hint}".strip(),
            status_code,
            user_message=hint,
        )
    return (body.get("data", body) if code is not None or "data" in body else body), hint
