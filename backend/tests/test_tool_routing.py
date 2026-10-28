"""工具路由模式：2-Tool 场景、确定性不调选 Tool 模型、事件开关。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest

from oa_agent.executor import tool_routing as tr
from oa_agent.runtime.chain_plan import plan_list_then_detail


@dataclass
class FakeSpec:
    name: str
    summary: str = ""
    description: str = ""
    model_params: dict | None = None
    result_kind: str = "list"
    result_fields: tuple = ("id",)
    result_labels: dict | None = None
    inject_identity_fields: tuple = ()
    identity_params: dict | None = None

    def __post_init__(self):
        self.model_params = self.model_params or {}
        self.result_labels = self.result_labels or {"id": "单号"}
        self.identity_params = self.identity_params or {}


@dataclass
class FakeSkill:
    name: str
    display_name: str
    description: str = ""
    instructions: str = ""
    tools: list | None = None


class FakeRecorder:
    def __init__(self):
        self.events = []

    def event(self, event_type, **kwargs):
        self.events.append({"event_type": event_type, **kwargs})


LIST = "query_my_travel_expense_list"
DETAIL = "query_my_travel_expense_detail"


def _two_tools(multi_skill: bool = False):
    list_spec = FakeSpec(LIST, summary="行程报销列表", description="查报销")
    detail_spec = FakeSpec(DETAIL, summary="行程报销详情", description="查详情", result_kind="object")
    if multi_skill:
        s1 = FakeSkill("travel", "行程报销", "报销相关", tools=[LIST, DETAIL])
        s2 = FakeSkill("other", "其他业务", "无关", tools=[])
        # 模拟另一 Skill 下的假 Tool
        other = FakeSpec("other_list", summary="考勤列表")
        s2.tools = ["other_list"]
        return {
            LIST: (list_spec, s1),
            DETAIL: (detail_spec, s1),
            "other_list": (other, s2),
        }
    skill = FakeSkill("travel", "行程报销", tools=[LIST, DETAIL])
    return {LIST: (list_spec, skill), DETAIL: (detail_spec, skill)}


def _route(mode: str, message: str, *, tools=None, llm_select=None, trace=True, **kw):
    tools = tools or _two_tools()
    rec = FakeRecorder()
    cfg = {**tr.ROUTING_DEFAULTS, "tool_routing_mode": mode, "routing_trace_enabled": trace, **kw}
    out = tr.route(
        message,
        tools=tools,
        today=date(2026, 10, 28),
        config=cfg,
        recorder=rec,
        llm_select=llm_select,
        chat_enabled=False,
    )
    return out, rec


@pytest.mark.parametrize("mode", list(tr.MODES))
def test_each_mode_two_tools_no_500(mode):
    out, rec = _route(mode, "查上周行程报销")
    assert out["intent"] in ("tool", "help", "chat", "ask")
    assert "routing_mode" in out
    assert any(e["event_type"] == "routing_decision" for e in rec.events)


def test_legacy_prompt_topk_includes_both_when_le_k():
    out, rec = _route("legacy_prompt", "查报销", prompt_topk=8)
    stages = [e for e in rec.events if e["event_type"] == "routing_stage"]
    assert stages
    assert set(stages[0]["metadata"]["candidates"]) >= {LIST, DETAIL}
    assert out["intent"] == "tool"
    assert out["tool"] == LIST


def test_skill_then_tool_does_not_cross_skill():
    tools = _two_tools(multi_skill=True)
    calls = []

    def llm_select(message, narrowed, opts):
        calls.append(list(narrowed.keys()))
        return {"intent": "tool", "tool": LIST, "params": {}, "intent_source": "llm"}

    out, _ = _route("skill_then_tool", "查报销", tools=tools, llm_select=llm_select)
    assert out["tool"] == LIST
    assert calls
    assert "other_list" not in calls[0]


def test_deterministic_first_skips_llm_on_rule_hit():
    called = {"n": 0}

    def llm_select(*_a, **_k):
        called["n"] += 1
        raise AssertionError("deterministic 命中时不应调用选 Tool 模型")

    out, rec = _route("deterministic_first", "查上周行程报销", llm_select=llm_select)
    assert called["n"] == 0
    assert out["intent"] == "tool"
    assert out["tool"] == LIST
    assert out["intent_source"] == "rules"
    assert any(e["event_type"] == "routing_stage" and e["metadata"].get("stage") == "deterministic"
               for e in rec.events)


def test_plan_list_then_detail_invoked_on_recent_detail():
    out, rec = _route("deterministic_first", "我最近一笔报销的详情")
    assert out["intent"] == "tool"
    assert out.get("steps") and len(out["steps"]) == 2
    assert out["steps"][0]["tool"] == LIST
    assert out["steps"][1]["tool"] == DETAIL
    # 真正调用了 plan_list_then_detail（步骤与其契约一致）
    plan = plan_list_then_detail(LIST, DETAIL, "id")
    assert plan[0]["tool"] == out["steps"][0]["tool"]


def test_routing_trace_toggle():
    _, on = _route("legacy_prompt", "查报销", trace=True)
    _, off = _route("legacy_prompt", "查报销", trace=False)
    assert any(e["event_type"].startswith("routing_") for e in on.events)
    assert not any(e["event_type"].startswith("routing_") for e in off.events)


def test_search_capabilities_returns_ranked_summaries():
    tools = _two_tools()
    hits = tr.search_capabilities("查报销列表", tools, top_k=2)
    assert hits
    assert all("name" in h and "summary" in h for h in hits)
    assert "model_params" not in hits[0]
    assert LIST in {h["name"] for h in hits}


def test_get_tool_schema_exposes_params_not_identity():
    tools = _two_tools()
    tools[LIST][0].model_params = {
        "start_date": {"type": "string", "required": True, "description": "开始"},
        "oa": {"type": "string", "required": False},
    }
    tools[LIST][0].inject_identity_fields = ("oa",)
    schema = tr.get_tool_schema(LIST, tools)
    assert schema is not None
    assert schema["name"] == LIST
    assert "start_date" in schema["model_params"]
    assert "oa" not in schema["model_params"]  # 身份字段不暴露
    assert tr.get_tool_schema("missing", tools) is None


def test_meta_search_runs_without_fallback():
    out, rec = _route("meta_search", "查报销")
    assert out["routing_mode"] == "meta_search"
    assert out.get("routing_fallback_from") in (None, "")
    assert out["intent"] == "tool"
    assert out["tool"] == LIST
    stages = [e for e in rec.events if e["event_type"] == "routing_stage"]
    assert any(e["metadata"].get("stage") == "meta_search" for e in stages)
    assert any(e["metadata"].get("meta_call") == "search_capabilities" for e in stages)
    assert any(e["metadata"].get("meta_call") == "get_tool_schema" for e in stages)
    assert not any(e["metadata"].get("degrade_to") for e in stages)


def test_meta_search_llm_meta_protocol_then_tool():
    calls = {"n": 0}
    tools = _two_tools()
    tools[LIST][0].model_params = {"start_date": {"type": "string", "required": False}}

    def llm_select(message, narrowed, opts):
        calls["n"] += 1
        assert opts.get("meta") is True
        state = opts.get("meta_state") or {}
        if not state.get("hits"):
            return {
                "intent": "meta",
                "meta_call": {"name": "search_capabilities", "args": {"query": "报销"}},
                "intent_source": "llm",
            }
        if not state.get("schemas"):
            return {
                "intent": "meta",
                "meta_call": {"name": "get_tool_schema", "args": {"tool_name": LIST}},
                "intent_source": "llm",
            }
        return {"intent": "tool", "tool": LIST, "params": {"start_date": "2026-10-01"}, "intent_source": "llm"}

    out, rec = _route("meta_search", "查报销", tools=tools, llm_select=llm_select, meta_max_rounds=5)
    assert calls["n"] >= 3
    assert out["routing_mode"] == "meta_search"
    assert out["tool"] == LIST
    assert out["params"].get("start_date") == "2026-10-01"
    assert out.get("intent_source") == "llm"


def test_meta_search_exceeds_max_rounds_clarifies():
    def llm_select(message, narrowed, opts):
        # 每轮都只搜，耗尽往返
        return {
            "intent": "meta",
            "meta_call": {"name": "search_capabilities", "args": {"query": message}},
            "intent_source": "llm",
        }

    out, rec = _route(
        "meta_search", "查报销", llm_select=llm_select,
        meta_max_rounds=2, routing_clarify_on_low_confidence=True,
    )
    assert out["intent"] == "chat"
    assert out.get("chat_reply")
    assert any(e["event_type"] == "routing_clarify" for e in rec.events)
    meta_rounds = [
        e for e in rec.events
        if e["event_type"] == "routing_stage" and e["metadata"].get("stage") == "meta_search"
    ]
    assert len(meta_rounds) <= 2


def test_resolve_priority_workflow_over_runtime():
    cfg = tr.resolve_routing_config(
        {"tool_routing_mode": "skill_then_tool"},
        {"tool_routing_mode": "legacy_prompt"},
    )
    assert cfg["tool_routing_mode"] == "skill_then_tool"


def test_resolve_runtime_when_workflow_omits():
    cfg = tr.resolve_routing_config({}, {"tool_routing_mode": "retrieve_then_tool"})
    assert cfg["tool_routing_mode"] == "retrieve_then_tool"


def test_deterministic_fallback_cannot_be_self():
    cfg = tr.resolve_routing_config(
        {"tool_routing_mode": "deterministic_first", "deterministic_fallback_mode": "deterministic_first"},
        None,
    )
    assert cfg["deterministic_fallback_mode"] == "skill_then_tool"


def test_router_then_fill_passes_stage_router_and_fill():
    """有 llm_select 时：先 stage=router 选 Tool，再 stage=fill 填参（规则未带参时）。"""
    stages: list[str | None] = []

    def llm_select(message, narrowed, opts):
        stages.append(opts.get("stage"))
        if opts.get("stage") == "router":
            return {"intent": "tool", "tool": DETAIL, "params": {}, "intent_source": "llm"}
        return {
            "intent": "tool",
            "tool": DETAIL,
            "params": {"id": "R1"},
            "intent_source": "llm",
        }

    out, rec = _route(
        "router_then_fill",
        "那个单据帮我看看细节吧嗯嗯",
        llm_select=llm_select,
    )
    assert stages.count("router") >= 1
    assert stages.count("fill") >= 1
    assert out["tool"] == DETAIL
    assert out["params"].get("id") == "R1"
    assert any(
        e["event_type"] == "routing_stage" and e["metadata"].get("stage") == "router_llm"
        for e in rec.events
    )


def test_router_then_fill_keyword_fallback_without_llm():
    """无 llm_select 时仍可走关键词/规则选 Tool。"""
    out, _ = _route("router_then_fill", "查上周行程报销", llm_select=None)
    assert out["intent"] == "tool"
    assert out["tool"] == LIST
