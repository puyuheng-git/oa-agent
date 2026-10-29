"""M5 Task 6：channel → IdP JSON 映射配置。"""

from __future__ import annotations

from oa_agent.config.schema import GROUPS, default
from oa_agent.identity import IdPContext, IdentityBroker
from oa_agent.identity.broker import DEFAULT_CHANNEL_IDP_MAP, parse_channel_idp_map
from oa_agent.identity.claims import PrincipalClaims


class _StubIdP:
    def __init__(self, idp_id: str) -> None:
        self.id = idp_id

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        return PrincipalClaims(principal_id=self.id, channel=str(payload["channel"]))


def test_valid_override_selects_configured_idp() -> None:
    broker = IdentityBroker({
        "oa_assertion": _StubIdP("oa_assertion"),
        "demo": _StubIdP("demo"),
    })

    claims = broker.verify_channel(
        "oa_web",
        {"channel": "oa_web"},
        ctx=IdPContext(),
        channel_idp_map_json='{"oa_web":"demo"}',
    )

    assert claims.principal_id == "demo"


def test_invalid_json_falls_back_to_default_map() -> None:
    broker = IdentityBroker({"oa_assertion": _StubIdP("oa_assertion")})

    claims = broker.verify_channel(
        "oa_web",
        {"channel": "oa_web"},
        ctx=IdPContext(),
        channel_idp_map_json="{not-json",
    )

    assert claims.principal_id == "oa_assertion"


def test_non_object_and_missing_keys_fall_back_per_channel() -> None:
    assert parse_channel_idp_map("[]") == DEFAULT_CHANNEL_IDP_MAP
    assert parse_channel_idp_map('{"oa_web":"demo"}') == {
        **DEFAULT_CHANNEL_IDP_MAP,
        "oa_web": "demo",
    }


def test_schema_exposes_channel_idp_map_json_default() -> None:
    field = GROUPS["idp"].field("channel_idp_map_json")
    assert field is not None
    assert field.kind == "text"
    assert "预留：运行时入口尚未统一走 verify_channel" in field.help
    assert "暂不影响现网 OA/企微 launch" in field.help
    assert default("idp", "channel_idp_map_json") == (
        '{"oa_web":"oa_assertion","wecom":"wecom","demo":"demo"}'
    )
    assert "待 FieldDef 支持 dict" not in GROUPS["idp"].description
