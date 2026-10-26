"""完整对话记录：员工原话、系统回复原文、模型调用的完整请求与输出。

只去掉密钥类内容（`redact_secrets`），业务与个人信息原样保存，供后台查看与训练导出。
写入失败只记日志，不影响员工对话。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from oa_agent.db.models import ConversationMessage, ModelCallLog, Run
from oa_agent.db.types import utcnow
from oa_agent.ids import new_message_id, new_model_call_id
from oa_agent.observability.events import RunRecorder
from oa_agent.observability.redact import redact, redact_secrets

log = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]


def _clean(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(redact_secrets(json.dumps(value, ensure_ascii=False, default=str)))


def record_user(session_factory: SessionFactory, rec: RunRecorder, channel: str, message: str) -> None:
    _add(session_factory, ConversationMessage(
        message_id=new_message_id(), thread_id=rec.thread_id, run_id=rec.run_id, oa=rec.oa, channel=channel,
        role="user", content=redact_secrets(message), created_at=utcnow()))


def record_reply(session_factory: SessionFactory, run_id: str, reply: dict) -> None:
    """回复员工的内容（含转人工提示、错误提示）；身份信息从运行记录取，不信任调用方。"""
    try:
        with session_factory() as db:
            run = db.scalar(sa.select(Run).where(Run.run_id == run_id))
    except SQLAlchemyError as exc:
        log.error("保存对话回复失败（读取运行）%s：%s", run_id, redact(str(exc), 200))
        return
    if run is None:
        return
    _add(session_factory, ConversationMessage(
        message_id=new_message_id(), thread_id=run.thread_id, run_id=run_id, oa=run.oa, channel=run.channel,
        role="assistant", content=redact_secrets(reply.get("content") or ""), reply_type=reply.get("type"),
        data_json=_clean(reply.get("data")), error_code=reply.get("error_code"), created_at=utcnow()))


def flush_model_calls(session_factory: SessionFactory, rec: RunRecorder) -> None:
    logs, rec.model_logs = rec.model_logs, []
    if not logs:
        return
    rows = [ModelCallLog(
        call_id=new_model_call_id(), run_id=rec.run_id, thread_id=rec.thread_id, oa=rec.oa,
        node_name=entry.get("node_name") or "", provider=entry.get("provider") or "", model=entry.get("model") or "",
        messages_json=_clean(entry.get("messages")) or [], output_text=redact_secrets(entry.get("output_text")) or None,
        parsed_json=_clean(entry.get("parsed")), usage_json=entry.get("usage"), status=entry.get("status") or "error",
        error_summary=redact_secrets(entry.get("error_summary"), 2000) or None, duration_ms=entry.get("duration_ms"),
        created_at=utcnow()) for entry in logs]
    _add(session_factory, *rows)


def _add(session_factory: SessionFactory, *rows) -> None:
    try:
        with session_factory() as db, db.begin():
            db.add_all(rows)
    except SQLAlchemyError as exc:
        log.error("保存对话记录失败：%s", redact(f"{type(exc).__name__}: {exc}", 300))
