"""oa_office 信封：与 OfficeApiClient._unwrap 对齐的 {code, msg, data} 解析。"""

from __future__ import annotations

from oa_agent.connectors.base import ConnectorError
from oa_agent.integrations.office_api import business_hint
from oa_agent.integrations.open_oa import looks_like_login_hint


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
        # 透传上游文案（如「请重新从 OA 进入助手」），便于渠道层改写/续期
        hint = business_hint(body, hint_max) if isinstance(body, dict) or body is not None else ""
        raise ConnectorError(
            "OFFICE_TOKEN_EXPIRED",
            f"业务上游拒绝访问（HTTP {status_code}）{(' ' + hint) if hint else ''}".rstrip(),
            status_code,
            user_message=hint,
        )
    if status_code >= 400:
        hint = business_hint(body, hint_max) if status_code < 500 else ""
        raise ConnectorError(
            "UPSTREAM_HTTP_ERROR",
            f"业务上游 HTTP {status_code} {hint}".strip(),
            status_code,
            user_message=hint,
        )
    if not json_decode_ok:
        raise ConnectorError("UPSTREAM_BAD_RESPONSE", "上游返回非 JSON", status_code)
    if not isinstance(body, dict):
        return body, ""
    code = next((body[k] for k in ("code", "errCode", "err_code") if k in body), None)
    hint = business_hint(body, hint_max)
    if code is not None and str(code) not in success_codes:
        # HTTP 200 + 业务码「请登录」：与 401 同等视为员工票失效，触发续期而非原样甩给员工
        if looks_like_login_hint(hint):
            raise ConnectorError(
                "OFFICE_TOKEN_EXPIRED",
                f"业务上游登录失效 code={code} {hint}".strip(),
                status_code,
                user_message=hint,
            )
        raise ConnectorError(
            "UPSTREAM_BIZ_ERROR",
            f"业务上游业务错误 code={code} {hint}".strip(),
            status_code,
            user_message=hint,
        )
    return (body.get("data", body) if code is not None or "data" in body else body), hint
