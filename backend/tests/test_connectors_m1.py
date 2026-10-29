"""M1 Connector Protocol / ConnectorResult / ConnectorError."""

from __future__ import annotations

import httpx
import pytest
import respx

from oa_agent.chat import service as chat_service
from oa_agent.connectors import Connector, ConnectorError, ConnectorHub, ConnectorResult, HttpJsonConnector
from oa_agent.integrations.office_api import OfficeApiClient, OfficeApiError, upstream_connectors
from tests.test_chat import OFFICE, runtime  # noqa: F401

OFFICE_BASE = "https://office-api.test"


class FakeConnector:
    """Minimal Connector for protocol checks."""

    @property
    def id(self) -> str:
        return "fake"

    def invoke(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        authorization: str,
        timeout: float | None = None,
        idempotency_key: str | None = None,
    ) -> ConnectorResult:
        return ConnectorResult(
            data={"method": method, "path": path, "params": params, "json": json_body},
            http_status=200,
            duration_ms=7,
            message="",
        )


def test_fake_connector_satisfies_protocol() -> None:
    assert isinstance(FakeConnector(), Connector)


def test_invoke_returns_connector_result() -> None:
    conn = FakeConnector()
    result = conn.invoke(
        "GET",
        "/agent/example",
        params={"q": "1"},
        authorization="Bearer tok",
    )
    assert isinstance(result, ConnectorResult)
    assert result.http_status == 200
    assert result.duration_ms == 7
    assert result.message == ""
    assert result.data["path"] == "/agent/example"
    assert result.data["method"] == "GET"


def test_connector_error_fields_match_office_api_error_spirit() -> None:
    err = ConnectorError(
        "UPSTREAM_BIZ_ERROR",
        "biz failed",
        http_status=200,
        user_message="请检查参数",
    )
    assert str(err) == "biz failed"
    assert err.code == "UPSTREAM_BIZ_ERROR"
    assert err.http_status == 200
    assert err.user_message == "请检查参数"
    assert "密钥" not in err.message  # redacted path exercised separately if needed


def test_connector_error_codes_align_with_office_api_error() -> None:
    """Task 3 maps OfficeApiError → ConnectorError; codes stay the same strings."""
    codes = (
        "OFFICE_API_NOT_CONFIGURED",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_UNAVAILABLE",
        "UPSTREAM_HTTP_ERROR",
        "UPSTREAM_BIZ_ERROR",
        "UPSTREAM_BAD_RESPONSE",
        "OFFICE_TOKEN_EXPIRED",
        "MINT_FAILED",
    )
    for code in codes:
        assert ConnectorError(code, "m").code == OfficeApiError(code, "m").code


@respx.mock
def test_http_json_connector_get_success() -> None:
    route = respx.get(f"{OFFICE_BASE}/agent/example").mock(
        return_value=httpx.Response(200, json={"code": "0", "data": {"items": [1]}, "msg": "ok"}),
    )
    client = OfficeApiClient(OFFICE_BASE)
    conn = HttpJsonConnector("office", client)
    assert conn.id == "office"
    assert isinstance(conn, Connector)

    result = conn.invoke(
        "GET",
        "/agent/example",
        params={"q": "1"},
        authorization="Bearer tok",
    )
    assert isinstance(result, ConnectorResult)
    assert result.http_status == 200
    assert result.data == {"items": [1]}
    assert result.duration_ms >= 0
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert route.calls.last.request.url.params["q"] == "1"


@respx.mock
def test_http_json_connector_biz_error_maps_to_connector_error() -> None:
    respx.get(f"{OFFICE_BASE}/agent/example").mock(
        return_value=httpx.Response(200, json={"code": "500", "msg": "参数错误", "data": None}),
    )
    conn = HttpJsonConnector("office", OfficeApiClient(OFFICE_BASE))

    with pytest.raises(ConnectorError) as exc_info:
        conn.invoke("GET", "/agent/example", authorization="Bearer tok")

    err = exc_info.value
    assert err.code == "UPSTREAM_BIZ_ERROR"
    assert err.http_status == 200
    assert err.user_message == "参数错误"
    assert "500" in err.message


@respx.mock
def test_http_json_connector_raw_json_returns_body_without_code_unwrap() -> None:
    """raw_json：整段 JSON 即 data，不按 office {code,msg,data} 解包。"""
    mock_base = "https://mock.example"
    body = {"items": [{"id": 1}], "code": "500", "msg": "would-be-biz-error"}
    route = respx.get(f"{mock_base}/api/items").mock(
        return_value=httpx.Response(200, json=body),
    )
    conn = HttpJsonConnector(
        "demo",
        base_url=mock_base,
        envelope_profile="raw_json",
    )
    result = conn.invoke("GET", "/api/items", authorization="Bearer tok")
    assert isinstance(result, ConnectorResult)
    assert result.http_status == 200
    assert result.data == body
    assert result.message == ""
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


def test_connector_hub_from_legacy_office_base_url() -> None:
    hub = ConnectorHub.from_office_settings({"office_api_base_url": OFFICE_BASE})
    assert "office" in hub
    assert hub.names() == frozenset({"office"})
    conn = hub.get("office")
    assert conn is not None
    assert isinstance(conn, HttpJsonConnector)
    assert conn.id == "office"
    assert hub.get("missing") is None


def test_upstream_connectors_matches_from_office_settings() -> None:
    settings = {
        "upstreams": [
            {"key": "office", "label": "office-api", "base_url": OFFICE_BASE},
            {"key": "hr", "label": "人事", "base_url": "http://hr.test/api"},
        ],
    }
    hub = upstream_connectors(settings)
    assert hub.names() == frozenset({"office", "hr"})
    assert all(isinstance(hub.get(k), HttpJsonConnector) for k in ("office", "hr"))


def test_tool_connectors_uses_runtime_oa_settings(admin) -> None:
    from tests.test_upstreams import set_upstreams

    assert set_upstreams(admin, [{"key": "office", "label": "office-api", "base_url": OFFICE}]).status_code == 200
    hub = chat_service.tool_connectors(runtime(admin.client))
    assert "office" in hub
    assert hub.get("office") is not None


def test_identity_principal_id_defaults_to_oa() -> None:
    from oa_agent.executor.executor import Identity

    assert Identity(oa="u1", authorization="t").principal_id == "u1"
    assert Identity(oa="u1", authorization="t", principal_id="p1").principal_id == "p1"


def test_executor_hub_records_connector_id_in_metadata() -> None:
    """Task 5: hub 路径调用 FakeConnector，tool_call_* metadata 含 connector_id。"""
    from oa_agent.executor.executor import Identity, ToolExecutor
    from oa_agent.executor.registry import ToolRegistry, ToolSpec

    class _Rec:
        def __init__(self) -> None:
            self.tool_call_count = 0
            self.events: list[dict] = []

        def event(self, kind, **kw) -> None:
            self.events.append({"kind": kind, **kw})

    class RecordingConnector(FakeConnector):
        def __init__(self) -> None:
            self.calls: list[dict] = []

        @property
        def id(self) -> str:
            return "office"

        def invoke(
            self,
            method: str,
            path: str,
            *,
            params: dict | None = None,
            json_body: dict | None = None,
            authorization: str,
            timeout: float | None = None,
            idempotency_key: str | None = None,
        ) -> ConnectorResult:
            self.calls.append({"method": method, "path": path, "params": params, "authorization": authorization})
            return ConnectorResult(
                data={"list": [{"id": 1}], "total": 1},
                http_status=200,
                duration_ms=3,
                message="",
            )

    spec = ToolSpec(
        name="query_x",
        method="GET",
        path="/agent/x",
        version="1",
        schema_hash="h",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=10.0,
        inject_identity_fields=("oa",),
        top_level_fields=(),
        query_params_field="queryParams",
        model_params={},
        result_kind="list",
        result_fields=("id",),
        upstream="office",
    )
    conn = RecordingConnector()
    hub = ConnectorHub({"office": conn})
    ex = ToolExecutor(ToolRegistry({spec.name: spec}), clients={}, hub=hub)
    rec = _Rec()

    result = ex.execute("query_x", {}, Identity(oa="u1", authorization="Bearer t"), rec, "call_tool")

    assert result["ok"] is True
    assert result["data"]["list"] == [{"id": 1}]
    assert len(conn.calls) == 1
    assert conn.calls[0]["path"] == "/agent/x"
    assert conn.calls[0]["authorization"] == "Bearer t"
    start = next(e for e in rec.events if e["kind"] == "tool_call_start")
    end = next(e for e in rec.events if e["kind"] == "tool_call_end")
    assert start["metadata"]["connector_id"] == "office"
    assert end["metadata"]["connector_id"] == "office"
    assert end["status"] == "ok"
