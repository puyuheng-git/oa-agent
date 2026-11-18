"""外出申请路由 + 列表「全部/N 条」limit 收口。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from oa_agent.executor import tool_routing
from oa_agent.executor.executor import _resolve_invoke_call
from oa_agent.executor.registry import ToolSpec
from oa_agent.runtime import intent_rules
from oa_agent.runtime.graphs import oa_assistant


def _spec(**kwargs) -> ToolSpec:
    base = dict(
        name="x", method="POST", path="/agent/invoke", version="1", schema_hash="h",
        risk_level="low", requires_confirmation=False, timeout_seconds=10,
        inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params={}, result_kind="list", result_fields=("id",), summary="",
        kind="open_oa_invoke",
    )
    base.update(kwargs)
    return ToolSpec(**base)


def test_outing_application_is_not_travel_list_intent():
    parsed = intent_rules.parse("我的外出申请列表", date(2026, 11, 17))
    assert parsed["intent"] == "help"
    assert "source" not in parsed["params"]


def test_outing_plus_travel_still_list_with_source():
    parsed = intent_rules.parse("本月外出行程报销", date(2026, 11, 17))
    assert parsed["intent"] == "list"
    assert parsed["params"].get("source") == 1


def test_parse_list_limit_all_and_n():
    assert intent_rules.parse_list_limit("显示全部行程报销单") == -1
    assert intent_rules.parse_list_limit("全部显示") == -1
    assert intent_rules.parse_list_limit("显示前 10 条") == 10
    assert intent_rules.merge_list_limit_params("显示全部", {}, max_limit=20)["limit"] == 20
    assert intent_rules.merge_list_limit_params("最近3条", {}, max_limit=20)["limit"] == 3


def test_deterministic_routes_outing_application_tool():
    app = _spec(name="search_application_list", summary="获取外出申请列表")
    travel = _spec(
        name="query_my_travel_expense_list", summary="行程报销",
        model_params={"limit": {"type": "integer", "maximum": 20}},
    )
    tools = {
        "search_application_list": (app, SimpleNamespace(
            name="get_applications", display_name="获取外出申请列表", description="",
        )),
        "query_my_travel_expense_list": (travel, SimpleNamespace(
            name="travel_expense_query", display_name="行程报销查询", description="",
        )),
    }
    hit = tool_routing._try_deterministic(
        "我的外出申请列表", date(2026, 11, 17), tools, tool_routing.FALLBACK_RULE_TOOLS,
    )
    assert hit is not None
    assert hit["tool"] == "search_application_list"


def test_prefer_outing_application_overrides_travel():
    tools = {
        "search_application_list": (_spec(name="search_application_list", summary="获取外出申请列表"), None),
        "query_my_travel_expense_list": (_spec(
            name="query_my_travel_expense_list", summary="行程报销",
            model_params={"limit": {"type": "integer", "maximum": 20}, "source": {"type": "integer"}},
        ), None),
    }
    parsed = {
        "intent": "tool",
        "tool": "query_my_travel_expense_list",
        "params": {"source": 1, "limit": 15},
    }
    out = oa_assistant._prefer_outing_application(parsed, "我的外出申请列表", tools)
    assert out["tool"] == "search_application_list"
    assert out["params"] == {}


def test_apply_list_limit_all_uses_tool_max():
    tools = {
        "query_my_travel_expense_list": (_spec(
            name="query_my_travel_expense_list",
            model_params={"limit": {"type": "integer", "maximum": 20, "default": 10}},
        ), None),
    }
    parsed = {"intent": "tool", "tool": "query_my_travel_expense_list", "params": {"page": 1}}
    out = oa_assistant._apply_list_limit_from_message(
        parsed, "显示全部行程报销单", tools, default_limit=10,
    )
    assert out["params"]["limit"] == 20


def test_resolve_invoke_call_page_list_when_paginated():
    spec = _spec(
        name="query_my_travel_expense_list",
        invoke_call="one_by_params",
        model_params={
            "page": {"type": "integer"},
            "limit": {"type": "integer", "maximum": 20},
        },
    )
    assert _resolve_invoke_call(spec) == "page_list"


def test_fetch_all_pages_merges_until_total():
    calls = []

    class _Ex:
        def execute(self, name, args, identity, recorder, node):
            calls.append(dict(args))
            page = int(args["page"])
            if page == 1:
                return {"data": {"list": [{"id": 1}, {"id": 2}], "total": 5}}
            if page == 2:
                return {"data": {"list": [{"id": 3}, {"id": 4}], "total": 5}}
            return {"data": {"list": [{"id": 5}], "total": 5}}

    ctx = SimpleNamespace(
        executor=_Ex(),
        identity=SimpleNamespace(oa="a"),
        recorder=SimpleNamespace(),
    )
    spec = _spec(
        name="query_my_travel_expense_list",
        model_params={"page": {"type": "integer"}, "limit": {"type": "integer", "maximum": 20}},
    )
    first = {"data": {"list": [{"id": 1}, {"id": 2}], "total": 5}}
    out = oa_assistant._maybe_fetch_all_list_pages(
        ctx, "query_my_travel_expense_list", spec,
        {"page": 1, "limit": 2}, first, "显示全部",
    )
    assert [r["id"] for r in out["data"]["list"]] == [1, 2, 3, 4, 5]
    assert [c["page"] for c in calls] == [2, 3]
