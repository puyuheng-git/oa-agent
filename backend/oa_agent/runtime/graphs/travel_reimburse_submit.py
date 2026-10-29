"""行程报销提交固定 Workflow：fetch → draft → await_confirm → submit → respond。

写 Tool 仅经 write_tools 白名单；确认令牌 confirmation.issue；await_confirm interrupt 等待员工确认。
"""

from __future__ import annotations

import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable, TypedDict

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy.orm import Session

from oa_agent.executor.executor import Identity, ToolError, ToolExecutor, validate_args
from oa_agent.executor.write_tools import WriteToolExecutor
from oa_agent.observability.events import RunRecorder
from oa_agent.runtime import confirmation
from oa_agent.runtime.run_service import RUNNING, WAITING_CONFIRMATION, RunService

WORKFLOW_ID = "travel_reimburse_submit"
WORKFLOW_VERSION = "1"
BUSINESS_TYPE = "travel_reimburse_submit"

DRAFT_TOOL = "create_travel_expense_submit_draft"
SUBMIT_TOOL = "submit_travel_expense_reimbursement"
DETAIL_TOOL = "query_my_travel_expense_detail"


class SubmitState(TypedDict, total=False):
    run_id: str
    expense_id: int
    detail: dict
    draft: dict
    confirm_payload: dict
    confirm_task_id: str
    confirm_token: str
    confirm_expire_at: str
    submit_result: dict
    reply: dict


@dataclass
class WriteRunContext:
    recorder: RunRecorder
    identity: Identity
    read_executor: ToolExecutor
    write_executor: WriteToolExecutor
    runs: RunService
    tenant_id: str
    session_factory: Callable[[], AbstractContextManager[Session]]


def _traced(name: str, fn: Callable[[SubmitState, WriteRunContext], dict],
            contexts: Callable[[str], WriteRunContext]):
    def node(state: SubmitState) -> dict:
        ctx = contexts(state["run_id"])
        rec = ctx.recorder
        rec.event("node_start", node_name=name, input_summary=_node_input(name, state))
        started = time.perf_counter()
        try:
            out = fn(state, ctx)
        except GraphInterrupt:
            rec.event("node_interrupted", node_name=name, status="waiting_confirmation",
                      duration_ms=int((time.perf_counter() - started) * 1000))
            raise
        except Exception as exc:
            rec.failed_node = name
            rec.event("node_error", node_name=name, status="error",
                      duration_ms=int((time.perf_counter() - started) * 1000),
                      error_code=getattr(exc, "code", type(exc).__name__),
                      error_summary=getattr(exc, "message", str(exc)))
            raise
        rec.event("node_end", node_name=name, status="ok",
                  duration_ms=int((time.perf_counter() - started) * 1000), output_summary=_node_output(name, out))
        return out

    node.__name__ = name
    return node


def _node_input(name: str, state: SubmitState) -> dict | None:
    if name == "fetch":
        return {"expense_id": state.get("expense_id")}
    if name == "await_confirm":
        return {"draft_id": (state.get("draft") or {}).get("draft_id")}
    return None


def _node_output(name: str, out: dict) -> dict | None:
    if name == "submit":
        return {"submit_id": (out.get("submit_result") or {}).get("submit_id")}
    return None


def fetch_detail(state: SubmitState, ctx: WriteRunContext) -> dict:
    expense_id = state.get("expense_id")
    if not isinstance(expense_id, int) or expense_id < 1:
        raise ToolError("INVALID_ARGUMENT", "缺少有效的行程报销单号")
    spec = ctx.read_executor.registry.get(DETAIL_TOOL)
    if spec is None:
        raise ToolError("TOOL_NOT_AVAILABLE", "查询详情 Tool 不可用")
    args, _ = validate_args(spec, {"id": expense_id})
    result = ctx.read_executor.execute(DETAIL_TOOL, args, ctx.identity, ctx.recorder, "fetch")
    detail = result.get("data") or {}
    if not detail.get("id"):
        raise ToolError("UPSTREAM_BIZ_ERROR", "未找到该行程报销单")
    return {"detail": detail}


def create_draft(state: SubmitState, ctx: WriteRunContext) -> dict:
    expense_id = state["expense_id"]
    result = ctx.write_executor.execute(DRAFT_TOOL, {"source_expense_id": expense_id}, ctx.identity,
                                        ctx.recorder, "draft")
    draft = result.get("data") or {}
    if not draft.get("draft_id"):
        raise ToolError("UPSTREAM_BAD_RESPONSE", "创建草稿响应缺少 draft_id")
    return {"draft": draft}


def prepare_confirm(state: SubmitState, ctx: WriteRunContext) -> dict:
    """签发确认令牌（仅执行一次；resume 不会回到此节点）。"""
    draft = state.get("draft") or {}
    detail = state.get("detail") or {}
    payload = {
        "action": SUBMIT_TOOL,
        "expense_id": state["expense_id"],
        "draft_id": draft.get("draft_id"),
        "total_amount": draft.get("total_amount") or detail.get("total_amount"),
    }
    with ctx.session_factory() as db, db.begin():
        issued = confirmation.issue(
            db, ctx.tenant_id, run_id=state["run_id"], oa=ctx.identity.oa,
            workflow_version=WORKFLOW_VERSION, payload=payload, reason="确认提交行程报销",
        )
        ctx.runs.transition(state["run_id"], RUNNING, WAITING_CONFIRMATION, db=db)
    ctx.recorder.event(
        "run_waiting_confirmation", status=WAITING_CONFIRMATION,
        metadata={"task_id": issued.task_id},
    )
    return {
        "confirm_payload": payload,
        "confirm_task_id": issued.task_id,
        "confirm_token": issued.token,
        "confirm_expire_at": issued.expire_at.isoformat(),
    }


def wait_confirm(state: SubmitState, ctx: WriteRunContext) -> dict:
    """interrupt 挂起；resume 后从此处继续到 submit，不会重复签发令牌。"""
    payload = state.get("confirm_payload") or {}
    interrupt({
        "run_id": state["run_id"],
        "kind": "user_confirm",
        "task_id": state.get("confirm_task_id"),
        "token": state.get("confirm_token"),
        "expire_at": state.get("confirm_expire_at"),
        "payload": payload,
    })
    return {}


def submit_draft(state: SubmitState, ctx: WriteRunContext) -> dict:
    draft_id = (state.get("draft") or {}).get("draft_id")
    if not draft_id:
        raise ToolError("INVALID_ARGUMENT", "缺少草稿号")
    idem = f"submit-{state['run_id']}-{draft_id}"
    result = ctx.write_executor.execute(
        SUBMIT_TOOL, {"draft_id": draft_id}, ctx.identity, ctx.recorder, "submit", idempotency_key=idem,
    )
    return {"submit_result": result.get("data") or {}}


def respond(state: SubmitState, ctx: WriteRunContext) -> dict:
    submit = state.get("submit_result") or {}
    draft = state.get("draft") or {}
    detail = state.get("detail") or {}
    submit_id = submit.get("submit_id")
    lines = [
        "行程报销已提交。",
        f"原单号：{detail.get('id') or state.get('expense_id')}",
        f"草稿号：{draft.get('draft_id')}",
    ]
    if submit_id is not None:
        lines.append(f"提交单号：{submit_id}")
    if submit.get("status_text"):
        lines.append(f"状态：{submit['status_text']}")
    reply = {"type": "text", "content": "\n".join(lines), "data": {"submit": submit, "draft": draft}}
    return {"reply": reply}


def build_graph(checkpointer, contexts: Callable[[str], WriteRunContext]):
    g = StateGraph(SubmitState)
    g.add_node("fetch", _traced("fetch", fetch_detail, contexts))
    g.add_node("draft", _traced("draft", create_draft, contexts))
    g.add_node("prepare_confirm", _traced("prepare_confirm", prepare_confirm, contexts))
    g.add_node("wait_confirm", _traced("wait_confirm", wait_confirm, contexts))
    g.add_node("submit", _traced("submit", submit_draft, contexts))
    g.add_node("respond", _traced("respond", respond, contexts))
    g.add_edge(START, "fetch")
    g.add_edge("fetch", "draft")
    g.add_edge("draft", "prepare_confirm")
    g.add_edge("prepare_confirm", "wait_confirm")
    g.add_edge("wait_confirm", "submit")
    g.add_edge("submit", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)
