"""M4 Task 5：Demo IdP + demo_http pack，无 office_api_base_url 可建会话并调 raw_json Tool。"""

from __future__ import annotations

import httpx
import pytest
import respx

from oa_agent.config.schema import GROUPS, default
from oa_agent.connectors import ConnectorHub, HttpJsonConnector
from oa_agent.errors import AppError
from oa_agent.executor.executor import Identity, ToolExecutor
from oa_agent.executor.registry import ToolRegistry, ToolSpec
from oa_agent.identity import IdPContext, IdentityBroker, register_default_idps
from oa_agent.identity.adapters import DemoIdP
from oa_agent.packs.loader import discover_packs
from oa_agent.settings import REPO_ROOT

MOCK_BASE = "https://mock-demo.example"
DEMO_SECRET = "local-demo-secret"


class _Rec:
    def __init__(self) -> None:
        self.tool_call_count = 0
        self.events: list[dict] = []

    def event(self, kind, **kw) -> None:
        self.events.append({"kind": kind, **kw})


def test_idp_schema_defaults():
    assert "idp" in GROUPS
    assert default("idp", "demo_idp_enabled") is False
    assert default("idp", "demo_shared_secret") == ""


def test_discover_packs_finds_demo_http():
    manifests = discover_packs(REPO_ROOT / "packs")
    ids = {m.id for m in manifests}
    assert "demo_http" in ids
    demo = next(m for m in manifests if m.id == "demo_http")
    assert demo.connectors == ("demo",)
    assert demo.default_enabled is True
    assert demo.skills == ()
    assert demo.tools_openapi == ()
    assert demo.rules == "rules/intent.yaml"


def test_demo_idp_disabled_without_flag():
    idp = DemoIdP()
    ctx = IdPContext(secrets={"demo_shared_secret": DEMO_SECRET})
    with pytest.raises(AppError) as ei:
        idp.verify(
            {"principal_id": "demo_user", "secret": DEMO_SECRET},
            ctx=ctx,
        )
    assert ei.value.status == 403
    assert ei.value.code == "DEMO_IDP_DISABLED"


def test_demo_broker_session_with_credentials_demo():
    broker = IdentityBroker(register_default_idps())
    ctx = IdPContext(
        secrets={
            "demo_idp_enabled": True,
            "demo_shared_secret": DEMO_SECRET,
        }
    )
    claims = broker.verify(
        "demo",
        {
            "principal_id": "demo_user",
            "display_name": "Demo",
            "secret": DEMO_SECRET,
        },
        ctx=ctx,
    )
    assert claims.principal_id == "demo_user"
    assert claims.channel == "demo"
    assert claims.raw["authorization"] == "Bearer demo-token"

    session = broker.session_from_claims(claims)
    assert session.principal_id == "demo_user"
    assert session.oa == "demo_user"
    assert session.channel == "demo"
    assert session.office_token == ""
    assert "demo" in session.credentials
    assert session.credentials["demo"]["authorization"] == "Bearer demo-token"
    # 无 office 上游凭证
    assert "office" not in session.credentials


@respx.mock
def test_demo_raw_json_tool_without_office_clients() -> None:
    """clients={}，Hub 仅 demo connector；不依赖 office_api_base_url。"""
    body = {"items": [{"id": 1, "name": "alpha"}], "total": 1}
    route = respx.get(f"{MOCK_BASE}/api/items").mock(
        return_value=httpx.Response(200, json=body),
    )
    spec = ToolSpec(
        name="demo_list_items",
        method="GET",
        path="/api/items",
        version="1",
        schema_hash="h",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=10.0,
        inject_identity_fields=(),
        top_level_fields=(),
        query_params_field=None,
        model_params={},
        result_kind="list",
        result_fields=("id", "name"),
        upstream="demo",
        identity_bindings=(),
        envelope_profile="raw_json",
    )
    hub = ConnectorHub({
        "demo": HttpJsonConnector("demo", base_url=MOCK_BASE, envelope_profile="raw_json"),
    })
    ex = ToolExecutor(ToolRegistry({spec.name: spec}), clients={}, hub=hub)

    broker = IdentityBroker(register_default_idps())
    claims = broker.verify(
        "demo",
        {
            "principal_id": "demo_user",
            "secret": DEMO_SECRET,
            "demo_enabled": True,
        },
        ctx=IdPContext(secrets={"demo_shared_secret": DEMO_SECRET}),
    )
    session = broker.session_from_claims(claims)
    identity = Identity(
        oa=session.oa,
        authorization="",
        credentials=dict(session.credentials),
    )
    rec = _Rec()

    result = ex.execute("demo_list_items", {}, identity, rec, "call_tool")

    assert result["ok"] is True
    assert result["data"]["list"] == [{"id": 1, "name": "alpha"}]
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer demo-token"
    end = next(e for e in rec.events if e["kind"] == "tool_call_end")
    assert end["metadata"]["connector_id"] == "demo"
    assert end["status"] == "ok"
