"""员工历史会话（ChatThread）领域逻辑。"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import DEFAULT_TENANT, ChatThread
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.ids import new_thread_id

STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_DELETED = "deleted"

TITLE_MAX = 40

_DEFAULT_VISIBLE = {STATUS_ACTIVE, STATUS_ARCHIVED}


def _thread_not_found() -> AppError:
    return AppError(404, "THREAD_NOT_FOUND", "会话不存在")


def _truncate_title(text: str) -> str:
    cleaned = (text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(cleaned) <= TITLE_MAX:
        return cleaned
    return cleaned[:TITLE_MAX]


def _iso_utc(value) -> str | None:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.isoformat() + "Z"
    return value.isoformat()


def ensure_thread(
    db: Session,
    *,
    thread_id: str,
    oa: str,
    channel: str,
    tenant_id: str = DEFAULT_TENANT,
) -> ChatThread:
    row = db.scalar(
        sa.select(ChatThread).where(
            ChatThread.tenant_id == tenant_id,
            ChatThread.thread_id == thread_id,
        )
    )
    if row is not None:
        if row.oa != oa or row.status == STATUS_DELETED:
            raise _thread_not_found()
        return row
    now = utcnow()
    row = ChatThread(
        thread_id=thread_id,
        tenant_id=tenant_id,
        oa=oa,
        created_channel=channel,
        last_channel=channel,
        status=STATUS_ACTIVE,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def create_thread(
    db: Session,
    *,
    oa: str,
    channel: str,
    tenant_id: str = DEFAULT_TENANT,
) -> ChatThread:
    return ensure_thread(db, thread_id=new_thread_id(), oa=oa, channel=channel, tenant_id=tenant_id)


def get_owned(
    db: Session,
    *,
    thread_id: str,
    oa: str,
    tenant_id: str = DEFAULT_TENANT,
    allow_statuses: set[str] | None = None,
) -> ChatThread | None:
    allowed = allow_statuses if allow_statuses is not None else _DEFAULT_VISIBLE
    row = db.scalar(
        sa.select(ChatThread).where(
            ChatThread.tenant_id == tenant_id,
            ChatThread.thread_id == thread_id,
            ChatThread.oa == oa,
        )
    )
    if row is None or row.status not in allowed:
        return None
    return row


def _list_order() -> tuple:
    """列表排序：最近有消息的在前；无消息的排后。不用 nulls_last（MySQL 不支持 NULLS LAST）。"""
    return (
        ChatThread.last_message_at.is_(None).asc(),
        ChatThread.last_message_at.desc(),
        ChatThread.updated_at.desc(),
    )


def list_threads(
    db: Session,
    *,
    oa: str,
    status: str,
    tenant_id: str,
    limit: int,
    offset: int,
) -> tuple[list[ChatThread], int]:
    base = sa.select(ChatThread).where(
        ChatThread.tenant_id == tenant_id,
        ChatThread.oa == oa,
        ChatThread.status == status,
    )
    total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(*_list_order()).limit(limit).offset(offset)).all()
    return list(rows), int(total)


def patch_thread(
    db: Session,
    thread: ChatThread,
    *,
    title: str | None = None,
    status: str | None = None,
) -> ChatThread:
    if title is not None:
        thread.title = _truncate_title(title)
    if status is not None:
        if status not in (STATUS_ACTIVE, STATUS_ARCHIVED):
            raise AppError(422, "VALIDATION_ERROR", "仅支持在 active 与 archived 之间切换")
        if thread.status == STATUS_DELETED:
            raise AppError(422, "VALIDATION_ERROR", "已删除的会话不可修改状态")
        if status != thread.status and thread.status not in (STATUS_ACTIVE, STATUS_ARCHIVED):
            raise AppError(422, "VALIDATION_ERROR", "仅支持在 active 与 archived 之间切换")
        thread.status = status
    thread.updated_at = utcnow()
    db.flush()
    return thread


def soft_delete(db: Session, thread: ChatThread) -> None:
    thread.status = STATUS_DELETED
    thread.updated_at = utcnow()
    db.flush()


def restore_thread(
    db: Session,
    thread: ChatThread,
    *,
    status: str = STATUS_ACTIVE,
) -> ChatThread:
    if thread.status != STATUS_DELETED:
        raise AppError(422, "VALIDATION_ERROR", "仅已删除的会话可恢复")
    if status not in (STATUS_ACTIVE, STATUS_ARCHIVED):
        raise AppError(422, "VALIDATION_ERROR", "恢复状态仅支持 active 或 archived")
    thread.status = status
    thread.updated_at = utcnow()
    db.flush()
    return thread


def touch_on_user_message(
    db: Session,
    *,
    thread_id: str,
    oa: str,
    channel: str,
    user_text: str,
    tenant_id: str = DEFAULT_TENANT,
) -> None:
    row = db.scalar(
        sa.select(ChatThread).where(
            ChatThread.tenant_id == tenant_id,
            ChatThread.thread_id == thread_id,
        )
    )
    if row is None:
        row = ensure_thread(db, thread_id=thread_id, oa=oa, channel=channel, tenant_id=tenant_id)
    elif row.oa != oa or row.status == STATUS_DELETED:
        raise _thread_not_found()
    now = utcnow()
    row.last_channel = channel
    row.last_message_at = now
    row.updated_at = now
    if not (row.title or "").strip():
        row.title = _truncate_title(user_text)
    db.flush()


def thread_view(t: ChatThread) -> dict:
    return {
        "thread_id": t.thread_id,
        "title": t.title,
        "status": t.status,
        "created_channel": t.created_channel,
        "last_channel": t.last_channel,
        "pinned": t.pinned,
        "created_at": _iso_utc(t.created_at),
        "updated_at": _iso_utc(t.updated_at),
        "last_message_at": _iso_utc(t.last_message_at),
    }
