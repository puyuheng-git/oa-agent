"""office-api 客户端：mint 员工 office token、以员工 token 调业务接口。

响应信封以 {code, msg, data} 解析；成功码在后台「OA 对接」配置（现网格式待联调确认）。
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass

import httpx

from oa_agent.observability.redact import redact, redact_secrets

MINT_PATH = "/agent/token/mint"
DEFAULT_SUCCESS_CODES = ("0", "200")
DEFAULT_UPSTREAM = "office"
UPSTREAM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
MESSAGE_KEYS = ("msg", "message", "errMsg", "err_msg", "errmsg")
MAX_HINT = 200
_TAG_RE = re.compile(r"<[^>]+>")
_GENERIC_RE = re.compile(r"(?i)^(ok|success|succeed|successful|成功|操作成功|请求成功|获取成功|查询成功|"
                         r"获取数据成功|数据获取成功|加载成功)[!！。.]*$")


def business_hint(body: object, max_len: int = MAX_HINT) -> str:
    """office-api 返回给员工看的提示语（msg 等）：去 HTML、去密钥、限长；通用的「成功/ok」视为无提示。"""
    if not isinstance(body, dict):
        return ""
    raw = next((body[k] for k in MESSAGE_KEYS if isinstance(body.get(k), str) and body[k].strip()), "")
    text = " ".join(html.unescape(_TAG_RE.sub(" ", raw)).split())
    if not text or _GENERIC_RE.match(text):
        return ""
    return redact_secrets(text, max_len)


class OfficeApiError(Exception):
    """code: OFFICE_API_NOT_CONFIGURED | UPSTREAM_TIMEOUT | UPSTREAM_UNAVAILABLE | UPSTREAM_HTTP_ERROR |
    UPSTREAM_BIZ_ERROR | UPSTREAM_BAD_RESPONSE | OFFICE_TOKEN_EXPIRED | MINT_FAILED

    user_message：office-api 给员工的提示语（已清洗），可直接展示；为空时按错误码给通用提示。"""

    def __init__(self, code: str, message: str, http_status: int | None = None, user_message: str = ""):
        super().__init__(message)
        self.code = code
        self.message = redact(message, 500)
        self.http_status = http_status
        self.user_message = user_message


@dataclass
class MintResult:
    authorization: str
    uid: int | None
    oa: str
    ttl_seconds: int
    display_name: str = ""


@dataclass
class OfficeResponse:
    data: object
    http_status: int
    duration_ms: int
    message: str = ""   # 成功响应里的提示语（如「暂无未接收合同」），已清洗


class OfficeApiClient:
    def __init__(self, base_url: str | None, success_codes: list[str] | tuple[str, ...] | None = None,
                 timeout: float = 10.0, transport: httpx.BaseTransport | None = None, hint_max: int = MAX_HINT):
        if not base_url:
            raise OfficeApiError("OFFICE_API_NOT_CONFIGURED", "未配置 office-api 地址")
        self.base_url = base_url.rstrip("/")
        self.success_codes = {str(c) for c in (success_codes or DEFAULT_SUCCESS_CODES)}
        self.timeout = timeout
        self._transport = transport
        self.hint_max = hint_max

    def _client(self, timeout: float | None) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=timeout or self.timeout, transport=self._transport)

    def _send(self, method: str, path: str, *, timeout: float | None = None, **kw) -> tuple[httpx.Response, int]:
        started = time.perf_counter()
        try:
            with self._client(timeout) as client:
                resp = client.request(method, path, **kw)
        except httpx.TimeoutException as exc:
            raise OfficeApiError("UPSTREAM_TIMEOUT", f"office-api 超时：{type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise OfficeApiError("UPSTREAM_UNAVAILABLE", f"office-api 不可用：{type(exc).__name__}: {exc}") from exc
        return resp, int((time.perf_counter() - started) * 1000)

    def _unwrap(self, resp: httpx.Response) -> tuple[object, str]:
        """返回 (data, 成功提示语)。"""
        if resp.status_code in (401, 403):
            raise OfficeApiError("OFFICE_TOKEN_EXPIRED", f"office-api 拒绝访问（HTTP {resp.status_code}）", resp.status_code)
        if resp.status_code >= 400:
            # 4xx 的 msg 多为参数/业务校验提示，可给员工看；5xx 的内容可能是堆栈，不展示
            hint = business_hint(_json_or_none(resp), self.hint_max) if resp.status_code < 500 else ""
            raise OfficeApiError("UPSTREAM_HTTP_ERROR", f"office-api HTTP {resp.status_code} {hint}".strip(),
                                 resp.status_code, user_message=hint)
        try:
            body = resp.json()
        except ValueError as exc:
            raise OfficeApiError("UPSTREAM_BAD_RESPONSE", "office-api 返回非 JSON", resp.status_code) from exc
        if not isinstance(body, dict):
            return body, ""
        code = next((body[k] for k in ("code", "errCode", "err_code") if k in body), None)
        hint = business_hint(body, self.hint_max)
        if code is not None and str(code) not in self.success_codes:
            raise OfficeApiError("UPSTREAM_BIZ_ERROR", f"office-api 业务错误 code={code} {hint}".strip(),
                                 resp.status_code, user_message=hint)
        return (body.get("data", body) if code is not None or "data" in body else body), hint

    def mint(self, oa: str, gateway_secret: str | None) -> MintResult:
        data = self._mint_request({"oa": oa}, gateway_secret)
        if str(data.get("oa", oa)) != oa:
            raise OfficeApiError("MINT_FAILED", "签发员工令牌失败：返回账号与请求不一致")
        return self._mint_result(data, oa)

    def mint_by_wework(self, wework_user_id: str, gateway_secret: str | None) -> MintResult:
        """企业微信入口：由 OA 按企微绑定解析主账号并签发 token；员工身份以 OA 返回的 oa 为准。"""
        data = self._mint_request({"wework_user_id": wework_user_id}, gateway_secret)
        oa = str(data.get("oa") or "").strip()
        if not oa:
            raise OfficeApiError("MINT_FAILED", "签发员工令牌失败：响应缺少 oa")
        return self._mint_result(data, oa)

    def _mint_request(self, who: dict, gateway_secret: str | None) -> dict:
        if not gateway_secret:
            raise OfficeApiError("OFFICE_API_NOT_CONFIGURED", "未配置 AGENT_GATEWAY_SECRET")
        resp, _ = self._send("POST", MINT_PATH, data={**who, "gateway_secret": gateway_secret}, timeout=5.0)
        try:
            data, _ = self._unwrap(resp)
        except OfficeApiError as exc:
            raise OfficeApiError("MINT_FAILED", f"签发员工令牌失败：{exc.message}", exc.http_status,
                                 user_message=exc.user_message) from exc
        if not isinstance(data, dict) or not data.get("authorization"):
            raise OfficeApiError("MINT_FAILED", "签发员工令牌失败：响应缺少 authorization")
        return data

    @staticmethod
    def _mint_result(data: dict, oa: str) -> MintResult:
        expire = int(data.get("expire") or 1800)
        ttl = expire - int(time.time()) if expire > 1_000_000_000 else expire
        uid = data.get("uid")
        return MintResult(str(data["authorization"]), int(uid) if uid is not None else None, oa, max(0, ttl),
                          str(data.get("display_name") or oa))

    def get(self, path: str, params: dict, authorization: str, timeout: float | None = None) -> OfficeResponse:
        resp, ms = self._send("GET", path, params=params, headers={"Authorization": authorization}, timeout=timeout)
        data, hint = self._unwrap(resp)
        return OfficeResponse(data, resp.status_code, ms, hint)

    def post(self, path: str, body: dict, authorization: str, *, timeout: float | None = None,
             idempotency_key: str | None = None) -> OfficeResponse:
        headers = {"Authorization": authorization}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        resp, ms = self._send("POST", path, json=body, headers=headers, timeout=timeout)
        data, hint = self._unwrap(resp)
        return OfficeResponse(data, resp.status_code, ms, hint)


def mint_base_url(oa_settings: dict) -> str | None:
    """签发入口基址；已由 SettingsService.apply_oa_compat 做过旧字段映射。"""
    url = oa_settings.get("mint_base_url") or oa_settings.get("office_api_base_url")
    return str(url).rstrip("/") if url else None


def upstream_clients(oa_settings: dict) -> dict[str, OfficeApiClient]:
    """业务上游客户端：来自 upstreams 目录（peer）；都以员工 Authorization 调用。

    兼容旧配置：无 upstreams 时用 office_api_base_url 作为 office + extra_upstreams。
    目录为空时仍尝试构建默认 office 客户端，未配置则抛 OFFICE_API_NOT_CONFIGURED。
    """
    codes = oa_settings.get("success_codes")
    hint_max = int(oa_settings.get("business_hint_max_chars") or MAX_HINT)
    items = list(oa_settings.get("upstreams") or [])
    if not items:
        base = oa_settings.get("office_api_base_url") or oa_settings.get("mint_base_url")
        if base:
            items = [{"key": DEFAULT_UPSTREAM, "label": "office-api", "base_url": base}]
        for extra in oa_settings.get("extra_upstreams") or []:
            items.append(extra)
    if not items:
        # 保持与旧行为一致：访问默认上游时给出未配置错误
        return {DEFAULT_UPSTREAM: OfficeApiClient(None, codes, hint_max=hint_max)}
    clients: dict[str, OfficeApiClient] = {}
    for item in items:
        key = item["key"]
        clients[key] = OfficeApiClient(item.get("base_url"), codes, hint_max=hint_max)
    return clients


def _json_or_none(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return None
