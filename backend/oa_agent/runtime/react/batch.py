"""批内串行 Step 调度：依赖失败 skipped，独立 step 继续。"""

from __future__ import annotations

from typing import Any, Callable

from oa_agent.runtime.react.constants import (
    STEP_ERROR,
    STEP_PENDING,
    STEP_SKIPPED,
    STEP_SUCCESS,
)


def prepare_batch_statuses(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for step in steps:
        item = dict(step)
        item.setdefault("status", STEP_PENDING)
        out.append(item)
    return out


def mark_skipped_dependents(steps: list[dict[str, Any]], failed_step_id: str) -> None:
    """上游失败后，传递性跳过依赖它的后续 step。"""
    failed = {failed_step_id}
    changed = True
    while changed:
        changed = False
        for step in steps:
            if step.get("status") not in (STEP_PENDING,):
                continue
            deps = step.get("depends_on") or []
            if any(d in failed for d in deps):
                step["status"] = STEP_SKIPPED
                step["skip_reason"] = f"depends_on failed:{failed_step_id}"
                failed.add(step["step_id"])
                changed = True


def next_runnable_index(steps: list[dict[str, Any]], from_index: int = 0) -> int | None:
    """返回下一个可执行 pending step 下标（依赖均已 success）。"""
    status_by_id = {s["step_id"]: s.get("status") for s in steps}
    for i in range(from_index, len(steps)):
        step = steps[i]
        if step.get("status") != STEP_PENDING:
            continue
        deps = step.get("depends_on") or []
        if all(status_by_id.get(d) == STEP_SUCCESS for d in deps):
            return i
        if any(status_by_id.get(d) in (STEP_ERROR, STEP_SKIPPED) for d in deps):
            step["status"] = STEP_SKIPPED
            step["skip_reason"] = "dependency not successful"
            status_by_id[step["step_id"]] = STEP_SKIPPED
            continue
    return None


def run_serial_batch(
    steps: list[dict[str, Any]],
    execute: Callable[[dict[str, Any], int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    串行执行批次。execute(step, index) → {"status": success|error, ...}
    返回更新后的 steps。
    """
    prepared = prepare_batch_statuses(steps)
    while True:
        idx = next_runnable_index(prepared, 0)
        if idx is None:
            # 将仍 pending 但依赖未满足的标为 skipped
            for step in prepared:
                if step.get("status") == STEP_PENDING:
                    step["status"] = STEP_SKIPPED
                    step["skip_reason"] = step.get("skip_reason") or "no runnable path"
            break
        step = prepared[idx]
        outcome = execute(step, idx)
        status = outcome.get("status") or STEP_ERROR
        step["status"] = status
        if status == STEP_SUCCESS:
            step["result"] = outcome.get("result")
            step["execution_id"] = outcome.get("execution_id")
            step["observation_id"] = outcome.get("observation_id")
            step["result_id"] = outcome.get("result_id")
        else:
            step["error"] = outcome.get("error")
            step["execution_id"] = outcome.get("execution_id")
            step["observation_id"] = outcome.get("observation_id")
            mark_skipped_dependents(prepared, step["step_id"])
        if outcome.get("requires_replan") or step.get("requires_replan"):
            # 提前结束批次：后续 pending → skipped
            for later in prepared[idx + 1 :]:
                if later.get("status") == STEP_PENDING:
                    later["status"] = STEP_SKIPPED
                    later["skip_reason"] = "batch ended for replan"
            break
    return prepared
