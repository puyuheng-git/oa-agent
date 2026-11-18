"""新员工消息须清零 ReAct 累计，否则「导出到表格」会被上一轮 max-rounds 直接挡掉。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from oa_agent.runtime.engine import _fresh_turn_input
from oa_agent.runtime.graphs import oa_assistant
from oa_agent.runtime.react.constants import FINISH_MAX_ROUNDS


def test_fresh_turn_input_zeros_react_counters():
    out = _fresh_turn_input("run_1", "导出到表格发给我", ["att_1"])
    assert out["run_id"] == "run_1"
    assert out["message"] == "导出到表格发给我"
    assert out["attachment_ids"] == ["att_1"]
    assert out["react_round"] == 0
    assert out["tool_call_count"] == 0
    assert out["recent_observation_ids"] == []
    assert out["replan"] is False
    assert out["finish_reason"] is None
    assert out["task_started_at"] is None


def test_understand_ignores_stale_max_rounds_without_replan(monkeypatch):
    """Checkpoint 残留高 react_round + observation，但新消息 replan=False 时不得直接 max-rounds 文案。"""
    calls = {"n": 0}

    def fake_understand(state, ctx, tools):
        calls["n"] += 1
        return {"intent": "chat", "tool": None, "params": {}, "chat_reply": "ok", "missing": []}

    monkeypatch.setattr(oa_assistant, "_understand", fake_understand)
    monkeypatch.setattr(oa_assistant, "_prefer_export", lambda parsed, *a, **k: parsed)
    monkeypatch.setattr(oa_assistant, "_prefer_explicit_memory", lambda parsed, message: parsed)

    ctx = oa_assistant.RunContext(
        recorder=SimpleNamespace(event=lambda *a, **k: None),
        identity=SimpleNamespace(oa="alice"),
        executor=SimpleNamespace(registry=SimpleNamespace(names=lambda: [], get=lambda n: None)),
        today=date(2026, 11, 5),
        skills=[],
        config={"chat_mode": "llm", "intent_mode": "auto", "react_max_rounds": 1},
    )
    state = {
        "run_id": "run_x",
        "message": "导出到表格发给我",
        "react_round": 99,
        "recent_observation_ids": ["obs_old"],
        "replan": False,
        "finish_reason": FINISH_MAX_ROUNDS,
        "history": [],
        "memory": "",
        "attachment_ids": [],
    }
    out = oa_assistant.understand(state, ctx)
    assert calls["n"] == 1
    assert out.get("finish_reason") != FINISH_MAX_ROUNDS
    assert "限定轮次" not in (out.get("chat_reply") or "")


def test_understand_enforces_budget_on_replan(monkeypatch):
    """同轮 replan 且轮次已耗尽时，仍应提前结束。"""
    monkeypatch.setattr(
        oa_assistant, "_understand",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call model")),
    )
    ctx = oa_assistant.RunContext(
        recorder=SimpleNamespace(event=lambda *a, **k: None),
        identity=SimpleNamespace(oa="alice"),
        executor=SimpleNamespace(registry=SimpleNamespace(names=lambda: [], get=lambda n: None)),
        today=date(2026, 11, 5),
        skills=[],
        config={"chat_mode": "llm", "intent_mode": "auto", "react_max_rounds": 1},
    )
    state = {
        "run_id": "run_y",
        "message": "继续",
        "react_round": 2,
        "recent_observation_ids": ["obs_1"],
        "replan": True,
        "task_started_at": 1.0,
        "history": [],
        "memory": "",
        "attachment_ids": [],
    }
    out = oa_assistant.understand(state, ctx)
    assert out["finish_reason"] == FINISH_MAX_ROUNDS
    assert "限定轮次" in out["chat_reply"]
