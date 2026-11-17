"""任务预算预检（轮次/调用/重试 + 时间；Token 预留结算）。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from oa_agent.runtime.react.constants import (
    FINISH_MAX_ROUNDS,
    FINISH_MAX_TOOL_CALLS,
    FINISH_MAX_TOKENS,
    FINISH_TIMEOUT,
    FinishReason,
)


@dataclass(frozen=True)
class BudgetLimits:
    react_max_rounds: int = 8
    max_tool_calls: int = 20
    max_tool_retries: int = 2
    max_execution_time: int = 300  # seconds; 0 = disabled
    max_total_tokens: int = 200_000  # 0 = disabled

    @classmethod
    def from_config(cls, config: dict | None) -> BudgetLimits:
        cfg = config or {}
        return cls(
            react_max_rounds=max(1, int(cfg.get("react_max_rounds") or 8)),
            max_tool_calls=max(1, int(cfg.get("max_tool_calls") or 20)),
            max_tool_retries=max(0, int(cfg.get("max_tool_retries") or 2)),
            max_execution_time=max(0, int(cfg.get("max_execution_time") or 300)),
            max_total_tokens=max(0, int(cfg.get("max_total_tokens") or 200_000)),
        )


@dataclass(frozen=True)
class BudgetVerdict:
    ok: bool
    finish_reason: FinishReason | None = None
    message: str = ""


@dataclass
class TokenBudget:
    """预留/结算：调用前 reserve，调用后 settle。"""

    used: int = 0
    reserved: int = 0

    def remaining(self, limit: int) -> int:
        if limit <= 0:
            return 10**12
        return max(0, limit - self.used - self.reserved)

    def reserve(self, amount: int, *, limit: int) -> bool:
        need = max(0, int(amount))
        if need > self.remaining(limit):
            return False
        self.reserved += need
        return True

    def settle(self, actual: int) -> None:
        """结算一次调用：计入实际用量并释放本次预留。"""
        actual = max(0, int(actual))
        self.used += actual
        self.reserved = 0

    def release_reserve(self) -> None:
        self.reserved = 0


def check_budget_before_think(
    *,
    react_round: int,
    limits: BudgetLimits,
    started_at: float | None = None,
    token_budget: TokenBudget | None = None,
) -> BudgetVerdict:
    """进入下一轮 Think 前：轮次 / 时间 / Token。"""
    if react_round >= limits.react_max_rounds:
        return BudgetVerdict(
            False,
            FINISH_MAX_ROUNDS,
            f"已达 react_max_rounds={limits.react_max_rounds}",
        )
    if limits.max_execution_time > 0 and started_at is not None:
        if time.time() - started_at >= limits.max_execution_time:
            return BudgetVerdict(False, FINISH_TIMEOUT, "已达 max_execution_time")
    if token_budget is not None and limits.max_total_tokens > 0:
        if token_budget.remaining(limits.max_total_tokens) <= 0:
            return BudgetVerdict(False, FINISH_MAX_TOKENS, "已达 max_total_tokens")
    return BudgetVerdict(True)


def check_budget_before_act(
    *,
    tool_call_count: int,
    limits: BudgetLimits,
    started_at: float | None = None,
) -> BudgetVerdict:
    if tool_call_count >= limits.max_tool_calls:
        return BudgetVerdict(
            False,
            FINISH_MAX_TOOL_CALLS,
            f"已达 max_tool_calls={limits.max_tool_calls}",
        )
    if limits.max_execution_time > 0 and started_at is not None:
        if time.time() - started_at >= limits.max_execution_time:
            return BudgetVerdict(False, FINISH_TIMEOUT, "已达 max_execution_time")
    return BudgetVerdict(True)


def estimate_prompt_tokens(text: str) -> int:
    """保守估算：按字符/2（中英混合），下限 1。"""
    n = max(1, (len(text or "") + 1) // 2)
    return n
