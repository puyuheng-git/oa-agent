"""Connector 抽象：统一上游 HTTP/业务调用边界（M1）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from oa_agent.observability.redact import redact


class ConnectorError(Exception):
    """与 OfficeApiError 同名字符串 code，便于 HttpJsonConnector 边界映射。

    code: OFFICE_API_NOT_CONFIGURED | UPSTREAM_TIMEOUT | UPSTREAM_UNAVAILABLE |
    UPSTREAM_HTTP_ERROR | UPSTREAM_BIZ_ERROR | UPSTREAM_BAD_RESPONSE |
    OFFICE_TOKEN_EXPIRED | MINT_FAILED

    user_message：上游给员工看的提示语（已清洗），可直接展示；为空时按错误码给通用提示。
    """

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int | None = None,
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = redact(message, 500)
        self.http_status = http_status
        self.user_message = user_message


@dataclass
class ConnectorResult:
    data: Any
    http_status: int
    duration_ms: int
    message: str = ""


@runtime_checkable
class Connector(Protocol):
    @property
    def id(self) -> str: ...

    def invoke(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        authorization: str,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> ConnectorResult: ...
