"""OA iframe assertion → PrincipalClaims（委托 chat_launch.verify_assertion）。"""

from __future__ import annotations

from dataclasses import replace

from oa_agent.auth.chat_launch import DEFAULT_POLICY, LaunchPolicy, verify_assertion
from oa_agent.identity.claims import PrincipalClaims
from oa_agent.identity.idp import IdPContext

ASSERTION_HMAC_SECRET_KEY = "assertion_hmac_secret"


def _resolve_secret(ctx: IdPContext) -> str | None:
    secrets = ctx.secrets
    if secrets is None:
        return None
    if isinstance(secrets, dict):
        return secrets.get(ASSERTION_HMAC_SECRET_KEY)
    if callable(secrets):
        return secrets(ASSERTION_HMAC_SECRET_KEY)
    return None


def _policy_from_payload(payload: dict) -> LaunchPolicy:
    overrides: dict[str, int] = {}
    for name in ("max_assertion_ttl", "clock_skew", "launch_ttl", "ticket_ttl", "remint_before"):
        if name in payload:
            overrides[name] = int(payload[name])
    if not overrides:
        return DEFAULT_POLICY
    return replace(DEFAULT_POLICY, **overrides)


class OaAssertionIdP:
    id = "oa_assertion"

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        assertion = str(payload.get("assertion") or "")
        policy = _policy_from_payload(payload)
        verified = verify_assertion(
            assertion,
            _resolve_secret(ctx),
            ctx.kv,
            now=ctx.now,
            policy=policy,
        )
        oa = str(verified["oa"])
        display_name = str(verified.get("display_name") or oa)
        return PrincipalClaims(
            principal_id=oa,
            display_name=display_name,
            external_keys={"oa": oa},
            channel=str(payload.get("channel") or "oa_web"),
            raw=dict(verified),
        )
