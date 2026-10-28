"""/v1/chat/*：员工对话（设计 §6.1、§12）。"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time

import sqlalchemy as sa
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from oa_agent.auth import chat_launch
from oa_agent.auth.chat_launch import ChatSession
from oa_agent.auth.rbac import request_meta
from oa_agent.chat.service import (
    chat_available, confirm_write, guard_message, handle_message, launch_policy, load_reply, load_settings,
    office_client, setting, skill_menu, start_workflow, user_reply_for, workflow_menu,
)
from oa_agent.chat import memory_store
from oa_agent.chat.threads import (
    create_thread,
    ensure_thread,
    get_owned,
    list_threads,
    patch_thread,
    soft_delete,
    thread_view,
)
from oa_agent.db.models import ConversationMessage, Run
from oa_agent.errors import AppError
from oa_agent.runtime.run_service import TERMINAL
from oa_agent.runtime_state import get_runtime

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/chat", tags=["chat"])


class LaunchIn(BaseModel):
    assertion: str = Field(min_length=10, max_length=4096)


class SessionIn(BaseModel):
    launch_code: str = Field(min_length=10, max_length=128)
    thread_id: str | None = Field(default=None, min_length=8, max_length=40)


class MessageIn(BaseModel):
    message: str = Field(max_length=2000)
    client_msg_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ThreadPatchIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: Literal["active", "archived"] | None = None


class SwitchIn(BaseModel):
    thread_id: str = Field(min_length=8, max_length=40)


class MemoryClearIn(BaseModel):
    confirm: Literal[True]


class ConfirmationIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)


class WorkflowStartIn(BaseModel):
    client_msg_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expense_id: int | None = Field(default=None, ge=1)


class ChatAuth:
    def __init__(self, ticket: str, session: ChatSession):
        self.ticket = ticket
        self.session = session


def chat_auth(request: Request) -> ChatAuth:
    rt = get_runtime(request)
    ticket = chat_launch.bearer(request)
    session = chat_launch.load_session(rt.kv.current, ticket)
    if session is None:
        raise AppError(401, "UNAUTHENTICATED", "会话已过期，请重新打开 OA 助手页")
    return ChatAuth(ticket, session)


@router.post("/launch")
def launch(body: LaunchIn, request: Request):
    """OA 宿主页服务端调用：assertion → 一次性 launch_code。"""
    rt = get_runtime(request)
    oa_cfg = load_settings(rt, "oa")
    policy = launch_policy(rt)
    identity = chat_launch.verify_assertion(body.assertion, oa_cfg.get("assertion_hmac_secret"), rt.kv.current,
                                            policy=policy)
    code = chat_launch.create_launch(rt.kv.current, identity, office_client(rt), oa_cfg.get("gateway_secret"),
                                     policy)
    meta = request_meta(request)
    try:
        with rt.session() as db, db.begin():
            rt.audit.record(db, actor_type="employee", actor_id=identity["oa"], action="chat.launch",
                            resource_type="chat_session", meta=meta)
    except Exception:  # noqa: BLE001 —— 员工登录审计失败不阻断对话（与管理操作不同）
        pass
    return {"launch_code": code, "expires_in": policy.launch_ttl}


@router.post("/session")
def create_session(body: SessionIn, request: Request):
    rt = get_runtime(request)
    policy = launch_policy(rt)
    ticket, session = chat_launch.redeem_launch(rt.kv.current, body.launch_code, policy)
    if body.thread_id:
        with rt.session() as db, db.begin():
            if get_owned(db, thread_id=body.thread_id, oa=session.oa) is None:
                raise AppError(404, "THREAD_NOT_FOUND", "会话不存在")
        session.thread_id = body.thread_id
        chat_launch.store_session(rt.kv.current, ticket, session, policy)
    else:
        channel = session.channel or "oa_web"
        with rt.session() as db, db.begin():
            ensure_thread(db, thread_id=session.thread_id, oa=session.oa, channel=channel)
    expires_in = min(policy.ticket_ttl, session.token_expires_at - int(time.time()))
    return {"ticket": ticket, "expires_in": expires_in, "display_name": session.display_name,
            "thread_id": session.thread_id,
            **_session_extras(rt, oa=session.oa, office_token=session.office_token)}


@router.get("/session")
def get_session(request: Request, auth: ChatAuth = Depends(chat_auth)):
    rt = get_runtime(request)
    return {"display_name": auth.session.display_name, "thread_id": auth.session.thread_id,
            **_session_extras(rt, oa=auth.session.oa, office_token=auth.session.office_token)}


def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.isoformat() + "Z"
    return value.isoformat()


def _message_item(m: ConversationMessage) -> dict:
    return {
        "message_id": m.message_id,
        "role": m.role,
        "content": m.content,
        "reply_type": m.reply_type,
        "data": m.data_json,
        "error_code": m.error_code,
        "created_at": _iso_utc(m.created_at),
        "run_id": m.run_id,
    }


def _session_extras(rt, *, oa: str, office_token: str = "") -> dict:
    """员工页面需要的能力与参数：可用功能、能否聊天、消息长度上限、转人工结果轮询参数。"""
    return {"skills": skill_menu(rt, oa=oa, office_token=office_token),
            "workflows": workflow_menu(rt),
            "chat": chat_available(rt),
            "message_max_chars": int(setting(rt, "chat", "message_max_chars")),
            "poll_interval_seconds": int(setting(rt, "chat", "result_poll_seconds")),
            "poll_max_minutes": int(setting(rt, "runtime", "intervention_expire_minutes")) + 5}


@router.get("/workflows")
def list_chat_workflows(request: Request, auth: ChatAuth = Depends(chat_auth)):
    """固定 Workflow 目录（写类未开 flag 时 available=false）。"""
    return {"items": workflow_menu(get_runtime(request))}


@router.post("/workflows/{workflow_id}/start")
def start_chat_workflow(workflow_id: str, body: WorkflowStartIn, request: Request,
                        auth: ChatAuth = Depends(chat_auth)):
    """员工显式启动写类固定 Workflow（按钮入口）；对话类请走 /messages。"""
    rt = get_runtime(request)
    params = {}
    if body.expense_id is not None:
        params["expense_id"] = body.expense_id
    return start_workflow(
        rt, auth.session, workflow_id, params, getattr(request.state, "request_id", "") or body.client_msg_id,
        session_key=chat_launch.session_key(auth.ticket),
    )


@router.get("/threads")
def list_chat_threads(
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
    status: Literal["active", "archived"] = Query("active"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    rt = get_runtime(request)
    offset = (page - 1) * page_size
    with rt.session() as db:
        rows, total = list_threads(
            db,
            oa=auth.session.oa,
            status=status,
            tenant_id=rt.tenant_id,
            limit=page_size,
            offset=offset,
        )
    return {
        "items": [thread_view(t) for t in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/threads")
def create_chat_thread(request: Request, auth: ChatAuth = Depends(chat_auth)):
    rt = get_runtime(request)
    policy = launch_policy(rt)
    channel = auth.session.channel or "oa_web"
    with rt.session() as db, db.begin():
        row = create_thread(db, oa=auth.session.oa, channel=channel, tenant_id=rt.tenant_id)
        view = thread_view(row)
    auth.session.thread_id = row.thread_id
    chat_launch.store_session(rt.kv.current, auth.ticket, auth.session, policy)
    return view


@router.get("/threads/{thread_id}/messages")
def list_thread_messages(
    thread_id: str,
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    rt = get_runtime(request)
    offset = (page - 1) * page_size
    with rt.session() as db:
        if get_owned(db, thread_id=thread_id, oa=auth.session.oa, tenant_id=rt.tenant_id) is None:
            raise AppError(404, "THREAD_NOT_FOUND", "会话不存在")
        base = sa.select(ConversationMessage).where(
            ConversationMessage.tenant_id == rt.tenant_id,
            ConversationMessage.thread_id == thread_id,
            ConversationMessage.oa == auth.session.oa,
        )
        total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
        rows = db.scalars(
            base.order_by(ConversationMessage.id.asc()).offset(offset).limit(page_size)
        ).all()
    return {
        "items": [_message_item(m) for m in rows],
        "page": page,
        "page_size": page_size,
        "total": int(total),
    }


@router.patch("/threads/{thread_id}")
def patch_chat_thread(
    thread_id: str,
    body: ThreadPatchIn,
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
):
    rt = get_runtime(request)
    with rt.session() as db, db.begin():
        row = get_owned(db, thread_id=thread_id, oa=auth.session.oa, tenant_id=rt.tenant_id)
        if row is None:
            raise AppError(404, "THREAD_NOT_FOUND", "会话不存在")
        patch_thread(db, row, title=body.title, status=body.status)
        return thread_view(row)


@router.delete("/threads/{thread_id}")
def delete_chat_thread(
    thread_id: str,
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
):
    rt = get_runtime(request)
    with rt.session() as db, db.begin():
        row = get_owned(db, thread_id=thread_id, oa=auth.session.oa, tenant_id=rt.tenant_id)
        if row is None:
            raise AppError(404, "THREAD_NOT_FOUND", "会话不存在")
        soft_delete(db, row)
    return {"ok": True}


@router.post("/session/switch")
def switch_session(
    body: SwitchIn,
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
):
    rt = get_runtime(request)
    policy = launch_policy(rt)
    with rt.session() as db:
        if get_owned(db, thread_id=body.thread_id, oa=auth.session.oa, tenant_id=rt.tenant_id) is None:
            raise AppError(404, "THREAD_NOT_FOUND", "会话不存在")
    auth.session.thread_id = body.thread_id
    chat_launch.store_session(rt.kv.current, auth.ticket, auth.session, policy)
    return {"thread_id": body.thread_id,
            **_session_extras(rt, oa=auth.session.oa, office_token=auth.session.office_token)}


@router.post("/session/refresh")
def refresh(request: Request, auth: ChatAuth = Depends(chat_auth)):
    rt = get_runtime(request)
    ttl = chat_launch.refresh_session(rt.kv.current, auth.ticket, auth.session, lambda: office_client(rt),
                                      load_settings(rt, "oa").get("gateway_secret"), launch_policy(rt))
    return {"expires_in": ttl}


@router.post("/messages")
def post_message(body: MessageIn, request: Request, auth: ChatAuth = Depends(chat_auth)):
    rt = get_runtime(request)
    guard_message(rt, auth.session, body.message, body.client_msg_id)
    return handle_message(rt, auth.session, body.message.strip(), request.state.request_id,
                          session_key=chat_launch.session_key(auth.ticket))


SSE_HEARTBEAT = 15  # 秒：无输出时发注释行，防止代理/负载均衡因空闲断开


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


@router.post("/messages/stream")
def post_message_stream(body: MessageIn, request: Request, auth: ChatAuth = Depends(chat_auth)):
    """与 /messages 相同，但以 SSE 返回：delta 事件为回复正文的新增片段，done 事件为完整结果（与 /messages 响应同形）。
    校验失败（限流、重复、过长）仍以普通 JSON 错误返回。员工中途断开不影响运行，结果可按 run_id 查询。"""
    rt = get_runtime(request)
    guard_message(rt, auth.session, body.message, body.client_msg_id)
    events: queue.Queue = queue.Queue()
    session, correlation_id = auth.session, request.state.request_id
    key = chat_launch.session_key(auth.ticket)

    def work() -> None:
        try:
            result = handle_message(rt, session, body.message.strip(), correlation_id, session_key=key,
                                    on_delta=lambda piece: events.put(("delta", {"text": piece})))
            events.put(("done", result))
        except AppError as exc:
            events.put(("error", {"code": exc.code, "message": exc.message}))
        except Exception:  # noqa: BLE001
            log.exception("流式对话失败")
            events.put(("error", {"code": "INTERNAL_ERROR", "message": "处理失败，请稍后重试"}))

    threading.Thread(target=work, name="chat-stream", daemon=True).start()

    def stream():
        while True:
            try:
                event, data = events.get(timeout=SSE_HEARTBEAT)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            yield _sse(event, data)
            if event != "delta":
                return

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _memory_item(row) -> dict:
    return {
        "memory_id": row.memory_id,
        "kind": row.kind,
        "text": row.text,
        "created_at": _iso_utc(row.created_at),
        "updated_at": _iso_utc(row.updated_at),
    }


@router.get("/memory")
def list_memory(
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    rt = get_runtime(request)
    offset = (page - 1) * page_size
    with rt.session() as db:
        rows, total = memory_store.list_active(
            db,
            tenant_id=rt.tenant_id,
            oa=auth.session.oa,
            limit=page_size,
            offset=offset,
        )
    return {
        "items": [_memory_item(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": int(total),
    }


@router.delete("/memory")
def clear_memory(
    body: MemoryClearIn,
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
):
    rt = get_runtime(request)
    with rt.session() as db, db.begin():
        deleted = memory_store.clear_all(
            db, tenant_id=rt.tenant_id, oa=auth.session.oa
        )
    return {"ok": True, "deleted": deleted}


@router.delete("/memory/{memory_id}")
def delete_memory(
    memory_id: str,
    request: Request,
    auth: ChatAuth = Depends(chat_auth),
):
    rt = get_runtime(request)
    with rt.session() as db, db.begin():
        ok = memory_store.soft_delete(
            db,
            tenant_id=rt.tenant_id,
            oa=auth.session.oa,
            memory_id=memory_id,
        )
    if not ok:
        raise AppError(404, "MEMORY_NOT_FOUND", "记忆不存在")
    return {"ok": True}


@router.post("/confirmations/{task_id}")
def confirm_workflow(task_id: str, body: ConfirmationIn, request: Request, auth: ChatAuth = Depends(chat_auth)):
    """员工确认写操作：校验令牌后恢复固定 Workflow（管理员不能代确认）。"""
    rt = get_runtime(request)
    return confirm_write(rt, auth.session, task_id, body.token.strip(), request.state.request_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request, auth: ChatAuth = Depends(chat_auth)):
    """员工查询本人运行的状态与结果（转人工后轮询）。只返回本人的运行。"""
    rt = get_runtime(request)
    with rt.session() as db:
        run = db.scalar(sa.select(Run).where(Run.tenant_id == rt.tenant_id, Run.run_id == run_id))
    if run is None or run.oa != auth.session.oa:
        raise AppError(404, "NOT_FOUND", "记录不存在")
    done = run.run_status in TERMINAL
    reply = load_reply(rt, run_id) if done else None
    if done and reply is None:
        reply = user_reply_for(rt, run.error_code) if run.error_code else {
            "type": "text", "content": "结果已过期，请重新提问。", "data": None}
    return {"run_id": run_id, "run_status": run.run_status, "done": done, "reply": reply}
