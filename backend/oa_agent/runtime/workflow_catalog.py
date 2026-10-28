"""固定 Workflow 注册表（子系统 D / X5）。

代码登记只读与写类流程；写类是否对员工可用取决于 runtime.write_workflows_enabled。
不代替 P5 发布配置；不开放自由注册非 GET Tool。
"""

from __future__ import annotations

from dataclasses import dataclass

from oa_agent.runtime.graphs import travel_query, travel_reimburse_submit


@dataclass(frozen=True)
class WorkflowEntry:
    workflow_id: str
    name: str
    kind: str  # chat | write
    description: str
    aliases: tuple[str, ...] = ()
    start_params: tuple[str, ...] = ()


# 一期：只读通用助理 + 行程报销提交（写，需 flag）
_ENTRIES: tuple[WorkflowEntry, ...] = (
    WorkflowEntry(
        workflow_id=travel_query.WORKFLOW_ID,
        name="通用助理",
        kind="chat",
        description="自然语言查询与对话；默认对话入口。",
        aliases=(travel_query.WORKFLOW_ID_ALIAS,),
    ),
    WorkflowEntry(
        workflow_id=travel_reimburse_submit.WORKFLOW_ID,
        name="行程报销提交",
        kind="write",
        description="固定步骤：拉取明细 → 草稿 → 员工确认 → 提交。需管理员开启写 Workflow。",
        start_params=("expense_id",),
    ),
)


def resolve_id(workflow_id: str) -> str:
    wid = (workflow_id or "").strip()
    if wid == travel_query.WORKFLOW_ID_ALIAS:
        return travel_query.WORKFLOW_ID
    return wid


def get(workflow_id: str) -> WorkflowEntry | None:
    wid = resolve_id(workflow_id)
    for e in _ENTRIES:
        if e.workflow_id == wid or wid in e.aliases:
            return e
    return None


def list_entries(*, write_enabled: bool) -> list[dict]:
    """员工/管理端只读目录。写类在未开 flag 时仍列出，但 available=false。"""
    out = []
    for e in _ENTRIES:
        available = True if e.kind == "chat" else bool(write_enabled)
        out.append({
            "workflow_id": e.workflow_id,
            "name": e.name,
            "kind": e.kind,
            "description": e.description,
            "aliases": list(e.aliases),
            "start_params": list(e.start_params),
            "available": available,
            "unavailable_reason": None if available else "write_workflows_disabled",
        })
    return out
