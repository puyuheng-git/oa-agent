"""企业微信 userid → PrincipalClaims（委托 OfficeApiClient.mint_by_wework）。"""

from __future__ import annotations

from collections.abc import Callable

from oa_agent.identity.claims import PrincipalClaims
from oa_agent.identity.idp import IdPContext
from oa_agent.integrations.office_api import OfficeApiClient, OfficeApiError

GATEWAY_SECRET_KEY = "gateway_secret"


def _resolve_gateway_secret(ctx: IdPContext) -> str | None:
    secrets = ctx.secrets
    if secrets is None:
        return None
    if isinstance(secrets, dict):
        return secrets.get(GATEWAY_SECRET_KEY)
    if callable(secrets):
        return secrets(GATEWAY_SECRET_KEY)
    return None


class WeComIdP:
    id = "wecom"

    def __init__(self, client_factory: Callable[[], OfficeApiClient] | None = None) -> None:
        self._client_factory = client_factory

    def _client(self, payload: dict) -> OfficeApiClient:
        if self._client_factory is not None:
            return self._client_factory()
        client = payload.get("client")
        if client is not None and callable(getattr(client, "mint_by_wework", None)):
            return client  # type: ignore[return-value]
        raise OfficeApiError("OFFICE_API_NOT_CONFIGURED", "未配置 office-api 客户端")

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        wework_user_id = str(payload.get("wework_user_id") or "").strip()
        if not wework_user_id:
            raise OfficeApiError("MINT_FAILED", "缺少 wework_user_id")
        result = self._client(payload).mint_by_wework(wework_user_id, _resolve_gateway_secret(ctx))
        oa = result.oa
        display_name = result.display_name or oa
        raw: dict = {
            "authorization": result.authorization,
            "ttl_seconds": result.ttl_seconds,
            "oa": oa,
        }
        if result.uid is not None:
            raw["uid"] = result.uid
        return PrincipalClaims(
            principal_id=oa,
            display_name=display_name,
            external_keys={"oa": oa},
            channel="wecom",
            raw=raw,
        )
