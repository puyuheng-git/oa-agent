"""IdentityBroker：IdP 校验 → PrincipalClaims → ChatSession / office 凭证。"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from oa_agent.auth.chat_launch import (
    DEFAULT_POLICY,
    ChatSession,
    LaunchPolicy,
    _sync_office_credentials,
)
from oa_agent.errors import AppError
from oa_agent.ids import new_thread_id
from oa_agent.identity.adapters.demo import DemoIdP
from oa_agent.identity.adapters.oa_assertion import OaAssertionIdP
from oa_agent.identity.adapters.oidc import OidcIdP
from oa_agent.identity.adapters.wecom import WeComIdP
from oa_agent.identity.claims import PrincipalClaims
from oa_agent.identity.idp import IdP, IdPContext
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM

if TYPE_CHECKING:
    from oa_agent.kv import KV


DEFAULT_CHANNEL_IDP_MAP = {
    "oa_web": "oa_assertion",
    "wecom": "wecom",
    "demo": "demo",
}
DEFAULT_CHANNEL_IDP_MAP_JSON = '{"oa_web":"oa_assertion","wecom":"wecom","demo":"demo"}'


def parse_channel_idp_map(raw: str | None) -> dict[str, str]:
    """解析渠道映射；整体非法或单项无效时回落到对应默认值。"""
    try:
        parsed = json.loads(raw or DEFAULT_CHANNEL_IDP_MAP_JSON)
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(DEFAULT_CHANNEL_IDP_MAP)
    if not isinstance(parsed, dict):
        return dict(DEFAULT_CHANNEL_IDP_MAP)

    result = dict(DEFAULT_CHANNEL_IDP_MAP)
    result.update({
        str(channel): idp_id.strip()
        for channel, idp_id in parsed.items()
        if isinstance(channel, str) and channel.strip()
        and isinstance(idp_id, str) and idp_id.strip()
    })
    return result


def register_default_idps() -> dict[str, IdP]:
    """注册默认 IdP：OA assertion + 企微 + demo（demo.verify 仍受开关约束）。"""
    return {
        "oa_assertion": OaAssertionIdP(),
        "wecom": WeComIdP(),
        "demo": DemoIdP(),
        "oidc": OidcIdP(),
    }


def claims_from_oa_assertion(
    assertion: str,
    secret: str | None,
    kv: KV,
    *,
    now: int | None = None,
    channel: str = "oa_web",
    policy: LaunchPolicy = DEFAULT_POLICY,
) -> PrincipalClaims:
    """薄 shim：经 Broker + OaAssertionIdP 校验 assertion，供测与现网路径对齐。"""
    broker = IdentityBroker(register_default_idps())
    payload: dict = {
        "assertion": assertion,
        "channel": channel,
        "max_assertion_ttl": policy.max_assertion_ttl,
        "clock_skew": policy.clock_skew,
        "launch_ttl": policy.launch_ttl,
        "ticket_ttl": policy.ticket_ttl,
        "remint_before": policy.remint_before,
    }
    ctx = IdPContext(
        kv=kv,
        secrets={"assertion_hmac_secret": secret} if secret is not None else None,
        now=now,
    )
    return broker.verify("oa_assertion", payload, ctx=ctx)


class IdentityBroker:
    def __init__(self, idps: dict[str, IdP]):
        self._idps = dict(idps)

    def verify(self, idp_id: str, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        idp = self._idps.get(idp_id)
        if idp is None:
            raise AppError(400, "IDP_UNKNOWN", f"未知身份提供者: {idp_id}")
        return idp.verify(payload, ctx=ctx)

    def verify_channel(
        self,
        channel: str,
        payload: dict,
        *,
        ctx: IdPContext,
        channel_idp_map_json: str | None = None,
    ) -> PrincipalClaims:
        """按配置将渠道解析为 IdP，再执行校验。"""
        idp_id = parse_channel_idp_map(channel_idp_map_json).get(channel)
        if idp_id is None:
            raise AppError(400, "CHANNEL_UNKNOWN", f"未知身份渠道: {channel}")
        return self.verify(idp_id, payload, ctx=ctx)

    def session_from_claims(
        self,
        claims: PrincipalClaims,
        *,
        office_token: str = "",
        token_expires_at: int = 0,
        thread_id: str | None = None,
        uid: int | None = None,
        created_at: int | None = None,
    ) -> ChatSession:
        """将 PrincipalClaims 映射为 ChatSession（双写 oa / principal_id / credentials）。"""
        ext = claims.external_keys or {}
        oa = str(ext.get("oa") or claims.principal_id)
        principal_id = claims.principal_id or oa
        display_name = claims.display_name or oa
        channel = claims.channel or "oa_web"
        raw = claims.raw or {}

        if uid is None and raw.get("uid") is not None:
            try:
                uid = int(raw["uid"])
            except (TypeError, ValueError):
                uid = None

        token = office_token
        expires_at = int(token_expires_at or 0)
        credentials: dict = {}

        # 企微 mint 等：claims.raw 已带 authorization，直接种 office 凭证
        auth_from_raw = raw.get("authorization")
        if auth_from_raw and not token:
            token = str(auth_from_raw)
            if not expires_at and raw.get("ttl_seconds") is not None:
                try:
                    expires_at = int(time.time()) + int(raw["ttl_seconds"])
                except (TypeError, ValueError):
                    expires_at = 0

        if token:
            # demo 渠道凭证挂在 connector_id=demo；现网仍写 office
            cred_key = "demo" if channel == "demo" else DEFAULT_UPSTREAM
            credentials[cred_key] = {
                "authorization": token,
                "expires_at": expires_at,
            }

        return ChatSession(
            oa=oa,
            uid=uid,
            display_name=display_name,
            thread_id=thread_id or new_thread_id(),
            office_token="" if channel == "demo" else token,
            token_expires_at=0 if channel == "demo" else expires_at,
            created_at=created_at if created_at is not None else int(time.time()),
            channel=channel,
            principal_id=principal_id,
            credentials=credentials,
        )

    def ensure_office_credentials(
        self,
        session: ChatSession,
        *,
        mint_fn: Callable[[str], tuple[str, int]],
        now: int | None = None,
        remint_before: int = 0,
    ) -> ChatSession:
        """office 凭证缺失或临近过期时调用 mint_fn(oa) -> (token, expires_at)。"""
        now = now if now is not None else int(time.time())
        office = (session.credentials or {}).get(DEFAULT_UPSTREAM)
        auth = session.office_token or (
            str(office["authorization"])
            if isinstance(office, dict) and office.get("authorization")
            else ""
        )
        expires_at = session.token_expires_at
        if not expires_at and isinstance(office, dict) and office.get("expires_at") is not None:
            try:
                expires_at = int(office["expires_at"])
            except (TypeError, ValueError):
                expires_at = 0

        still_valid = bool(auth) and expires_at - now >= remint_before
        if still_valid:
            if not session.office_token and auth:
                session.office_token = auth
                session.token_expires_at = expires_at
                _sync_office_credentials(session)
            return session

        token, new_expires = mint_fn(session.oa)
        session.office_token = token
        session.token_expires_at = int(new_expires)
        _sync_office_credentials(session)
        return session
