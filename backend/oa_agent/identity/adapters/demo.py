"""Demo IdP：本地共享口令签发主体（默认关闭，仅本地/测无 OA 可聊）。"""

from __future__ import annotations

from oa_agent.errors import AppError
from oa_agent.identity.claims import PrincipalClaims
from oa_agent.identity.idp import IdPContext

DEMO_ENABLED_KEY = "demo_idp_enabled"
DEMO_SECRET_KEY = "demo_shared_secret"
DEFAULT_DEMO_AUTHORIZATION = "Bearer demo-token"


def _secret_get(ctx: IdPContext, key: str):
    secrets = ctx.secrets
    if secrets is None:
        return None
    if isinstance(secrets, dict):
        return secrets.get(key)
    if callable(secrets):
        return secrets(key)
    return None


def _truthy(value: object) -> bool:
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class DemoIdP:
    id = "demo"

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        enabled = _secret_get(ctx, DEMO_ENABLED_KEY)
        if not _truthy(enabled) and not _truthy(payload.get("demo_enabled")):
            raise AppError(403, "DEMO_IDP_DISABLED", "Demo 身份提供者未启用")

        expected = _secret_get(ctx, DEMO_SECRET_KEY)
        provided = payload.get("secret")
        if expected is None or provided is None or str(expected) != str(provided):
            raise AppError(401, "DEMO_IDP_SECRET_INVALID", "Demo 共享口令无效")

        principal_id = str(payload.get("principal_id") or "").strip()
        if not principal_id:
            raise AppError(400, "DEMO_IDP_INVALID_PAYLOAD", "缺少 principal_id")

        display_name = str(payload.get("display_name") or "").strip()
        channel = str(payload.get("channel") or "demo").strip() or "demo"
        authorization = payload.get("authorization")
        if authorization is None or authorization == "":
            authorization = DEFAULT_DEMO_AUTHORIZATION
        else:
            authorization = str(authorization)

        return PrincipalClaims(
            principal_id=principal_id,
            display_name=display_name or principal_id,
            external_keys={"demo": principal_id},
            channel=channel,
            raw={
                "authorization": authorization,
                "principal_id": principal_id,
            },
        )
