"""员工对话身份（设计 §6.1）：OA assertion → launch_code → chat ticket。

assertion 线格式：base64url(UTF-8 JSON，无填充) + "." + hex(HMAC-SHA256(secret, base64url 部分))
payload：{oa, uid, display_name, exp, nonce, iss:"oa-host", aud:"oa-langgraph"}，exp 为 Unix 秒且 ≤ 60 秒后。
office token 只存在服务端 KV；ticket 只存其 SHA-256 作为键。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass

from fastapi import Request

from oa_agent.errors import AppError
from oa_agent.integrations.office_api import OfficeApiClient, OfficeApiError
from oa_agent.kv import KV
from oa_agent.ids import new_thread_id

ISSUER, AUDIENCE = "oa-host", "oa-langgraph"


@dataclass(frozen=True)
class LaunchPolicy:
    """时长类参数（秒），来自配置中心「员工对话」组；默认值即原设计值。"""
    max_assertion_ttl: int = 60
    clock_skew: int = 30
    launch_ttl: int = 60
    ticket_ttl: int = 30 * 60
    remint_before: int = 5 * 60


DEFAULT_POLICY = LaunchPolicy()

_LAUNCH = "chat:launch:"
_TICKET = "chat:ticket:"
_NONCE = "chat:nonce:"


@dataclass
class ChatSession:
    oa: str
    uid: int | None
    display_name: str
    thread_id: str
    office_token: str
    token_expires_at: int
    created_at: int
    channel: str = "oa_web"
    principal_id: str = ""

    def __post_init__(self) -> None:
        if not self.principal_id:
            self.principal_id = self.oa


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_assertion(payload: dict, secret: str) -> str:
    """OA 宿主页的参考实现（测试与联调用）。"""
    body = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode().rstrip("=")
    return body + "." + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def verify_assertion(assertion: str, secret: str | None, kv: KV, now: int | None = None,
                     policy: LaunchPolicy = DEFAULT_POLICY) -> dict:
    if not secret:
        raise AppError(503, "OA_NOT_CONFIGURED", "未配置 OA assertion HMAC 密钥")
    try:
        body, sig = assertion.strip().split(".", 1)
    except ValueError:
        raise AppError(401, "ASSERTION_INVALID", "assertion 格式无效") from None
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig.lower()):
        raise AppError(401, "ASSERTION_INVALID", "assertion 签名无效")
    try:
        payload = json.loads(_b64decode(body))
    except ValueError:
        raise AppError(401, "ASSERTION_INVALID", "assertion 内容无效") from None
    now = now or int(time.time())
    if payload.get("iss") != ISSUER or payload.get("aud") != AUDIENCE:
        raise AppError(401, "ASSERTION_INVALID", "assertion iss/aud 不匹配")
    oa, nonce = str(payload.get("oa") or "").strip(), str(payload.get("nonce") or "")
    if not oa or len(nonce) < 8:
        raise AppError(401, "ASSERTION_INVALID", "assertion 缺少 oa 或 nonce")
    try:
        exp = int(payload.get("exp"))
    except (TypeError, ValueError):
        raise AppError(401, "ASSERTION_INVALID", "assertion 缺少 exp") from None
    if exp < now - policy.clock_skew:
        raise AppError(401, "ASSERTION_EXPIRED", "assertion 已过期，请重新打开 OA 助手页")
    if exp > now + policy.max_assertion_ttl + policy.clock_skew:
        raise AppError(401, "ASSERTION_INVALID", "assertion 有效期过长")
    if not kv.set_nx(_NONCE + nonce, "1", policy.max_assertion_ttl + 2 * policy.clock_skew):
        raise AppError(401, "ASSERTION_REPLAYED", "assertion 已使用")
    return {"oa": oa, "uid": payload.get("uid"), "display_name": str(payload.get("display_name") or oa)}


def _mint(client: OfficeApiClient, oa: str, gateway_secret: str | None) -> tuple[str, int]:
    try:
        result = client.mint(oa, gateway_secret)
    except OfficeApiError as exc:
        status = 503 if exc.code == "OFFICE_API_NOT_CONFIGURED" else 502
        raise AppError(status, exc.code, exc.message) from exc
    if result.ttl_seconds <= 60:
        raise AppError(502, "MINT_FAILED", "签发的员工令牌有效期过短")
    return result.authorization, int(time.time()) + result.ttl_seconds


def create_launch(kv: KV, identity: dict, client: OfficeApiClient, gateway_secret: str | None,
                  policy: LaunchPolicy = DEFAULT_POLICY) -> str:
    token, expires_at = _mint(client, identity["oa"], gateway_secret)
    code = secrets.token_urlsafe(24)
    kv.set(_LAUNCH + code, json.dumps({**identity, "office_token": token, "token_expires_at": expires_at}),
           policy.launch_ttl)
    return code


def _ticket_key(ticket: str) -> str:
    return _TICKET + hashlib.sha256(ticket.encode()).hexdigest()


def _ttl_for(session: ChatSession, policy: LaunchPolicy = DEFAULT_POLICY) -> int:
    return max(1, min(policy.ticket_ttl, session.token_expires_at - int(time.time())))


def redeem_launch(kv: KV, code: str, policy: LaunchPolicy = DEFAULT_POLICY) -> tuple[str, ChatSession]:
    raw = kv.pop(_LAUNCH + code) if code else None
    if raw is None:
        raise AppError(401, "LAUNCH_CODE_INVALID", "启动码无效或已使用，请重新打开 OA 助手页")
    data = json.loads(raw)
    session = ChatSession(oa=data["oa"], uid=data.get("uid"), display_name=data["display_name"],
                          thread_id=new_thread_id(), office_token=data["office_token"],
                          token_expires_at=int(data["token_expires_at"]), created_at=int(time.time()))
    ticket = secrets.token_urlsafe(32)
    kv.set(_ticket_key(ticket), json.dumps(asdict(session)), _ttl_for(session, policy))
    return ticket, session


def store_session(kv: KV, ticket: str, session: ChatSession, policy: LaunchPolicy = DEFAULT_POLICY) -> int:
    """保存（续期）会话；ticket 只在服务端使用时（如企业微信渠道）由调用方随机生成且不外发。"""
    ttl = _ttl_for(session, policy)
    kv.set(_ticket_key(ticket), json.dumps(asdict(session)), ttl)
    return ttl


def load_session(kv: KV, ticket: str) -> ChatSession | None:
    raw = kv.get(_ticket_key(ticket)) if ticket else None
    return ChatSession(**json.loads(raw)) if raw else None


def session_key(ticket: str) -> str:
    """会话的服务端引用（ticket 的哈希键）；运行上下文只存它，不复制员工 token。"""
    return _ticket_key(ticket)


def load_session_by_key(kv: KV, key: str | None) -> ChatSession | None:
    if not key or not key.startswith(_TICKET):
        return None
    raw = kv.get(key)
    return ChatSession(**json.loads(raw)) if raw else None


def refresh_session(kv: KV, ticket: str, session: ChatSession, client_factory, gateway_secret: str | None,
                    policy: LaunchPolicy = DEFAULT_POLICY) -> int:
    """续期 ticket；员工 token 临近过期时以会话中的 oa 重新 mint（身份已由 ticket 证明）。"""
    if session.token_expires_at - int(time.time()) < policy.remint_before:
        session.office_token, session.token_expires_at = _mint(client_factory(), session.oa, gateway_secret)
    ttl = _ttl_for(session, policy)
    kv.set(_ticket_key(ticket), json.dumps(asdict(session)), ttl)
    return ttl


def bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth[:7].lower() == "bearer " else ""
