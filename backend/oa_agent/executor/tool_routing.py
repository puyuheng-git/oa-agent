"""可配置的 Tool/Skill 路由流水线（规格 2026-10-28）。

route() 是 oa_assistant.understand 的唯一选 Tool 入口。
优先级：工作流发布快照 > runtime 全局默认 > 代码默认。
写操作不走本模块（固定写 Workflow）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from oa_agent.executor.tool_select import select_top_tools
from oa_agent.runtime import intent_rules
from oa_agent.runtime.chain_plan import plan_list_then_detail
from oa_agent.runtime.intent_rules import DETAIL, LIST

TOOL = "tool"
HELP = "help"
ASK = "ask"
CHAT = "chat"
CLARIFY = "clarify"

MODES = (
    "legacy_prompt",
    "skill_then_tool",
    "retrieve_then_tool",
    "meta_search",
    "deterministic_first",
    "router_then_fill",
)

ROUTING_KEYS = (
    "tool_routing_mode",
    "prompt_topk",
    "routing_skill_method",
    "retrieve_topk",
    "retrieve_backend",
    "retrieve_must_include_recent",
    "meta_max_rounds",
    "deterministic_fallback_mode",
    "router_model_id",
    "routing_clarify_on_low_confidence",
    "routing_trace_enabled",
)

ROUTING_DEFAULTS: dict[str, Any] = {
    "tool_routing_mode": "legacy_prompt",
    "prompt_topk": 8,
    "routing_skill_method": "rules_then_llm",
    "retrieve_topk": 8,
    "retrieve_backend": "keyword",
    "retrieve_must_include_recent": 2,
    "meta_max_rounds": 3,
    "deterministic_fallback_mode": "skill_then_tool",
    "router_model_id": None,
    "routing_clarify_on_low_confidence": True,
    "routing_trace_enabled": True,
}

# 无 PackRegistry 时的回退映射（单测 / 未注入 registry 场景）
FALLBACK_RULE_TOOLS = {
    LIST: "query_my_travel_expense_list",
    DETAIL: "query_my_travel_expense_detail",
}
RULE_TOOLS = FALLBACK_RULE_TOOLS  # 兼容旧引用
LIST_TOOL = FALLBACK_RULE_TOOLS[LIST]
DETAIL_TOOL = FALLBACK_RULE_TOOLS[DETAIL]
_DETAIL_CHAIN = re.compile(r"最近一笔|最新一笔|最后一笔|第一条的详情|最近.*详情")


def _resolve_rule_tool_map(rule_tool_map: dict[str, str] | None) -> dict[str, str]:
    return dict(FALLBACK_RULE_TOOLS if rule_tool_map is None else rule_tool_map)

LlmSelectFn = Callable[[str, dict, dict], dict | None]
RulesSelectFn = Callable[[str, date, dict], dict]


@dataclass
class RoutingDecision:
    mode: str
    action: str  # tool|chat|clarify|help|ask
    stages: list[dict] = field(default_factory=list)
    candidate_skills: list[str] = field(default_factory=list)
    candidate_tools: list[str] = field(default_factory=list)
    chosen_skill: str | None = None
    chosen_tool: str | None = None
    args: dict = field(default_factory=dict)
    clarify_question: str | None = None
    fallback_from: str | None = None
    intent_source: str = "rules"
    steps: list[dict] | None = None
    chat_reply: str | None = None
    missing: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def as_understand(self) -> dict:
        if self.extra.get("intent") in ("memory_write", "memory_forget"):
            out = {
                "intent": self.extra["intent"],
                "tool": None,
                "params": {},
                "intent_source": self.intent_source,
                "routing_mode": self.mode,
                "routing_fallback_from": self.fallback_from,
            }
            for k, v in self.extra.items():
                if k != "intent":
                    out[k] = v
            return out
        out: dict[str, Any] = {
            "intent": HELP,
            "tool": self.chosen_tool,
            "params": dict(self.args),
            "intent_source": self.intent_source,
            "routing_mode": self.mode,
            "routing_fallback_from": self.fallback_from,
        }
        if self.action == TOOL:
            out["intent"] = TOOL
        elif self.action == ASK:
            out["intent"] = ASK
        elif self.action == CHAT or self.action == CLARIFY:
            out["intent"] = CHAT
            out["tool"] = None
            out["params"] = {}
            if self.action == CLARIFY and self.clarify_question:
                out["chat_reply"] = self.clarify_question
            elif self.chat_reply:
                out["chat_reply"] = self.chat_reply
        if self.steps:
            out["steps"] = self.steps
        if self.missing:
            out["missing"] = list(self.missing)
        for k, v in self.extra.items():
            if k not in out:
                out[k] = v
        return out


def resolve_routing_config(workflow_config: dict | None, runtime_defaults: dict | None = None) -> dict:
    """工作流快照 > runtime 全局 > 代码默认。"""
    wf = workflow_config or {}
    rt = runtime_defaults or {}
    out = dict(ROUTING_DEFAULTS)
    for key in ROUTING_KEYS:
        if key in rt and rt[key] is not None:
            out[key] = rt[key]
        if key in wf and wf[key] is not None:
            out[key] = wf[key]
    mode = out.get("tool_routing_mode") or "legacy_prompt"
    if mode not in MODES:
        mode = "legacy_prompt"
    out["tool_routing_mode"] = mode
    fallback = out.get("deterministic_fallback_mode") or "skill_then_tool"
    if fallback == "deterministic_first" or fallback not in MODES:
        fallback = "skill_then_tool"
    out["deterministic_fallback_mode"] = fallback
    return out


def route(
    message: str,
    *,
    tools: dict,
    today: date,
    config: dict,
    runtime_defaults: dict | None = None,
    recent_tool_names: list[str] | None = None,
    recorder: Any = None,
    llm_select: LlmSelectFn | None = None,
    rules_select: RulesSelectFn | None = None,
    chat_enabled: bool = False,
    rule_tool_map: dict[str, str] | None = None,
) -> dict:
    """统一路由入口。返回与 _understand 兼容的 dict。

    ``rule_tool_map``：意图 key → Tool 名；为 None 时使用 FALLBACK_RULE_TOOLS（无 registry 的单测）。
    """
    cfg = resolve_routing_config(config, runtime_defaults)
    mode = cfg["tool_routing_mode"]
    trace = bool(cfg.get("routing_trace_enabled", True))
    resolved_map = _resolve_rule_tool_map(rule_tool_map)
    t0 = time.perf_counter()
    _emit(recorder, trace, "routing_start", metadata={
        "mode": mode,
        "message_chars": len(message or ""),
        "candidate_tool_count": len(tools),
    })

    decision = _dispatch(
        mode,
        message=message,
        tools=tools,
        today=today,
        cfg=cfg,
        recent_tool_names=recent_tool_names or [],
        llm_select=llm_select,
        rules_select=rules_select,
        chat_enabled=chat_enabled,
        recorder=recorder,
        trace=trace,
        fallback_from=None,
        depth=0,
        rule_tool_map=resolved_map,
    )
    duration_ms = int((time.perf_counter() - t0) * 1000)
    _emit(
        recorder,
        trace,
        "routing_decision",
        duration_ms=duration_ms,
        tool_name=decision.chosen_tool,
        metadata={
            "mode": decision.mode,
            "action": decision.action,
            "skill": decision.chosen_skill,
            "tool": decision.chosen_tool,
            "fallback_from": decision.fallback_from,
            "clarify": bool(decision.clarify_question),
            "candidate_tools": decision.candidate_tools[:32],
            "candidate_skills": decision.candidate_skills[:32],
        },
    )
    if decision.action == CLARIFY and decision.clarify_question:
        _emit(recorder, trace, "routing_clarify", metadata={"question": decision.clarify_question[:500]})
    return decision.as_understand()


def _dispatch(
    mode: str,
    *,
    message: str,
    tools: dict,
    today: date,
    cfg: dict,
    recent_tool_names: list[str],
    llm_select: LlmSelectFn | None,
    rules_select: RulesSelectFn | None,
    chat_enabled: bool,
    recorder: Any,
    trace: bool,
    fallback_from: str | None,
    depth: int,
    rule_tool_map: dict[str, str],
) -> RoutingDecision:
    if depth > 2:
        return _help_decision(mode, fallback_from, "routing_depth_exceeded")

    if mode == "legacy_prompt":
        return _legacy_prompt(
            message, tools, today, cfg, llm_select, rules_select, chat_enabled,
            recorder, trace, fallback_from, rule_tool_map,
        )
    if mode == "skill_then_tool":
        return _skill_then_tool(
            message, tools, today, cfg, llm_select, rules_select, chat_enabled,
            recorder, trace, fallback_from, rule_tool_map,
        )
    if mode == "retrieve_then_tool":
        return _retrieve_then_tool(
            message, tools, today, cfg, recent_tool_names, llm_select, rules_select,
            chat_enabled, recorder, trace, fallback_from, rule_tool_map,
        )
    if mode == "deterministic_first":
        return _deterministic_first(
            message, tools, today, cfg, recent_tool_names, llm_select, rules_select,
            chat_enabled, recorder, trace, fallback_from, depth, rule_tool_map,
        )
    if mode == "meta_search":
        return _meta_search(
            message, tools, today, cfg, recent_tool_names, llm_select, rules_select,
            chat_enabled, recorder, trace, fallback_from, rule_tool_map,
        )
    if mode == "router_then_fill":
        return _router_then_fill(
            message, tools, today, cfg, llm_select, rules_select, chat_enabled,
            recorder, trace, fallback_from, rule_tool_map,
        )
    return _legacy_prompt(
        message, tools, today, cfg, llm_select, rules_select, chat_enabled,
        recorder, trace, fallback_from or "unknown_mode", rule_tool_map,
    )


def _legacy_prompt(
    message, tools, today, cfg, llm_select, rules_select, chat_enabled,
    recorder, trace, fallback_from, rule_tool_map,
) -> RoutingDecision:
    top_k = int(cfg.get("prompt_topk") or 8)
    narrowed = _topk_tools(message, tools, top_k)
    names = list(narrowed.keys())
    _stage(recorder, trace, "topk", duration_ms=0, candidates=names, metadata={
        "top_k": top_k, "visible": len(tools), "picked": len(names),
    })
    parsed = _run_llm_or_rules(
        message, narrowed, tools, today, llm_select, rules_select, chat_enabled,
        full_tools=tools, rule_tool_map=rule_tool_map,
    )
    return _decision_from_parsed(
        "legacy_prompt", parsed, names, fallback_from=fallback_from, tools=tools,
    )


def _skill_then_tool(
    message, tools, today, cfg, llm_select, rules_select, chat_enabled,
    recorder, trace, fallback_from, rule_tool_map,
) -> RoutingDecision:
    t0 = time.perf_counter()
    skill_name, skill_tools, scores = _select_skill(
        message, tools, cfg.get("routing_skill_method") or "rules_then_llm", rule_tool_map,
    )
    _stage(recorder, trace, "skill_select", duration_ms=int((time.perf_counter() - t0) * 1000),
           candidates=list({s for s, _ in scores}), metadata={"scores": scores[:16], "chosen": skill_name})
    if not skill_tools:
        if cfg.get("routing_clarify_on_low_confidence", True):
            return RoutingDecision(
                mode="skill_then_tool", action=CLARIFY,
                clarify_question="请问你想查询哪一类信息？可以说「行程报销」或具体业务名称。",
                fallback_from=fallback_from, intent_source="rules",
                candidate_skills=[s for s, _ in scores],
            )
        return _help_decision("skill_then_tool", fallback_from)

    narrowed = {n: tools[n] for n in skill_tools if n in tools}
    parsed = _run_llm_or_rules(
        message, narrowed, tools, today, llm_select, rules_select, chat_enabled,
        full_tools=tools, rule_tool_map=rule_tool_map,
    )
    dec = _decision_from_parsed(
        "skill_then_tool", parsed, list(narrowed.keys()), fallback_from=fallback_from, tools=tools,
    )
    dec.chosen_skill = skill_name
    dec.candidate_skills = [s for s, _ in scores]
    return dec


def _retrieve_then_tool(
    message, tools, today, cfg, recent_tool_names, llm_select, rules_select,
    chat_enabled, recorder, trace, fallback_from, rule_tool_map,
) -> RoutingDecision:
    t0 = time.perf_counter()
    backend = cfg.get("retrieve_backend") or "keyword"
    used_backend = "keyword"
    if backend == "embedding":
        used_backend = "keyword"  # embedding 未就绪：强制降级
    top_n = int(cfg.get("retrieve_topk") or 8)
    must_n = int(cfg.get("retrieve_must_include_recent") or 0)
    candidates = _tools_as_candidates(tools)
    skill_bound = [n for n, (_, sk) in tools.items() if sk is not None]
    picked = select_top_tools(message, candidates=candidates, skill_tool_names=skill_bound, top_k=top_n)
    if must_n > 0 and recent_tool_names:
        for name in recent_tool_names:
            if name in tools and name not in picked:
                picked.insert(0, name)
            if sum(1 for n in picked if n in recent_tool_names) >= must_n and len(picked) >= top_n:
                break
        # 去重并截断
        seen, ordered = set(), []
        for n in picked:
            if n not in seen and n in tools:
                seen.add(n)
                ordered.append(n)
        picked = ordered[: max(top_n, must_n)]
    _stage(recorder, trace, "retrieve", duration_ms=int((time.perf_counter() - t0) * 1000),
           candidates=picked, metadata={
               "backend": used_backend,
               "requested_backend": backend,
               "fallback": "keyword" if backend == "embedding" else None,
               "top_n": top_n,
           })
    narrowed = {n: tools[n] for n in picked if n in tools} or tools
    parsed = _run_llm_or_rules(
        message, narrowed, tools, today, llm_select, rules_select, chat_enabled,
        full_tools=tools, rule_tool_map=rule_tool_map,
    )
    return _decision_from_parsed(
        "retrieve_then_tool", parsed, list(narrowed.keys()),
        fallback_from=fallback_from or ("embedding→keyword" if backend == "embedding" else fallback_from),
        tools=tools,
    )


def _deterministic_first(
    message, tools, today, cfg, recent_tool_names, llm_select, rules_select,
    chat_enabled, recorder, trace, fallback_from, depth, rule_tool_map,
) -> RoutingDecision:
    t0 = time.perf_counter()
    hit = _try_deterministic(message, today, tools, rule_tool_map)
    _stage(recorder, trace, "deterministic", duration_ms=int((time.perf_counter() - t0) * 1000),
           candidates=[hit["tool"]] if hit and hit.get("tool") else [],
           metadata={"hit": bool(hit), "plan": "plan_list_then_detail" if hit and hit.get("steps") else "rules"})
    if hit:
        return RoutingDecision(
            mode="deterministic_first",
            action=TOOL if hit.get("intent") == TOOL else HELP,
            chosen_tool=hit.get("tool"),
            args=hit.get("params") or {},
            steps=hit.get("steps"),
            intent_source="rules",
            candidate_tools=[hit["tool"]] if hit.get("tool") else [],
            fallback_from=fallback_from,
        )

    fb = cfg.get("deterministic_fallback_mode") or "skill_then_tool"
    if fb == "deterministic_first":
        fb = "skill_then_tool"
    return _dispatch(
        fb,
        message=message,
        tools=tools,
        today=today,
        cfg=cfg,
        recent_tool_names=recent_tool_names,
        llm_select=llm_select,
        rules_select=rules_select,
        chat_enabled=chat_enabled,
        recorder=recorder,
        trace=trace,
        fallback_from="deterministic_first",
        depth=depth + 1,
        rule_tool_map=rule_tool_map,
    )


def search_capabilities(query: str, tools: dict, *, top_k: int = 8) -> list[dict]:
    """元能力：按关键词检索可见 Tool，只返回 name/summary/skill（不含参数 schema）。"""
    top_k = max(1, int(top_k or 8))
    candidates = _tools_as_candidates(tools)
    skill_bound = [n for n, (_, sk) in tools.items() if sk is not None]
    ranked = select_top_tools(query or "", candidates=candidates, skill_tool_names=skill_bound, top_k=top_k)
    if not ranked:
        ranked = list(tools.keys())[:top_k]
    out: list[dict] = []
    for name in ranked:
        if name not in tools:
            continue
        spec, skill = tools[name]
        out.append({
            "name": name,
            "summary": getattr(spec, "summary", "") or getattr(spec, "description", "") or name,
            "skill": skill.name if skill is not None else None,
        })
    return out


def get_tool_schema(tool_name: str, tools: dict) -> dict | None:
    """元能力：返回单个业务 Tool 的参数说明（剥离身份注入字段）。"""
    if not tool_name or tool_name not in tools:
        return None
    spec, skill = tools[tool_name]
    blocked = set(getattr(spec, "inject_identity_fields", ()) or ())
    blocked.update((getattr(spec, "identity_params", None) or {}).keys())
    for binding in getattr(spec, "identity_bindings", ()) or ():
        if isinstance(binding, dict) and binding.get("param"):
            blocked.add(str(binding["param"]))
    params = {}
    for key, rule in (getattr(spec, "model_params", None) or {}).items():
        if key in blocked:
            continue
        if isinstance(rule, dict):
            params[key] = {k: v for k, v in rule.items() if k != "x-inject"}
        else:
            params[key] = rule
    return {
        "name": tool_name,
        "summary": getattr(spec, "summary", "") or "",
        "description": getattr(spec, "description", "") or "",
        "skill": skill.name if skill is not None else None,
        "model_params": params,
    }


def _meta_search(
    message, tools, today, cfg, recent_tool_names, llm_select, rules_select,
    chat_enabled, recorder, trace, fallback_from, rule_tool_map,
) -> RoutingDecision:
    """元工具渐进披露：search_capabilities / get_tool_schema，受 meta_max_rounds 限制后再填参。"""
    max_rounds = max(1, int(cfg.get("meta_max_rounds") or 3))
    top_k = int(cfg.get("retrieve_topk") or 8)
    state: dict[str, Any] = {"hits": None, "schemas": {}, "recent": list(recent_tool_names or [])}
    last_meta_error: str | None = None

    for round_i in range(1, max_rounds + 1):
        t0 = time.perf_counter()
        parsed = None
        if llm_select is not None:
            try:
                parsed = llm_select(message, {}, {
                    "meta": True,
                    "meta_state": {
                        "hits": state["hits"],
                        "schemas": dict(state["schemas"]),
                        "round": round_i,
                        "max_rounds": max_rounds,
                    },
                    "chat_enabled": chat_enabled,
                    "all_tools": tools,
                })
            except Exception:  # noqa: BLE001
                parsed = None

        if parsed and parsed.get("intent") == "meta":
            call = parsed.get("meta_call") or {}
            name = call.get("name")
            args = call.get("args") or {}
            if name == "search_capabilities":
                query = str(args.get("query") or message or "")
                hits = search_capabilities(query, tools, top_k=top_k)
                state["hits"] = hits
                _stage(recorder, trace, "meta_search",
                       duration_ms=int((time.perf_counter() - t0) * 1000),
                       candidates=[h["name"] for h in hits],
                       metadata={"round": round_i, "meta_call": "search_capabilities",
                                 "max_rounds": max_rounds, "via": "llm"})
                continue
            if name == "get_tool_schema":
                tool_name = str(args.get("tool_name") or "")
                schema = get_tool_schema(tool_name, tools)
                if schema:
                    state["schemas"][tool_name] = schema
                    if state["hits"] is None:
                        state["hits"] = search_capabilities(message, tools, top_k=top_k)
                    _stage(recorder, trace, "meta_search",
                           duration_ms=int((time.perf_counter() - t0) * 1000),
                           candidates=[tool_name],
                           metadata={"round": round_i, "meta_call": "get_tool_schema",
                                     "max_rounds": max_rounds, "via": "llm"})
                else:
                    last_meta_error = f"unknown_tool:{tool_name}"
                    _stage(recorder, trace, "meta_search",
                           duration_ms=int((time.perf_counter() - t0) * 1000),
                           candidates=[],
                           metadata={"round": round_i, "meta_call": "get_tool_schema",
                                     "error": last_meta_error, "max_rounds": max_rounds})
                continue
            last_meta_error = f"unknown_meta:{name}"
            continue

        if parsed and parsed.get("intent") in (TOOL, ASK, CHAT, "memory_write", "memory_forget"):
            # 仅当目标 Tool 已加载 schema（或无参）时接受业务决定
            chosen = parsed.get("tool")
            if parsed.get("intent") == TOOL and chosen and chosen not in state["schemas"]:
                schema = get_tool_schema(chosen, tools)
                if schema and round_i < max_rounds:
                    state["schemas"][chosen] = schema
                    _stage(recorder, trace, "meta_search",
                           duration_ms=int((time.perf_counter() - t0) * 1000),
                           candidates=[chosen],
                           metadata={"round": round_i, "meta_call": "get_tool_schema",
                                     "max_rounds": max_rounds, "via": "auto_before_tool"})
                    continue
            if parsed.get("intent") == TOOL and chosen and chosen not in tools:
                continue
            if state["schemas"] or parsed.get("intent") != TOOL:
                _stage(recorder, trace, "fill_args", duration_ms=0,
                       candidates=list(state["schemas"]) or ([chosen] if chosen else []),
                       metadata={"schema_count": len(state["schemas"]), "via": "llm_meta"})
                return _decision_from_parsed(
                    "meta_search", parsed, list(state["schemas"]) or list(tools.keys()),
                    fallback_from=fallback_from, tools=tools,
                )

        # 服务端默认推进：尚无 hits → search；有 hits 无 schema → 批量拉 schema；否则填参
        if state["hits"] is None:
            hits = search_capabilities(message, tools, top_k=top_k)
            if recent_tool_names:
                for name in recent_tool_names:
                    if name in tools and name not in {h["name"] for h in hits}:
                        hits.insert(0, {
                            "name": name,
                            "summary": getattr(tools[name][0], "summary", "") or name,
                            "skill": tools[name][1].name if tools[name][1] else None,
                        })
                hits = hits[: max(top_k, len(recent_tool_names))]
            state["hits"] = hits
            _stage(recorder, trace, "meta_search",
                   duration_ms=int((time.perf_counter() - t0) * 1000),
                   candidates=[h["name"] for h in hits],
                   metadata={"round": round_i, "meta_call": "search_capabilities",
                             "max_rounds": max_rounds, "via": "server"})
            continue

        if not state["schemas"]:
            remaining = max_rounds - round_i + 1
            to_load = [h["name"] for h in state["hits"] if h["name"] in tools][:remaining]
            loaded = []
            for name in to_load:
                schema = get_tool_schema(name, tools)
                if schema:
                    state["schemas"][name] = schema
                    loaded.append(name)
            _stage(recorder, trace, "meta_search",
                   duration_ms=int((time.perf_counter() - t0) * 1000),
                   candidates=loaded,
                   metadata={"round": round_i, "meta_call": "get_tool_schema",
                             "max_rounds": max_rounds, "via": "server", "batch": len(loaded)})
            if not state["schemas"]:
                break
            # 本轮已用于拉 schema；若还有轮次留给 LLM 填参则 continue，否则立刻填参
            if round_i < max_rounds and llm_select is not None:
                continue
            break

        break

    if not state["schemas"]:
        if cfg.get("routing_clarify_on_low_confidence", True):
            q = "我还不能确定该用哪个能力。请补充业务类型（例如「行程报销」），或换种说法。"
            if last_meta_error:
                q = "查询能力时次数已用完。请直接说明要查什么业务，或稍后再试。"
            return RoutingDecision(
                mode="meta_search", action=CLARIFY, clarify_question=q,
                fallback_from=fallback_from, intent_source="rules",
                candidate_tools=[h["name"] for h in (state["hits"] or [])],
            )
        return _help_decision("meta_search", fallback_from, "meta_no_schema")

    narrowed = {n: tools[n] for n in state["schemas"] if n in tools}
    _stage(recorder, trace, "fill_args", duration_ms=0,
           candidates=list(narrowed.keys()),
           metadata={"schema_count": len(narrowed), "via": "meta_search"})
    # 填参轮：给 llm_select 业务 schema（非 meta 模式）
    fill_select = llm_select
    if llm_select is not None:
        def fill_select(message, narrowed_tools, opts):  # noqa: ANN001
            # 若模型仍只懂 meta，避免死循环：去掉 meta 标记
            clean = {k: v for k, v in (opts or {}).items() if k not in ("meta", "meta_state")}
            return llm_select(message, narrowed_tools, clean)

    parsed = _run_llm_or_rules(
        message, narrowed, tools, today, fill_select, rules_select, chat_enabled,
        full_tools=tools, rule_tool_map=rule_tool_map,
    )
    return _decision_from_parsed(
        "meta_search", parsed, list(narrowed.keys()), fallback_from=fallback_from, tools=tools,
    )


def _router_then_fill(
    message, tools, today, cfg, llm_select, rules_select, chat_enabled,
    recorder, trace, fallback_from, rule_tool_map,
) -> RoutingDecision:
    """小路由：优先 LLM stage=router（可走 router_model_id）定 1 个 tool；否则规则/关键词；再 stage=fill 填参。"""
    t0 = time.perf_counter()
    skill_name, skill_tools, scores = _select_skill(
        message, tools, cfg.get("routing_skill_method") or "rules_then_llm", rule_tool_map,
    )
    picked_name = None
    router_source = "rules"
    pool_names = [n for n in (skill_tools or list(tools.keys())) if n in tools]
    pool = {n: tools[n] for n in pool_names}

    if llm_select is not None and pool:
        try:
            routed = llm_select(message, pool, {
                "chat_enabled": False,
                "all_tools": tools,
                "stage": "router",
            })
        except Exception:  # noqa: BLE001
            routed = None
        if routed and routed.get("intent") == TOOL and routed.get("tool") in tools:
            picked_name = routed["tool"]
            router_source = routed.get("intent_source") or "llm"
            if not skill_name:
                skill_name = _skill_of(picked_name, tools)
        elif routed and routed.get("intent") in (CLARIFY, ASK, HELP, CHAT):
            _stage(recorder, trace, "router_llm", duration_ms=int((time.perf_counter() - t0) * 1000),
                   candidates=[], metadata={"skill": skill_name, "scores": scores[:8], "router_source": "llm"})
            if routed.get("intent") == CLARIFY or (
                routed.get("intent") in (HELP, CHAT) and cfg.get("routing_clarify_on_low_confidence", True)
            ):
                return RoutingDecision(
                    mode="router_then_fill", action=CLARIFY,
                    clarify_question=(routed.get("chat_reply") or routed.get("clarify_question")
                                      or "我还不太确定你要查什么，请补充业务类型或关键条件。"),
                    fallback_from=fallback_from, intent_source=routed.get("intent_source") or "llm",
                    candidate_skills=[s for s, _ in scores],
                )

    if not picked_name and pool:
        ranked = select_top_tools(
            message,
            candidates=_tools_as_candidates(pool),
            skill_tool_names=pool_names,
            top_k=1,
        )
        picked_name = ranked[0] if ranked else pool_names[0]
        router_source = "keyword"
    if not picked_name:
        rules = _invoke_rules(rules_select, message, today, tools, rule_tool_map)
        if rules.get("intent") == TOOL and rules.get("tool") in tools:
            picked_name = rules["tool"]
            router_source = "rules"

    _stage(recorder, trace, "router_llm", duration_ms=int((time.perf_counter() - t0) * 1000),
           candidates=[picked_name] if picked_name else [],
           metadata={"skill": skill_name, "scores": scores[:8], "router_source": router_source})
    if not picked_name:
        if cfg.get("routing_clarify_on_low_confidence", True):
            return RoutingDecision(
                mode="router_then_fill", action=CLARIFY,
                clarify_question="我还不太确定你要查什么，请补充业务类型或关键条件。",
                fallback_from=fallback_from, intent_source="rules",
                candidate_skills=[s for s, _ in scores],
            )
        return _help_decision("router_then_fill", fallback_from)

    narrowed = {picked_name: tools[picked_name]}
    _stage(recorder, trace, "fill_args", duration_ms=0, candidates=[picked_name], metadata={"schema_count": 1})
    # 规则已带参则直接用，避免多余模型调用
    rules = _invoke_rules(rules_select, message, today, tools, rule_tool_map)
    if rules.get("intent") == TOOL and rules.get("tool") == picked_name and rules.get("params"):
        return RoutingDecision(
            mode="router_then_fill", action=TOOL, chosen_tool=picked_name,
            chosen_skill=skill_name, args=rules.get("params") or {},
            candidate_tools=[picked_name], intent_source="rules", fallback_from=fallback_from,
        )
    parsed = _run_llm_or_rules(
        message, narrowed, tools, today, llm_select, rules_select, chat_enabled,
        full_tools=tools, stage="fill", rule_tool_map=rule_tool_map,
    )
    dec = _decision_from_parsed(
        "router_then_fill", parsed, [picked_name], fallback_from=fallback_from, tools=tools,
    )
    dec.chosen_skill = skill_name
    return dec


def _try_deterministic(
    message: str, today: date, tools: dict, rule_tool_map: dict[str, str],
) -> dict | None:
    """规则 + plan_list_then_detail 真正调用。命中则返回 understand 形态 dict。"""
    parsed = intent_rules.parse(message, today)
    intent = parsed.get("intent")
    params = parsed.get("params") or {}
    list_tool = rule_tool_map.get(LIST)
    detail_tool = rule_tool_map.get(DETAIL)

    # 「最近一笔详情」类：服务端串联 list→detail
    if (
        _DETAIL_CHAIN.search(message or "")
        and list_tool
        and detail_tool
        and list_tool in tools
        and detail_tool in tools
    ):
        plan = plan_list_then_detail(list_tool, detail_tool, "id")
        list_args = {k: v for k, v in params.items() if k != "id"}
        if "limit" not in list_args:
            list_args = {**list_args}  # limit 由 understand 层补默认
        steps = [
            {"tool": list_tool, "args": list_args},
            {"tool": detail_tool, "args": {"id": {"$ref": "step1.list[0].id"}}},
        ]
        # 校验 plan 已被调用（返回非空）
        assert plan and plan[0]["tool"] == list_tool
        return {"intent": TOOL, "tool": list_tool, "params": list_args, "steps": steps}

    name = rule_tool_map.get(intent) if intent else None
    if name is None or name not in tools:
        return None
    return {"intent": TOOL, "tool": name, "params": params}


def _select_skill(
    message: str, tools: dict, method: str, rule_tool_map: dict[str, str],
) -> tuple[str | None, list[str], list[tuple[str, int]]]:
    """按 Skill 聚合候选；返回 (chosen_skill, tool_names, scores)。"""
    buckets: dict[str, list[str]] = {}
    for name, (_, skill) in tools.items():
        key = skill.name if skill is not None else "_ungrouped"
        buckets.setdefault(key, []).append(name)
    if len(buckets) <= 1:
        only = next(iter(buckets), None)
        tools_in = buckets.get(only or "", list(tools.keys()))
        return (None if only == "_ungrouped" else only), tools_in, [(only or "_ungrouped", 1)]

    tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", (message or "").lower()))
    mapped_tools = set(rule_tool_map.values())
    scores: list[tuple[str, int]] = []
    for skill_name, names in buckets.items():
        score = 0
        sample = tools[names[0]][1] if names and tools[names[0]][1] else None
        blob = " ".join([
            skill_name,
            getattr(sample, "display_name", "") or "",
            getattr(sample, "description", "") or "",
            " ".join(names),
        ]).lower()
        for tok in tokens:
            if tok in blob:
                score += 10
        # 规则强命中：Skill 工具落在当前 rule_tool_map
        if skill_name != "_ungrouped" and any(n in mapped_tools for n in names):
            if intent_rules.parse(message, date.today()).get("intent") in (LIST, DETAIL):
                score += 100
        scores.append((skill_name, score))
    scores.sort(key=lambda x: (-x[1], x[0]))

    if method == "llm":
        # 本期无独立路由模型：退回最高分；0 分则全量
        best, best_score = scores[0]
        if best_score <= 0:
            return None, list(tools.keys()), scores
        return (None if best == "_ungrouped" else best), buckets[best], scores

    # rules / rules_then_llm：取最高分；全 0 时 rules_then_llm 退全量给上层 llm 填参
    best, best_score = scores[0]
    if best_score <= 0:
        if method == "rules":
            return None, [], scores
        return None, list(tools.keys()), scores
    return (None if best == "_ungrouped" else best), buckets[best], scores


def _topk_tools(message: str, tools: dict, top_k: int) -> dict:
    if len(tools) <= top_k:
        return tools
    candidates = _tools_as_candidates(tools)
    skill_names = [n for n, (_, sk) in tools.items() if sk is not None]
    picked = select_top_tools(message, candidates=candidates, skill_tool_names=skill_names, top_k=top_k)
    return {n: tools[n] for n in picked if n in tools} or tools


def _tools_as_candidates(tools: dict) -> list[dict]:
    out = []
    for name, (spec, _skill) in tools.items():
        out.append({
            "name": name,
            "summary": getattr(spec, "summary", "") or "",
            "description": getattr(spec, "description", "") or name,
        })
    return out


def _invoke_rules(
    rules_select: RulesSelectFn | None,
    message: str,
    today: date,
    tools: dict,
    rule_tool_map: dict[str, str],
) -> dict:
    if rules_select is not None:
        return rules_select(message, today, tools)
    return _default_rules(message, today, tools, rule_tool_map=rule_tool_map)


def _run_llm_or_rules(
    message, narrowed, all_tools, today, llm_select, rules_select, chat_enabled, *, full_tools,
    stage: str = "fill",
    rule_tool_map: dict[str, str] | None = None,
) -> dict:
    if llm_select is not None and (narrowed or chat_enabled):
        try:
            parsed = llm_select(message, narrowed, {
                "chat_enabled": chat_enabled,
                "all_tools": full_tools,
                "stage": stage,
            })
            if parsed is not None:
                return parsed
        except Exception:  # noqa: BLE001 — 模型失败回退规则
            pass
    return _invoke_rules(
        rules_select, message, today, all_tools, _resolve_rule_tool_map(rule_tool_map),
    )


def _default_rules(
    message: str,
    today: date,
    tools: dict,
    *,
    rule_tool_map: dict[str, str] | None = None,
) -> dict:
    mapping = _resolve_rule_tool_map(rule_tool_map)
    parsed = intent_rules.parse(message, today)
    name = mapping.get(parsed.get("intent"))
    if name is None or name not in tools:
        return {"intent": HELP, "tool": None, "params": {}}
    return {"intent": TOOL, "tool": name, "params": parsed.get("params") or {}, "intent_source": "rules"}


def _decision_from_parsed(
    mode: str, parsed: dict, candidates: list[str], *, fallback_from: str | None, tools: dict,
) -> RoutingDecision:
    intent = parsed.get("intent") or HELP
    source = parsed.get("intent_source") or "rules"
    if intent == TOOL:
        return RoutingDecision(
            mode=mode, action=TOOL, chosen_tool=parsed.get("tool"),
            args=parsed.get("params") or {}, steps=parsed.get("steps"),
            candidate_tools=candidates, intent_source=source, fallback_from=fallback_from,
            chosen_skill=_skill_of(parsed.get("tool"), tools),
        )
    if intent == ASK:
        return RoutingDecision(
            mode=mode, action=ASK, chosen_tool=parsed.get("tool"),
            missing=list(parsed.get("missing") or []),
            candidate_tools=candidates, intent_source=source, fallback_from=fallback_from,
        )
    if intent == CHAT:
        return RoutingDecision(
            mode=mode, action=CHAT, chat_reply=parsed.get("chat_reply"),
            candidate_tools=candidates, intent_source=source, fallback_from=fallback_from,
            extra={k: parsed[k] for k in ("memory_kind", "memory_text", "memory_id", "match_text")
                   if k in parsed},
        )
    # memory_* 等透传
    if intent in ("memory_write", "memory_forget"):
        return RoutingDecision(
            mode=mode, action=CHAT, intent_source=source, fallback_from=fallback_from,
            extra={**{k: v for k, v in parsed.items() if k not in ("intent", "tool", "params")},
                   "intent": intent},
        )
    return RoutingDecision(
        mode=mode, action=HELP, candidate_tools=candidates,
        intent_source=source, fallback_from=fallback_from,
    )


def _skill_of(tool_name: str | None, tools: dict) -> str | None:
    if not tool_name or tool_name not in tools:
        return None
    skill = tools[tool_name][1]
    return skill.name if skill is not None else None


def _help_decision(mode: str, fallback_from: str | None, reason: str | None = None) -> RoutingDecision:
    return RoutingDecision(
        mode=mode, action=HELP, fallback_from=fallback_from, intent_source="rules",
        extra={"routing_reason": reason} if reason else {},
    )


def _emit(recorder, trace: bool, event_type: str, **kwargs) -> None:
    if not trace or recorder is None or not hasattr(recorder, "event"):
        return
    recorder.event(event_type, node_name="understand", **kwargs)


def _stage(recorder, trace: bool, stage: str, *, duration_ms: int, candidates: list[str],
           metadata: dict | None = None) -> None:
    meta = {"stage": stage, "candidates": candidates[:32], **(metadata or {})}
    _emit(recorder, trace, "routing_stage", duration_ms=duration_ms, metadata=meta)
