"""HTTP JSON Connector：委托现有 OfficeApiClient。"""

from __future__ import annotations

from typing import Any

from oa_agent.connectors.base import ConnectorError, ConnectorResult
from oa_agent.integrations.office_api import OfficeApiClient, OfficeApiError


class HttpJsonConnector:
    def __init__(self, connector_id: str, client: OfficeApiClient) -> None:
        self._connector_id = connector_id
        self._client = client

    @property
    def id(self) -> str:
        return self._connector_id

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
    ) -> ConnectorResult:
        try:
            if method.upper() == "GET":
                resp = self._client.get(path, params or {}, authorization, timeout)
            elif method.upper() == "POST":
                resp = self._client.post(
                    path,
                    json_body or {},
                    authorization,
                    timeout=timeout,
                    idempotency_key=idempotency_key,
                )
            else:
                raise ConnectorError("UPSTREAM_HTTP_ERROR", f"不支持的 HTTP 方法：{method}")
        except OfficeApiError as exc:
            raise ConnectorError(
                exc.code,
                exc.message,
                http_status=exc.http_status,
                user_message=exc.user_message,
            ) from exc
        return ConnectorResult(
            data=resp.data,
            http_status=resp.http_status,
            duration_ms=resp.duration_ms,
            message=resp.message,
        )
