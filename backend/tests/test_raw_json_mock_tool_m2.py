"""M2 Task 6：raw_json + mock 非 OA 只读 Tool 端到端验收。"""

from __future__ import annotations

import httpx
import respx

from oa_agent.connectors import ConnectorHub, HttpJsonConnector
from oa_agent.executor.executor import Identity, ToolExecutor
from oa_agent.executor.registry import ToolRegistry, ToolSpec

MOCK_BASE = "https://mock.example"


class _Rec:
    """Minimal RunRecorder stand-in（同 test_connectors_m1）。"""

    def __init__(self) -> None:
        self.tool_call_count = 0
        self.events: list[dict] = []

    def event(self, kind, **kw) -> None:
        self.events.append({"kind": kind, **kw})


def _demo_list_spec(**over) -> ToolSpec:
    defaults = dict(
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
    defaults.update(over)
    return ToolSpec(**defaults)


@respx.mock
def test_raw_json_mock_tool_list_object_envelope() -> None:
    """GET /api/items 返回 {"items":[...]}，无 office code 信封；execute 成功且 connector_id=demo。"""
    body = {"items": [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}], "total": 2}
    route = respx.get(f"{MOCK_BASE}/api/items").mock(
        return_value=httpx.Response(200, json=body),
    )
    spec = _demo_list_spec()
    hub = ConnectorHub({
        "demo": HttpJsonConnector("demo", base_url=MOCK_BASE, envelope_profile="raw_json"),
    })
    ex = ToolExecutor(ToolRegistry({spec.name: spec}), clients={}, hub=hub)
    identity = Identity(
        oa="u1",
        authorization="",
        credentials={"demo": {"authorization": "Bearer demo-token"}},
    )
    rec = _Rec()

    result = ex.execute("demo_list_items", {}, identity, rec, "call_tool")

    assert result["ok"] is True
    assert result["data"]["list"] == [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]
    assert result["data"]["total"] == 2
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer demo-token"
    # 响应无 office {code,msg,data} 包装，execute 仍成功即证明不依赖 success code
    assert "code" not in body
    start = next(e for e in rec.events if e["kind"] == "tool_call_start")
    end = next(e for e in rec.events if e["kind"] == "tool_call_end")
    assert start["metadata"]["connector_id"] == "demo"
    assert end["metadata"]["connector_id"] == "demo"
    assert end["status"] == "ok"


@respx.mock
def test_raw_json_mock_tool_bare_json_list() -> None:
    """裸 JSON 列表同样可被 raw_json + list compact 识别。"""
    body = [{"id": 10, "name": "solo"}]
    respx.get(f"{MOCK_BASE}/api/items").mock(return_value=httpx.Response(200, json=body))
    spec = _demo_list_spec()
    hub = ConnectorHub({
        "demo": HttpJsonConnector("demo", base_url=MOCK_BASE, envelope_profile="raw_json"),
    })
    ex = ToolExecutor(ToolRegistry({spec.name: spec}), clients={}, hub=hub)
    identity = Identity(
        oa="u1",
        authorization="",
        credentials={"demo": {"authorization": "Bearer demo-token"}},
    )
    rec = _Rec()

    result = ex.execute("demo_list_items", {}, identity, rec, "call_tool")

    assert result["ok"] is True
    assert result["data"]["list"] == [{"id": 10, "name": "solo"}]
    assert result["data"]["total"] == 1
    end = next(e for e in rec.events if e["kind"] == "tool_call_end")
    assert end["metadata"]["connector_id"] == "demo"
    assert end["status"] == "ok"


def test_toolspec_envelope_profile_defaults_oa_office() -> None:
    spec = ToolSpec(
        name="legacy",
        method="GET",
        path="/x",
        version="1",
        schema_hash="h",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=10.0,
        inject_identity_fields=(),
        top_level_fields=(),
        query_params_field=None,
        model_params={},
        result_kind="object",
        result_fields=("id",),
    )
    assert spec.envelope_profile == "oa_office"
