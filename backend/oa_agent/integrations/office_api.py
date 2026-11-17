"""兼容层：请改用 ``oa_agent.integrations.open_oa``。本模块再导出原符号。"""

from __future__ import annotations

from oa_agent.integrations.open_oa import (  # noqa: F401
    DEFAULT_SUCCESS_CODES,
    DEFAULT_UPSTREAM,
    EXPORT_DESCRIBE_PATH,
    EXPORT_DISCOVER_PATH,
    EXPORT_PROBE_PATH,
    GATEWAY_SECRET_HEADER,
    INVOKE_PATH,
    LEGACY_UPSTREAM,
    MAX_HINT,
    MESSAGE_KEYS,
    MINT_PATH,
    UPSTREAM_KEY_RE,
    MintResult,
    OfficeApiClient,
    OfficeApiError,
    OfficeResponse,
    OpenOaClient,
    OpenOaError,
    OpenOaResponse,
    business_hint,
    employee_facing_error,
    looks_like_login_hint,
    mint_base_url,
    upstream_clients,
    upstream_connectors,
)
