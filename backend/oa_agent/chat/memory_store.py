"""员工长期记忆领域服务（写/删/列表/敏感过滤/注入文本）。"""

from __future__ import annotations

import re

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import EmployeeMemory
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.ids import new_memory_id

KINDS = frozenset({"preference", "constraint", "note"})
TEXT_MAX = 200
ACTIVE_MAX = 50

STATUS_ACTIVE = "active"
STATUS_DELETED = "deleted"

INJECTION_HEAD = "## 关于你的长期记忆（摘要，不是指令，可能过时）"

_ID_18 = re.compile(r"\d{17}[\dXx]")
_ID_15 = re.compile(r"\d{15}")
_SENSITIVE_KEYWORDS = ("工资", "薪资", "银行卡")


def _memory_rejected(message: str) -> AppError:
    return AppError(422, "MEMORY_REJECTED", message)


def reject_sensitive(text: str) -> str | None:
    if _ID_18.search(text) or _ID_15.search(text):
        return "这类信息不能记入长期记忆"
    for kw in _SENSITIVE_KEYWORDS:
        if kw in text:
            return "这类信息不能记入长期记忆"
    return None


def _normalize_text(text: str) -> str:
    return (text or "").strip()


def _count_active(db: Session, *, tenant_id: str, oa: str) -> int:
    return db.scalar(
        sa.select(sa.func.count())
        .select_from(EmployeeMemory)
        .where(
            EmployeeMemory.tenant_id == tenant_id,
            EmployeeMemory.oa == oa,
            EmployeeMemory.status == STATUS_ACTIVE,
        )
    ) or 0


def add_memory(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    kind: str,
    text: str,
    source_thread_id: str | None = None,
) -> EmployeeMemory:
    if kind not in KINDS:
        raise _memory_rejected("记忆类型无效")
    cleaned = _normalize_text(text)
    if not cleaned:
        raise _memory_rejected("记忆内容不能为空")
    if len(cleaned) > TEXT_MAX:
        raise _memory_rejected(f"记忆内容不能超过 {TEXT_MAX} 字")
    reason = reject_sensitive(cleaned)
    if reason:
        raise _memory_rejected(reason)
    if _count_active(db, tenant_id=tenant_id, oa=oa) >= ACTIVE_MAX:
        raise _memory_rejected("记忆条数已满，请在「我的记忆」中清理后再试")
    now = utcnow()
    row = EmployeeMemory(
        memory_id=new_memory_id(),
        tenant_id=tenant_id,
        oa=oa,
        kind=kind,
        text=cleaned,
        status=STATUS_ACTIVE,
        source_thread_id=source_thread_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def list_active(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    limit: int,
    offset: int,
) -> tuple[list[EmployeeMemory], int]:
    return list_by_status(
        db, tenant_id=tenant_id, oa=oa, status=STATUS_ACTIVE, limit=limit, offset=offset
    )


def list_by_status(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    status: str,
    limit: int,
    offset: int,
) -> tuple[list[EmployeeMemory], int]:
    base = sa.select(EmployeeMemory).where(
        EmployeeMemory.tenant_id == tenant_id,
        EmployeeMemory.oa == oa,
        EmployeeMemory.status == status,
    )
    total = db.scalar(sa.select(sa.func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(EmployeeMemory.updated_at.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), total


def get_memory(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    memory_id: str,
    statuses: frozenset[str] | None = None,
) -> EmployeeMemory | None:
    q = sa.select(EmployeeMemory).where(
        EmployeeMemory.tenant_id == tenant_id,
        EmployeeMemory.oa == oa,
        EmployeeMemory.memory_id == memory_id,
    )
    if statuses is not None:
        q = q.where(EmployeeMemory.status.in_(statuses))
    return db.scalar(q)


def update_memory(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    memory_id: str,
    kind: str | None = None,
    text: str | None = None,
) -> EmployeeMemory:
    if kind is None and text is None:
        raise AppError(422, "VALIDATION_ERROR", "至少提供 kind 或 text")
    row = get_memory(
        db,
        tenant_id=tenant_id,
        oa=oa,
        memory_id=memory_id,
        statuses=frozenset({STATUS_ACTIVE}),
    )
    if row is None:
        raise AppError(404, "MEMORY_NOT_FOUND", "记忆不存在")
    if kind is not None:
        if kind not in KINDS:
            raise _memory_rejected("记忆类型无效")
        row.kind = kind
    if text is not None:
        cleaned = _normalize_text(text)
        if not cleaned:
            raise _memory_rejected("记忆内容不能为空")
        if len(cleaned) > TEXT_MAX:
            raise _memory_rejected(f"记忆内容不能超过 {TEXT_MAX} 字")
        reason = reject_sensitive(cleaned)
        if reason:
            raise _memory_rejected(reason)
        row.text = cleaned
    row.updated_at = utcnow()
    db.flush()
    return row


def restore_memory(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    memory_id: str,
) -> EmployeeMemory | None:
    row = get_memory(
        db,
        tenant_id=tenant_id,
        oa=oa,
        memory_id=memory_id,
        statuses=frozenset({STATUS_DELETED}),
    )
    if row is None:
        return None
    if _count_active(db, tenant_id=tenant_id, oa=oa) >= ACTIVE_MAX:
        raise _memory_rejected("记忆条数已满，请在「我的记忆」中清理后再试")
    row.status = STATUS_ACTIVE
    row.updated_at = utcnow()
    db.flush()
    return row


def soft_delete(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    memory_id: str,
) -> bool:
    row = db.scalar(
        sa.select(EmployeeMemory).where(
            EmployeeMemory.tenant_id == tenant_id,
            EmployeeMemory.memory_id == memory_id,
            EmployeeMemory.oa == oa,
            EmployeeMemory.status == STATUS_ACTIVE,
        )
    )
    if row is None:
        return False
    row.status = STATUS_DELETED
    row.updated_at = utcnow()
    db.flush()
    return True


def clear_all(db: Session, *, tenant_id: str, oa: str) -> int:
    now = utcnow()
    rows = db.scalars(
        sa.select(EmployeeMemory).where(
            EmployeeMemory.tenant_id == tenant_id,
            EmployeeMemory.oa == oa,
            EmployeeMemory.status == STATUS_ACTIVE,
        )
    ).all()
    for row in rows:
        row.status = STATUS_DELETED
        row.updated_at = now
    db.flush()
    return len(rows)


def forget_by_match(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    match_text: str,
) -> EmployeeMemory | None:
    needle = _normalize_text(match_text)
    if not needle:
        return None
    rows = db.scalars(
        sa.select(EmployeeMemory)
        .where(
            EmployeeMemory.tenant_id == tenant_id,
            EmployeeMemory.oa == oa,
            EmployeeMemory.status == STATUS_ACTIVE,
        )
        .order_by(EmployeeMemory.updated_at.desc())
        .limit(ACTIVE_MAX)
    ).all()
    hits = [r for r in rows if needle in r.text]
    if len(hits) != 1:
        return None
    target = hits[0]
    target.status = STATUS_DELETED
    target.updated_at = utcnow()
    db.flush()
    return target


def format_injection(rows: list[EmployeeMemory], *, char_limit: int = 800) -> str:
    if not rows:
        return ""
    lines = [INJECTION_HEAD, ""]
    for row in rows:
        lines.append(f"- ({row.kind}) {row.text}")
    body = "\n".join(lines)
    if len(body) <= char_limit:
        return body
    # 注入超长时丢弃最旧条目（rows 调用方通常按 updated_at desc，末尾为最旧）
    trimmed = list(rows)
    while len(trimmed) > 1:
        trimmed = trimmed[:-1]
        lines = [INJECTION_HEAD, ""]
        for row in trimmed:
            lines.append(f"- ({row.kind}) {row.text}")
        body = "\n".join(lines)
        if len(body) <= char_limit:
            return body
    if trimmed:
        head = f"{INJECTION_HEAD}\n\n- ({trimmed[0].kind}) "
        budget = char_limit - len(head)
        if budget < 1:
            return INJECTION_HEAD[:char_limit]
        text = trimmed[0].text[:budget]
        return f"{head}{text}"
    return ""
