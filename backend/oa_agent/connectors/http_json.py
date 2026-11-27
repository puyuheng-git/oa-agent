"""HTTP JSON Connector：默认 oa_office 委托 OfficeApiClient；其它 profile 自管 httpx。"""

from __future__ import annotations

import time
from typing import Any

import httpx

from oa_agent.connectors.base import ConnectorError, ConnectorResult
from oa_agent.connectors.envelope import parse_envelope
from oa_agent.executor.param_wire import encode_query_string, encode_www_form
from oa_agent.integrations.office_api import (
    DEFAULT_SUCCESS_CODES,
    MAX_HINT,
    OfficeApiClient,
    OfficeApiError,
)


class HttpJsonConnector:
    def __init__(
        self,
        connector_id: str,
        client: OfficeApiClient | None = None,
        *,
        base_url: str | None = None,
        envelope_profile: str = "oa_office",
        success_codes: set[str] | list[str] | tuple[str, ...] | None = None,
        hint_max: int = MAX_HINT,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
        shares_employee_token: bool | None = None,
    ) -> None:
        self._connector_id = connector_id
        self._client = client
        self._envelope_profile = envelope_profile
        self._hint_max = hint_max
        self._transport = transport
        self._timeout = timeout
        # 仅 oa_office + 已有 client 时走委托，保证 M1 行为不变
        self._delegate = client is not None and envelope_profile == "oa_office"
        # 仅「委托 OfficeApiClient」的 OA upstreams peer 默认共享 mint 员工票；
        # raw_json / 独立 base_url connector 须显式凭证（或显式传 True）
        if shares_employee_token is None:
            self.shares_employee_token = self._delegate
        else:
            self.shares_employee_token = shares_employee_token

        if success_codes is not None:
            self._success_codes = {str(c) for c in success_codes}
        elif client is not None:
            self._success_codes = set(client.success_codes)
        else:
            self._success_codes = {str(c) for c in DEFAULT_SUCCESS_CODES}

        if base_url:
            self._base_url: str | None = base_url.rstrip("/")
        elif client is not None:
            self._base_url = client.base_url
        else:
            self._base_url = None

        if not self._delegate and not self._base_url:
            raise ConnectorError("OFFICE_API_NOT_CONFIGURED", "未配置上游地址")

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
        form_body: dict[str, Any] | None = None,
        authorization: str,
        timeout: float | None = None,
        idempotency_key: str | None = None,
        extra_headers: dict[str, str] | None = None,
        request_charset: str | None = None,
    ) -> ConnectorResult:
        if self._delegate:
            return self._invoke_via_client(
                method,
                path,
                params=params,
                json_body=json_body,
                form_body=form_body,
                authorization=authorization,
                timeout=timeout,
                idempotency_key=idempotency_key,
                extra_headers=extra_headers,
                request_charset=request_charset,
            )
        return self._invoke_direct(
            method,
            path,
            params=params,
            json_body=json_body,
            form_body=form_body,
            authorization=authorization,
            timeout=timeout,
            idempotency_key=idempotency_key,
            extra_headers=extra_headers,
            request_charset=request_charset,
        )

    def _invoke_via_client(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        form_body: dict[str, Any] | None = None,
        authorization: str,
        timeout: float | None,
        idempotency_key: str | None,
        extra_headers: dict[str, str] | None = None,
        request_charset: str | None = None,
    ) -> ConnectorResult:
        assert self._client is not None
        try:
            if method.upper() == "GET":
                resp = self._client.get(
                    path, params or {}, authorization, timeout,
                    request_charset=request_charset,
                )
            elif method.upper() == "POST":
                if form_body is not None:
                    resp = self._client.post(
                        path,
                        form_body,
                        authorization,
                        timeout=timeout,
                        idempotency_key=idempotency_key,
                        extra_headers=extra_headers,
                        content_type="application/x-www-form-urlencoded",
                        params=params,
                        request_charset=request_charset,
                    )
                else:
                    resp = self._client.post(
                        path,
                        json_body or {},
                        authorization,
                        timeout=timeout,
                        idempotency_key=idempotency_key,
                        extra_headers=extra_headers,
                        params=params,
                        request_charset=request_charset,
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

    def _invoke_direct(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        form_body: dict[str, Any] | None = None,
        authorization: str,
        timeout: float | None,
        idempotency_key: str | None,
        extra_headers: dict[str, str] | None = None,
        request_charset: str | None = None,
    ) -> ConnectorResult:
        assert self._base_url is not None
        verb = method.upper()
        if verb not in ("GET", "POST"):
            raise ConnectorError("UPSTREAM_HTTP_ERROR", f"不支持的 HTTP 方法：{method}")

        headers = {"Authorization": authorization}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if extra_headers:
            headers.update({k: v for k, v in extra_headers.items() if v})

        charset = (request_charset or "utf-8").strip() or "utf-8"
        # 按字符集手写 query，避免 httpx 默认 UTF-8 导致 OA GBK 乱码
        qs = encode_query_string(params, charset)
        url = f"{path}?{qs}" if qs else path

        started = time.perf_counter()
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=timeout or self._timeout,
                transport=self._transport,
            ) as client:
                if verb == "GET":
                    resp = client.request("GET", url, headers=headers)
                elif form_body is not None:
                    raw, ct = encode_www_form(form_body or {}, charset)
                    headers = {**headers, "Content-Type": ct}
                    resp = client.request("POST", url, content=raw, headers=headers)
                else:
                    resp = client.request(
                        "POST", url, json=json_body or {}, headers=headers,
                    )
        except httpx.TimeoutException as exc:
            raise ConnectorError("UPSTREAM_TIMEOUT", f"上游超时：{type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise ConnectorError(
                "UPSTREAM_UNAVAILABLE",
                f"上游不可用：{type(exc).__name__}: {exc}",
            ) from exc
        duration_ms = int((time.perf_counter() - started) * 1000)

        body, json_decode_ok = self._read_body(resp)
        data, hint = parse_envelope(
            self._envelope_profile,
            resp.status_code,
            body,
            success_codes=self._success_codes,
            hint_max=self._hint_max,
            json_decode_ok=json_decode_ok,
        )
        return ConnectorResult(
            data=data,
            http_status=resp.status_code,
            duration_ms=duration_ms,
            message=hint,
        )

    def _read_body(self, resp: httpx.Response) -> tuple[object, bool]:
        """解析响应体；空 body 在 raw_json 下视为合法 None（profile 会映射为 {}）。"""
        if resp.status_code >= 400:
            try:
                return resp.json(), True
            except ValueError:
                return None, True
        try:
            return resp.json(), True
        except ValueError:
            empty = not (resp.content or b"").strip()
            if empty and self._envelope_profile == "raw_json":
                return None, True
            return None, False
