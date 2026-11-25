"""P1 ReAct：Ledger 不盲重试、Observation、批依赖 skipped、路由回 understand。"""

from __future__ import annotations

from pathlib import Path

import pytest

from oa_agent.runtime.react.batch import mark_skipped_dependents, prepare_batch_statuses, run_serial_batch
from oa_agent.runtime.react.budget import BudgetLimits, check_budget_before_act, check_budget_before_think
from oa_agent.runtime.react.constants import FINISH_MAX_ROUNDS, FINISH_MAX_TOOL_CALLS, STEP_ERROR, STEP_SKIPPED, STEP_SUCCESS
from oa_agent.runtime.react.ledger import ExecutionLedger, LedgerStore, request_fingerprint
from oa_agent.runtime.react.observation import ObservationStore, build_observation, format_observations_for_prompt, summarize_tool_data
from oa_agent.runtime.react.validate import DecisionValidationError, validate_tool_decision


def test_ledger_write_reuse_prevents_blind_retry(tmp_path: Path):
    store = LedgerStore(tmp_path, "t1")
    ledger = ExecutionLedger(store)
    args = {"x": 1}
    first = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.create", args=args,
        effect_type="write", idempotent=False,
    )
    ledger.mark_running(first["execution_id"])
    ledger.mark_succeeded(first["execution_id"], result_id="res_1")

    second = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.create", args=args,
        effect_type="write", idempotent=False,
    )
    assert second["execution_id"] == first["execution_id"]
    assert ledger.should_skip_execute(second) is True


def test_ledger_uncertain_skips_retry(tmp_path: Path):
    store = LedgerStore(tmp_path, "t1")
    ledger = ExecutionLedger(store)
    rec = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.create", args={"a": 1},
        effect_type="write", idempotent=False,
    )
    ledger.mark_running(rec["execution_id"])
    ledger.mark_uncertain(rec["execution_id"], reason="timeout after dispatch")
    again = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.create", args={"a": 1},
        effect_type="write", idempotent=False,
    )
    assert again["status"] == "uncertain"
    assert ledger.should_skip_execute(again) is True


def test_batch_dependency_skip():
    steps = prepare_batch_statuses([
        {"step_id": "a", "tool": "t1", "args": {}, "depends_on": []},
        {"step_id": "b", "tool": "t2", "args": {}, "depends_on": ["a"]},
        {"step_id": "c", "tool": "t3", "args": {}, "depends_on": []},
    ])

    def execute(step, index):
        if step["step_id"] == "a":
            return {"status": STEP_ERROR, "error": {"code": "X"}}
        return {"status": STEP_SUCCESS, "result": {}}

    out = run_serial_batch(steps, execute)
    by_id = {s["step_id"]: s for s in out}
    assert by_id["a"]["status"] == STEP_ERROR
    assert by_id["b"]["status"] == STEP_SKIPPED
    assert by_id["c"]["status"] == STEP_SUCCESS


def test_validate_unknown_tool():
    with pytest.raises(DecisionValidationError):
        validate_tool_decision(tool="nope", args={}, steps=None, tools={})


def test_budget_limits():
    limits = BudgetLimits(react_max_rounds=2, max_tool_calls=3)
    assert check_budget_before_think(react_round=2, limits=limits).finish_reason == FINISH_MAX_ROUNDS
    assert check_budget_before_act(tool_call_count=3, limits=limits).finish_reason == FINISH_MAX_TOOL_CALLS


def test_observation_prompt_includes_redacted_rows():
    summary = summarize_tool_data(
        "office.list",
        {"list": [{"id": 1, "amount": 100, "id_card": "110101199001011234"}, {"id": 2, "amount": 200}], "total": 2},
        kind="list",
        columns=["id", "amount", "id_card"],
        max_rows=20,
    )
    assert '"amount": 100' in summary or '"amount":100' in summary.replace(" ", "")
    assert "110101199001011234" not in summary
    assert "[已脱敏]" in summary
    obs = build_observation(
        task_id="t", run_id="r", execution_id="e", tool="office.list",
        round_no=1, step_index=0, status="success", summary=summary,
    )
    text = format_observations_for_prompt([obs])
    assert "Tool observations" in text
    assert "office.list" in text


def test_summarize_tool_data_object_kind_maps_to_record():
    """legacy kind=object 应归一为 record，脱敏后返回合法 JSON，不抛错。"""
    summary = summarize_tool_data(
        "office.get",
        {
            "item": {
                "id": 9,
                "name": "Alice",
                "id_card": "110101199001011234",
            },
        },
        kind="object",
        columns=["id", "name", "id_card"],
    )
    assert '"kind": "record"' in summary or '"kind":"record"' in summary.replace(" ", "")
    assert '"id": 9' in summary or '"id":9' in summary.replace(" ", "")
    assert "110101199001011234" not in summary
    assert "[已脱敏]" in summary


def test_observation_store_roundtrip(tmp_path: Path):
    store = ObservationStore(tmp_path, "t1")
    obs = build_observation(
        task_id="t", run_id="r", execution_id="e", tool="builtin.skill",
        round_no=0, step_index=0, status="success", summary="# SKILL BODY",
    )
    store.save(obs)
    loaded = store.load(obs["observation_id"])
    assert loaded is not None
    assert "SKILL BODY" in loaded["summary"]


def test_after_tool_routes_to_understand():
    from oa_agent.runtime.graphs.oa_assistant import _after_tool

    assert _after_tool({"replan": True, "steps": [], "step_index": 0}) == "understand"
    assert _after_tool({"handoff": {"tool": "x"}}) == "human_handoff"
    assert _after_tool({
        "replan": False,
        "steps": [{"tool": "a"}, {"tool": "b"}],
        "step_index": 1,
    }) == "call_tool"
    # 业务工具成功写 finish_reason 后应直接 respond，不再空转 understand
    assert _after_tool({
        "replan": False,
        "finish_reason": "answer",
        "steps": [],
        "step_index": 0,
    }) == "respond"


def test_fingerprint_stable():
    a = request_fingerprint("t", {"b": 1, "a": 2})
    b = request_fingerprint("t", {"a": 2, "b": 1})
    assert a == b


def test_result_store_auth(tmp_path: Path):
    from oa_agent.runtime.react.budget import TokenBudget
    from oa_agent.runtime.react.observation import ResultStore

    store = ResultStore(tmp_path, "t1")
    rid = store.save(
        task_id="task", execution_id="e1", tenant_id="t1", owner_oa="u1",
        result_type="list", data={"list": [{"id": 1}], "total": 1},
    )
    assert store.load(rid, tenant_id="t1", owner_oa="u1") is not None
    assert store.load(rid, tenant_id="t1", owner_oa="other") is None
    assert store.load(rid, tenant_id="other", owner_oa="u1") is None

    tb = TokenBudget()
    assert tb.reserve(100, limit=150) is True
    assert tb.reserve(100, limit=150) is False
    tb.settle(40)
    assert tb.used == 40
    assert tb.reserve(100, limit=150) is True
