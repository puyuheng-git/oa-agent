"""open_oa_invoke：Executor POST /agent/invoke。"""

from __future__ import annotations

import httpx

from oa_agent.executor.executor import Identity, ToolExecutor
from oa_agent.executor.registry import ToolRegistry, ToolSpec
from oa_agent.integrations.open_oa import DEFAULT_UPSTREAM, INVOKE_PATH, OpenOaClient


class _Rec:
    def __init__(self) -> None:
        self.tool_call_count = 0
        self.events: list[dict] = []

    def event(self, kind, **kw) -> None:
        self.events.append({"kind": kind, **kw})


def _invoke_spec(**kwargs) -> ToolSpec:
    base = dict(
        name="query_my_travel_expense_list",
        method="POST",
        path=INVOKE_PATH,
        version="1#v1",
        schema_hash="h",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=10.0,
        inject_identity_fields=(),
        top_level_fields=(),
        query_params_field=None,
        model_params={"page": {"type": "integer"}, "limit": {"type": "integer"}},
        result_kind="list",
        result_fields=("id", "date"),
        upstream=DEFAULT_UPSTREAM,
        kind="open_oa_invoke",
        invoke_service="out_attendance/go_out_application",
        invoke_method="getTravelExpensePageList",
    )
    base.update(kwargs)
    return ToolSpec(**base)


def test_execute_open_oa_invoke_posts_service_method():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        import json
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"code": 0, "message": "ok", "data": {"list": [{"id": 9, "date": "2026-01-01", "secret": "x"}], "total": 1}},
        )

    client = OpenOaClient("http://open-oa.test", transport=httpx.MockTransport(handler))
    spec = _invoke_spec()
    ex = ToolExecutor(ToolRegistry({spec.name: spec}), clients={DEFAULT_UPSTREAM: client})
    out = ex.execute(
        spec.name,
        {"page": 1, "limit": 5, "oa": "attacker"},
        Identity(oa="real_user", authorization="Bearer tok"),
        _Rec(),
        "call_tool",
    )
    assert out["ok"] is True
    assert seen["method"] == "POST"
    assert seen["path"].endswith(INVOKE_PATH)
    assert seen["auth"] == "Bearer tok"
    assert seen["body"]["service"] == "out_attendance/go_out_application"
    assert seen["body"]["method"] == "getTravelExpensePageList"
    assert seen["body"]["args"].get("page") == 1
    assert "oa" not in seen["body"]["args"]
    assert out["data"]["list"] == [{"id": 9, "date": "2026-01-01"}]
