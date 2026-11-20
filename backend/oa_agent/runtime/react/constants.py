"""ReAct 结束态与任务态枚举（字符串常量，便于 Checkpoint JSON）。"""

from __future__ import annotations

from typing import Literal

FinishReason = Literal[
    "answer",
    "ask",
    "max_rounds",
    "max_tool_calls",
    "max_tokens",
    "timeout",
    "cancelled",
    "fatal_error",
]

FINISH_ANSWER: FinishReason = "answer"
FINISH_ASK: FinishReason = "ask"
FINISH_MAX_ROUNDS: FinishReason = "max_rounds"
FINISH_MAX_TOOL_CALLS: FinishReason = "max_tool_calls"
FINISH_MAX_TOKENS: FinishReason = "max_tokens"
FINISH_TIMEOUT: FinishReason = "timeout"
FINISH_CANCELLED: FinishReason = "cancelled"
FINISH_FATAL: FinishReason = "fatal_error"

TaskStatus = Literal[
    "created",
    "planning",
    "running",
    "waiting_confirmation",
    "waiting_external",
    "completed",
    "partially_completed",
    "failed",
    "cancelled",
]

TASK_CREATED: TaskStatus = "created"
TASK_PLANNING: TaskStatus = "planning"
TASK_RUNNING: TaskStatus = "running"
TASK_WAITING_CONFIRM: TaskStatus = "waiting_confirmation"
TASK_WAITING_EXTERNAL: TaskStatus = "waiting_external"
TASK_COMPLETED: TaskStatus = "completed"
TASK_PARTIAL: TaskStatus = "partially_completed"
TASK_FAILED: TaskStatus = "failed"
TASK_CANCELLED: TaskStatus = "cancelled"

STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_SUCCESS = "success"
STEP_ERROR = "error"
STEP_SKIPPED = "skipped"
STEP_CANCELLED = "cancelled"

# 认知类工具：结果必须回灌模型，禁止当员工最终回复
COGNITIVE_BUILTIN_IDS = frozenset({"sys.skill", "sys.skill_read", "sys.skill_exec"})
COGNITIVE_TOOL_NAMES = frozenset({"builtin.skill", "builtin.skill_read", "builtin.skill_exec"})
