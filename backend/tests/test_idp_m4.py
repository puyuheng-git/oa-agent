"""M4：PrincipalClaims、IdP Protocol、适配器与 IdentityBroker。"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from oa_agent.auth.chat_launch import sign_assertion, verify_assertion
from oa_agent.errors import AppError
from oa_agent.identity import (
    IdP,
    IdPContext,
    IdentityBroker,
    PrincipalClaims,
    claims_from_oa_assertion,
    register_default_idps,
)
from oa_agent.identity.adapters.oa_assertion import OaAssertionIdP
from oa_agent.identity.adapters.oidc import OidcIdP
from oa_agent.identity.adapters.wecom import WeComIdP
from oa_agent.integrations.office_api import DEFAULT_UPSTREAM, MintResult
from oa_agent.kv import MemoryKV

HMAC_SECRET = "hmac-secret-for-tests-0123"


class FakeIdP:
    id = "fake"

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        return PrincipalClaims(
            principal_id=str(payload["principal_id"]),
            display_name=str(payload.get("display_name", "")),
            channel=str(payload.get("channel", "")),
            raw=dict(payload),
        )


def test_fake_idp_implements_protocol():
    idp = FakeIdP()
    assert isinstance(idp, IdP)


def test_fake_idp_verify_returns_claims():
    idp = FakeIdP()
    ctx = IdPContext(now=1_700_000_000)
    claims = idp.verify(
        {"principal_id": "u42", "display_name": "Test User", "channel": "iframe"},
        ctx=ctx,
    )
    assert claims.principal_id == "u42"
    assert claims.display_name == "Test User"
    assert claims.channel == "iframe"
    assert claims.external_keys == {}
    assert claims.raw == {
        "principal_id": "u42",
        "display_name": "Test User",
        "channel": "iframe",
    }


def test_principal_claims_normalizes_external_keys():
    claims = PrincipalClaims(principal_id="p1", external_keys=None)
    assert claims.external_keys == {}


def test_oa_assertion_idp_verify_maps_claims():
    now = 1_700_000_000
    assertion_body = {
        "oa": "zhangsan",
        "uid": 7,
        "display_name": "张三",
        "exp": now + 50,
        "nonce": uuid.uuid4().hex,
        "iss": "oa-host",
        "aud": "oa-langgraph",
    }
    assertion = sign_assertion(assertion_body, HMAC_SECRET)
    idp = OaAssertionIdP()
    ctx = IdPContext(
        kv=MemoryKV(),
        secrets={"assertion_hmac_secret": HMAC_SECRET},
        now=now,
    )
    claims = idp.verify({"assertion": assertion, "channel": "iframe"}, ctx=ctx)
    assert claims.principal_id == "zhangsan"
    assert claims.display_name == "张三"
    assert claims.external_keys == {"oa": "zhangsan"}
    assert claims.channel == "iframe"
    assert claims.raw == {"oa": "zhangsan", "uid": 7, "display_name": "张三"}


GATEWAY = "gateway-secret-xyz"


def _mint_result(oa: str = "zhangsan") -> MintResult:
    return MintResult(
        authorization=f"tok-{oa}",
        uid=7,
        oa=oa,
        ttl_seconds=1800,
        display_name="张三",
    )


def test_wecom_idp_implements_protocol():
    idp = WeComIdP(client_factory=lambda: MagicMock())
    assert isinstance(idp, IdP)


def test_wecom_idp_verify_maps_claims_via_client_factory():
    mock_client = MagicMock()
    mock_client.mint_by_wework.return_value = _mint_result()
    idp = WeComIdP(client_factory=lambda: mock_client)
    ctx = IdPContext(secrets={"gateway_secret": GATEWAY})
    claims = idp.verify({"wework_user_id": "wx_zhangsan"}, ctx=ctx)
    mock_client.mint_by_wework.assert_called_once_with("wx_zhangsan", GATEWAY)
    assert claims.principal_id == "zhangsan"
    assert claims.display_name == "张三"
    assert claims.external_keys == {"oa": "zhangsan"}
    assert claims.channel == "wecom"
    assert claims.raw == {
        "authorization": "tok-zhangsan",
        "ttl_seconds": 1800,
        "oa": "zhangsan",
        "uid": 7,
    }


def test_wecom_idp_verify_accepts_client_in_payload():
    mock_client = MagicMock()
    mock_client.mint_by_wework.return_value = _mint_result("lisi")
    idp = WeComIdP()
    ctx = IdPContext(secrets=lambda key: GATEWAY if key == "gateway_secret" else None)
    claims = idp.verify(
        {"wework_user_id": "wx_lisi", "client": mock_client},
        ctx=ctx,
    )
    mock_client.mint_by_wework.assert_called_once_with("wx_lisi", GATEWAY)
    assert claims.principal_id == "lisi"
    assert claims.raw["authorization"] == "tok-lisi"


def _signed_assertion(oa: str = "zhangsan", *, now: int = 1_700_000_000) -> tuple[str, int]:
    body = {
        "oa": oa,
        "uid": 7,
        "display_name": "张三",
        "exp": now + 50,
        "nonce": uuid.uuid4().hex,
        "iss": "oa-host",
        "aud": "oa-langgraph",
    }
    return sign_assertion(body, HMAC_SECRET), now


def test_register_default_idps_contains_oa_wecom_and_demo():
    from oa_agent.identity.adapters.demo import DemoIdP

    idps = register_default_idps()
    assert set(idps) == {"oa_assertion", "wecom", "demo", "oidc"}
    assert isinstance(idps["oa_assertion"], OaAssertionIdP)
    assert isinstance(idps["wecom"], WeComIdP)
    assert isinstance(idps["demo"], DemoIdP)
    assert isinstance(idps["oidc"], OidcIdP)


def test_broker_verify_oidc_raises_not_implemented():
    broker = IdentityBroker(register_default_idps())
    ctx = IdPContext(now=1_700_000_000)
    with pytest.raises(AppError) as ei:
        broker.verify("oidc", {}, ctx=ctx)
    assert ei.value.status == 501
    assert ei.value.code == "IDP_NOT_IMPLEMENTED"


def test_broker_verify_oa_assertion_session_has_principal_and_oa():
    assertion, now = _signed_assertion()
    broker = IdentityBroker(register_default_idps())
    ctx = IdPContext(
        kv=MemoryKV(),
        secrets={"assertion_hmac_secret": HMAC_SECRET},
        now=now,
    )
    claims = broker.verify(
        "oa_assertion",
        {"assertion": assertion, "channel": "iframe"},
        ctx=ctx,
    )
    session = broker.session_from_claims(claims)
    assert session.principal_id == "zhangsan"
    assert session.oa == "zhangsan"
    assert session.display_name == "张三"
    assert session.channel == "iframe"
    assert session.uid == 7


def test_claims_from_oa_assertion_matches_verify_assertion_path():
    """Broker shim 与 verify_assertion + OaAssertionIdP 映射同构（各用独立 nonce）。"""
    now = 1_700_000_000
    a_shim, _ = _signed_assertion(now=now)
    a_direct, _ = _signed_assertion(now=now)
    a_idp, _ = _signed_assertion(now=now)

    claims = claims_from_oa_assertion(a_shim, HMAC_SECRET, MemoryKV(), now=now)
    verified = verify_assertion(a_direct, HMAC_SECRET, MemoryKV(), now=now)
    idp_claims = OaAssertionIdP().verify(
        {"assertion": a_idp, "channel": "oa_web"},
        ctx=IdPContext(
            kv=MemoryKV(),
            secrets={"assertion_hmac_secret": HMAC_SECRET},
            now=now,
        ),
    )

    assert claims.principal_id == verified["oa"] == idp_claims.principal_id
    assert claims.external_keys == {"oa": verified["oa"]} == idp_claims.external_keys
    assert claims.display_name == verified["display_name"] == idp_claims.display_name
    assert claims.raw == {
        "oa": verified["oa"],
        "uid": verified["uid"],
        "display_name": verified["display_name"],
    }
    assert claims.raw == idp_claims.raw
    assert claims.channel == "oa_web"


def test_broker_wecom_authorization_seeds_office_credentials():
    mock_client = MagicMock()
    mock_client.mint_by_wework.return_value = _mint_result()
    broker = IdentityBroker({"wecom": WeComIdP(client_factory=lambda: mock_client)})
    ctx = IdPContext(secrets={"gateway_secret": GATEWAY})
    claims = broker.verify("wecom", {"wework_user_id": "wx_zhangsan"}, ctx=ctx)
    session = broker.session_from_claims(claims)
    assert session.office_token == "tok-zhangsan"
    assert session.credentials[DEFAULT_UPSTREAM]["authorization"] == "tok-zhangsan"
    assert session.credentials["office"]["authorization"] == "tok-zhangsan"
    assert session.oa == "zhangsan"
    assert session.principal_id == "zhangsan"
    assert session.channel == "wecom"


def test_ensure_office_credentials_mints_when_missing():
    broker = IdentityBroker(register_default_idps())
    claims = PrincipalClaims(
        principal_id="zhangsan",
        display_name="张三",
        external_keys={"oa": "zhangsan"},
        channel="oa_web",
    )
    session = broker.session_from_claims(claims)
    assert not session.office_token

    def mint_fn(oa: str) -> tuple[str, int]:
        assert oa == "zhangsan"
        return "minted-tok", 9_999_999_999

    updated = broker.ensure_office_credentials(session, mint_fn=mint_fn)
    assert updated.office_token == "minted-tok"
    assert updated.credentials["office"]["authorization"] == "minted-tok"
    assert updated.token_expires_at == 9_999_999_999
