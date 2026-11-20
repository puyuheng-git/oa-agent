"""Decision / Plan 结构校验（进入执行器前）。"""

from __future__ import annotations

from typing import Any


class DecisionValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_DECISION"):
        super().__init__(message)
        self.message = message
        self.code = code


def validate_tool_decision(
    *,
    tool: str | None,
    args: dict[str, Any] | None,
    steps: list[dict] | None,
    tools: dict[str, Any],
) -> list[dict[str, Any]]:
    """返回规范化 steps；非法则抛 DecisionValidationError。"""
    planned = list(steps or [])
    if not planned:
        if not tool or not isinstance(tool, str):
            raise DecisionValidationError("缺少 tool")
        planned = [{"tool": tool, "args": dict(args or {})}]

    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(planned):
        if not isinstance(raw, dict):
            raise DecisionValidationError(f"step[{index}] 不是对象")
        name = raw.get("tool")
        if not isinstance(name, str) or not name.strip():
            raise DecisionValidationError(f"step[{index}] 缺少 tool")
        name = name.strip()
        if name not in tools:
            raise DecisionValidationError(f"工具不可用或不存在：{name}", code="TOOL_NOT_AVAILABLE")
        step_args = raw.get("args") if isinstance(raw.get("args"), dict) else {}
        step_id = str(raw.get("step_id") or f"step_{index + 1}")
        if step_id in seen_ids:
            raise DecisionValidationError(f"重复 step_id：{step_id}")
        seen_ids.add(step_id)
        depends_on = raw.get("depends_on") if isinstance(raw.get("depends_on"), list) else []
        for dep in depends_on:
            if str(dep) not in seen_ids and str(dep) not in {s.get("step_id") for s in normalized}:
                # 允许依赖尚未出现在 normalized 但会出现在同批更早下标——下方二次校验
                pass
        normalized.append({
            "step_id": step_id,
            "tool": name,
            "args": dict(step_args),
            "depends_on": [str(d) for d in depends_on],
            "requires_replan": bool(raw.get("requires_replan")),
            "status": "pending",
        })

    id_set = {s["step_id"] for s in normalized}
    for step in normalized:
        for dep in step["depends_on"]:
            if dep not in id_set:
                raise DecisionValidationError(f"depends_on 引用不存在：{dep}")
            if dep == step["step_id"]:
                raise DecisionValidationError("depends_on 不能指向自身")
    if _has_cycle(normalized):
        raise DecisionValidationError("depends_on 存在循环依赖")
    return normalized


def _has_cycle(steps: list[dict[str, Any]]) -> bool:
    graph = {s["step_id"]: list(s.get("depends_on") or []) for s in steps}
    visiting: set[str] = set()
    done: set[str] = set()

    def dfs(node: str) -> bool:
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for nxt in graph.get(node) or []:
            if dfs(nxt):
                return True
        visiting.remove(node)
        done.add(node)
        return False

    return any(dfs(n) for n in graph)
