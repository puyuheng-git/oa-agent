"""P3/P4：meta Tick、Handoff 再鉴权、取消 Ledger、租约/fencing、压缩、重复调用。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from oa_agent.executor.tool_routing import META_CONTINUE, route as route_tools
from oa_agent.runtime.graphs.oa_assistant import _after_handoff, _route
from oa_agent.runtime.react.ledger import (
    ExecutionLedger,
    FenceRejected,
    LedgerStore,
    request_fingerprint,
)
from oa_agent.runtime.react.observation import (
    build_observation,
    compress_observations_for_prompt,
)


def test_meta_single_tick_returns_continue():
    """meta_search + single_tick：首拍未收敛 → meta_continue + meta_state。"""
    tools = {
        "office.list": (MagicMock(name="office.list", summary="list trips", model_params={}), None),
    }
    # 无 llm：服务端默认先 search → continue
    out = route_tools(
        "查行程",
        tools=tools,
        today=__import__("datetime").date(2026, 1, 1),
        config={"tool_routing_mode": "meta_search", "meta_max_rounds": 3, "retrieve_topk": 4},
        llm_select=None,
        rules_select=None,
        chat_enabled=False,
        meta_single_tick=True,
        meta_state=None,
    )
    assert out.get("intent") == META_CONTINUE
    assert out.get("meta_continue") is True
    assert isinstance(out.get("meta_state"), dict)
    assert out["meta_state"].get("hits") is not None


def test_route_meta_continue_loops_understand():
    assert _route({"meta_continue": True, "intent": "meta_continue"}) == "understand"
    assert _route({"intent": "chat", "chat_reply": "hi", "finish_reason": "answer"}) == "respond"


def test_after_handoff_routing():
    assert _after_handoff({"decision": {"action": "abort"}, "finish_reason": "cancelled"}) == "respond"
    assert _after_handoff({"decision": {"action": "retry", "skip_execute": True}, "replan": True}) == "understand"
    assert _after_handoff({"decision": {"action": "retry", "reauth_ok": True}}) == "call_tool"


def test_lease_and_fencing(tmp_path: Path):
    store = LedgerStore(tmp_path, "t1")
    ledger = ExecutionLedger(store)
    rec = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.write", args={"x": 1},
        effect_type="write", idempotent=False,
    )
    eid = rec["execution_id"]
    leased = ledger.acquire_lease(eid, owner="worker-a", ttl_seconds=60)
    token = int(leased["fencing_token"])
    assert token >= 1
    ledger.mark_running(eid, fencing_token=token)
    ledger.mark_succeeded(eid, result_id="res_1", fencing_token=token)

    # 同 owner 续租递增 fencing；旧 token 提交被拒
    rec2 = ledger.reserve(
        task_id="task2", run_id="run2", tool="office.write", args={"y": 2},
        effect_type="write", idempotent=False,
    )
    eid2 = rec2["execution_id"]
    leased2 = ledger.acquire_lease(eid2, owner="worker-a", ttl_seconds=60)
    token2 = int(leased2["fencing_token"])
    leased3 = ledger.acquire_lease(eid2, owner="worker-a", ttl_seconds=60)
    token3 = int(leased3["fencing_token"])
    assert token3 > token2
    with pytest.raises(FenceRejected):
        ledger.mark_succeeded(eid2, result_id="res_x", fencing_token=token2)
    ledger.mark_succeeded(eid2, result_id="res_ok", fencing_token=token3)
    assert ledger.store.load(eid2)["status"] == "succeeded"


def test_lease_blocks_other_owner(tmp_path: Path):
    store = LedgerStore(tmp_path, "t1")
    ledger = ExecutionLedger(store)
    rec = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.write", args={"a": 1},
        effect_type="write", idempotent=False,
    )
    eid = rec["execution_id"]
    ledger.acquire_lease(eid, owner="worker-a", ttl_seconds=120)
    with pytest.raises(FenceRejected):
        ledger.acquire_lease(eid, owner="worker-b", ttl_seconds=120)


def test_mark_cancelled(tmp_path: Path):
    store = LedgerStore(tmp_path, "t1")
    ledger = ExecutionLedger(store)
    rec = ledger.reserve(
        task_id="task1", run_id="run1", tool="office.list", args={},
        effect_type="read", idempotent=True,
    )
    ledger.mark_running(rec["execution_id"])
    ledger.mark_cancelled(rec["execution_id"], reason="user_cancel")
    loaded = ledger.store.load(rec["execution_id"])
    assert loaded["status"] == "cancelled"
    assert ledger.should_skip_execute(loaded) is True


def test_observation_compression_keeps_recent_full():
    obs_list = [
        build_observation(
            task_id="t", run_id="r", execution_id=f"e{i}", tool=f"tool_{i}",
            round_no=i, step_index=0, status="success",
            summary=("FULL_DETAIL_" + str(i) + "_") * 20,
        )
        for i in range(8)
    ]
    text = compress_observations_for_prompt(obs_list, max_chars=8000, keep_full=3)
    assert "Earlier (compressed)" in text
    assert "Recent (full)" in text
    # 最近一条全文应出现；最旧的应被压成一行
    assert "FULL_DETAIL_7_" in text
    assert "tool_0" in text


def test_duplicate_fingerprint_stable_across_key_order():
    a = request_fingerprint("builtin.skill", {"name": "pdf", "x": 1})
    b = request_fingerprint("builtin.skill", {"x": 1, "name": "pdf"})
    assert a == b
