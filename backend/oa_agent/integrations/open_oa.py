"""open-oa 客户端：mint 员工 token、以员工 token 调业务接口（含 POST /agent/invoke）。

响应信封以 {code, msg|message, data} 解析；成功码在后台「业务上游」配置。
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass

import httpx

from oa_agent.observability.redact import redact, redact_secrets

MINT_PATH = "/agent/token/mint"
INVOKE_PATH = "/agent/invoke"
CATALOG_PATH = "/agent/export-catalog"
DEFAULT_SUCCESS_CODES = ("0", "200")
DEFAULT_UPSTREAM = "open_oa"
# 旧会话 / 旧 Tool 上游标识兼容
LEGACY_UPSTREAM = "office"
UPSTREAM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
MESSAGE_KEYS = ("msg", "message", "errMsg", "err_msg", "errmsg")
MAX_HINT = 200
_TAG_RE = re.compile(r"<[^>]+>")
_GENERIC_RE = re.compile(r"(?i)^(ok|success|succeed|successful|成功|操作成功|请求成功|获取成功|查询成功|"
                         r"获取数据成功|数据获取成功|加载成功)[!！。.]*$")
_VAGUE_FAILURE_RE = re.compile(
    r"(?i)^(请求失败|操作失败|处理失败|系统错误|系统异常|失败|error|failed)[!！。.…]*$"
)
_NOT_FOUND_HINT_RE = re.compile(r"不存在|未找到|找不到|无此|没有该|无数据|not\s*found", re.I)
_FORBIDDEN_HINT_RE = re.compile(r"权限|无权|不允许|禁止|forbidden|permission|denied", re.I)


def employee_facing_error(
    code: str,
    *,
    hint: str = "",
    http_status: int | None = None,
) -> str | None:
    """将上游错误转为员工可读文案。返回 None 表示沿用 hint 或配置项默认逻辑。"""
    if code not in ("UPSTREAM_BIZ_ERROR", "UPSTREAM_HTTP_ERROR", "UPSTREAM_BAD_RESPONSE"):
        return None
    text = (hint or "").strip()
    if _NOT_FOUND_HINT_RE.search(text) or http_status == 404:
        return "未找到该报销单，请核对单号是否正确。"
    if _FORBIDDEN_HINT_RE.search(text) or http_status == 403:
        return "你没有权限查看该报销单。"
    if text and not _VAGUE_FAILURE_RE.match(text):
        return None
    if code == "UPSTREAM_HTTP_ERROR" and http_status is not None and http_status >= 500:
        return None
    if text or code == "UPSTREAM_BIZ_ERROR":
        return "查询失败，请稍后再试。"
    return None


def business_hint(body: object, max_len: int = MAX_HINT) -> str:
    """open-oa 返回给员工看的提示语：去 HTML、去密钥、限长；通用的「成功/ok」视为无提示。"""
    if not isinstance(body, dict):
        return ""
    raw = next((body[k] for k in MESSAGE_KEYS if isinstance(body.get(k), str) and body[k].strip()), "")
    text = " ".join(html.unescape(_TAG_RE.sub(" ", raw)).split())
    if not text or _GENERIC_RE.match(text):
        return ""
    return redact_secrets(text, max_len)


class OpenOaError(Exception):
    """code: OFFICE_API_NOT_CONFIGURED | UPSTREAM_TIMEOUT | UPSTREAM_UNAVAILABLE | UPSTREAM_HTTP_ERROR |
    UPSTREAM_BIZ_ERROR | UPSTREAM_BAD_RESPONSE | OFFICE_TOKEN_EXPIRED | MINT_FAILED

    user_message：open-oa 给员工的提示语（已清洗），可直接展示。"""

    def __init__(self, code: str, message: str, http_status: int | None = None, user_message: str = ""):
        super().__init__(message)
        self.code = code
        self.message = redact(message, 500)
        self.http_status = http_status
        self.user_message = user_message


# 兼容旧 import 名
OfficeApiError = OpenOaError


@dataclass
class MintResult:
    authorization: str
    uid: int | None
    oa: str
    ttl_seconds: int
    display_name: str = ""


@dataclass
class OpenOaResponse:
    data: object
    http_status: int
    duration_ms: int
    message: str = ""


OfficeResponse = OpenOaResponse


class OpenOaClient:
    def __init__(self, base_url: str | None, success_codes: list[str] | tuple[str, ...] | None = None,
                 timeout: float = 10.0, transport: httpx.BaseTransport | None = None, hint_max: int = MAX_HINT):
        if not base_url:
            raise OpenOaError("OFFICE_API_NOT_CONFIGURED", "未配置 open-oa 地址")
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
            raise OpenOaError("UPSTREAM_TIMEOUT", f"open-oa 超时：{type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise OpenOaError("UPSTREAM_UNAVAILABLE", f"open-oa 不可用：{type(exc).__name__}: {exc}") from exc
        return resp, int((time.perf_counter() - started) * 1000)

    def _unwrap(self, resp: httpx.Response) -> tuple[object, str]:
        from oa_agent.connectors.base import ConnectorError
        from oa_agent.connectors.envelope import parse_envelope

        if resp.status_code >= 400:
            body: object = _json_or_none(resp)
            json_decode_ok = True
        else:
            try:
                body = resp.json()
                json_decode_ok = True
            except ValueError:
                body = None
                json_decode_ok = False
        try:
            return parse_envelope(
                "oa_office",
                resp.status_code,
                body,
                success_codes=self.success_codes,
                hint_max=self.hint_max,
                json_decode_ok=json_decode_ok,
            )
        except ConnectorError as exc:
            raise OpenOaError(
                exc.code,
                exc.message,
                exc.http_status,
                user_message=exc.user_message,
            ) from exc

    def mint(self, oa: str, gateway_secret: str | None) -> MintResult:
        data = self._mint_request({"oa": oa}, gateway_secret)
        if str(data.get("oa", oa)) != oa:
            raise OpenOaError("MINT_FAILED", "签发员工令牌失败：返回账号与请求不一致")
        return self._mint_result(data, oa)

    def mint_by_wework(self, wework_user_id: str, gateway_secret: str | None) -> MintResult:
        data = self._mint_request({"wework_user_id": wework_user_id}, gateway_secret)
        oa = str(data.get("oa") or "").strip()
        if not oa:
            raise OpenOaError("MINT_FAILED", "签发员工令牌失败：响应缺少 oa")
        return self._mint_result(data, oa)

    def _mint_request(self, who: dict, gateway_secret: str | None) -> dict:
        if not gateway_secret:
            raise OpenOaError("OFFICE_API_NOT_CONFIGURED", "未配置 AGENT_GATEWAY_SECRET")
        resp, _ = self._send("POST", MINT_PATH, data={**who, "gateway_secret": gateway_secret}, timeout=5.0)
        try:
            data, _ = self._unwrap(resp)
        except OpenOaError as exc:
            raise OpenOaError("MINT_FAILED", f"签发员工令牌失败：{exc.message}", exc.http_status,
                             user_message=exc.user_message) from exc
        if not isinstance(data, dict) or not data.get("authorization"):
            raise OpenOaError("MINT_FAILED", "签发员工令牌失败：响应缺少 authorization")
        return data

    @staticmethod
    def _mint_result(data: dict, oa: str) -> MintResult:
        expire = int(data.get("expire") or 1800)
        ttl = expire - int(time.time()) if expire > 1_000_000_000 else expire
        uid = data.get("uid")
        return MintResult(str(data["authorization"]), int(uid) if uid is not None else None, oa, max(0, ttl),
                          str(data.get("display_name") or oa))

    def get(self, path: str, params: dict, authorization: str, timeout: float | None = None) -> OpenOaResponse:
        resp, ms = self._send("GET", path, params=params, headers={"Authorization": authorization}, timeout=timeout)
        data, hint = self._unwrap(resp)
        return OpenOaResponse(data, resp.status_code, ms, hint)

    def post(self, path: str, body: dict, authorization: str, *, timeout: float | None = None,
             idempotency_key: str | None = None, extra_headers: dict | None = None) -> OpenOaResponse:
        headers = {"Authorization": authorization}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if extra_headers:
            headers.update({k: v for k, v in extra_headers.items() if v})
        resp, ms = self._send("POST", path, json=body, headers=headers, timeout=timeout)
        data, hint = self._unwrap(resp)
        return OpenOaResponse(data, resp.status_code, ms, hint)

    def get_export_catalog(self, *, gateway_secret: str, timeout: float | None = None) -> list:
        """管理端导入：用网关密钥拉清单（不经员工 Bearer）。"""
        if not gateway_secret:
            raise OpenOaError("OFFICE_API_NOT_CONFIGURED", "未配置 AGENT_GATEWAY_SECRET")
        resp, _ = self._send(
            "GET", CATALOG_PATH,
            headers={"X-Agent-Gateway-Secret": gateway_secret},
            timeout=timeout or 10.0,
        )
        data, _ = self._unwrap(resp)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data, list):
            return data
        raise OpenOaError("UPSTREAM_BAD_RESPONSE", "export-catalog 响应缺少 items")


OfficeApiClient = OpenOaClient


def mint_base_url(oa_settings: dict) -> str | None:
    """签发入口基址；已由 SettingsService.apply_oa_compat 做过旧字段映射。"""
    url = oa_settings.get("mint_base_url") or oa_settings.get("office_api_base_url")
    return str(url).rstrip("/") if url else None


def upstream_clients(oa_settings: dict) -> dict[str, OpenOaClient]:
    """业务上游客户端：来自 upstreams 目录（peer）；都以员工 Authorization 调用。"""
    codes = oa_settings.get("success_codes")
    hint_max = int(oa_settings.get("business_hint_max_chars") or MAX_HINT)
    items = list(oa_settings.get("upstreams") or [])
    if not items:
        base = oa_settings.get("office_api_base_url") or oa_settings.get("mint_base_url")
        if base:
            items = [{"key": DEFAULT_UPSTREAM, "label": "open-oa", "base_url": base}]
        for extra in oa_settings.get("extra_upstreams") or []:
            items.append(extra)
    if not items:
        return {DEFAULT_UPSTREAM: OpenOaClient(None, codes, hint_max=hint_max)}
    clients: dict[str, OpenOaClient] = {}
    for item in items:
        key = item["key"]
        clients[key] = OpenOaClient(item.get("base_url"), codes, hint_max=hint_max)
    return clients


def upstream_connectors(oa_settings: dict):
    from oa_agent.connectors.hub import ConnectorHub

    return ConnectorHub.from_office_settings(oa_settings)


def _json_or_none(resp: httpx.Response) -> object:
    try:
        return resp.json()
    except ValueError:
        return None
