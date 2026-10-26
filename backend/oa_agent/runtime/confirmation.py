"""员工业务确认令牌（设计 §13 P3「确认令牌模型」；业务确认闭环待 OA MVP-3 写操作 API）。

令牌只发给员工本人；库内只存 SHA-256。校验 = 未过期 + 本人 oa + 绑定运行 + 载荷哈希一致 + 任务仍 pending，
通过即以乐观锁消费（单次有效）。管理员接口一律拒绝处理 user_confirm 任务。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import InterventionTask
from oa_agent.db.types import utcnow
from oa_agent.ids import new_task_id
from oa_agent.runtime.intervention import PENDING, RESOLVED, USER_CONFIRM

DEFAULT_TTL_SECONDS = 300


class ConfirmationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class IssuedConfirmation:
    task_id: str
    token: str
    expire_at: datetime


def payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(db: Session, tenant_id: str, *, run_id: str, oa: str, workflow_version: str, payload: dict,
          reason: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> IssuedConfirmation:
    """创建 user_confirm 任务并返回明文令牌（只此一次可见）。调用方负责事务提交。"""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    expire_at = now + timedelta(seconds=ttl_seconds)
    task = InterventionTask(
        task_id=new_task_id(), tenant_id=tenant_id, run_id=run_id, kind=USER_CONFIRM, status=PENDING,
        reason=reason[:255], confirm_token_hash=_token_hash(token), expire_at=expire_at, created_at=now,
        binding_snapshot_json={"oa": oa, "run_id": run_id, "workflow_version": workflow_version,
                               "payload_hash": payload_hash(payload)},
    )
    db.add(task)
    return IssuedConfirmation(task.task_id, token, expire_at)


def verify_and_consume(db: Session, *, task_id: str, token: str, oa: str, payload: dict,
                       now: datetime | None = None) -> InterventionTask:
    """校验并单次消费。失败抛 ConfirmationError，不改变任务状态。调用方负责事务提交。"""
    task = db.scalar(sa.select(InterventionTask).where(InterventionTask.task_id == task_id))
    if task is None or task.kind != USER_CONFIRM:
        raise ConfirmationError("CONFIRMATION_NOT_FOUND", "确认请求不存在")
    if task.status != PENDING:
        raise ConfirmationError("CONFIRMATION_USED", "该确认已处理或已失效")
    now = now or utcnow()
    expire_at = task.expire_at if task.expire_at is None or task.expire_at.tzinfo else task.expire_at.replace(tzinfo=UTC)
    if expire_at is None or expire_at <= now:
        raise ConfirmationError("CONFIRMATION_EXPIRED", "确认已过期，请重新发起")
    binding = task.binding_snapshot_json or {}
    if binding.get("oa") != oa:
        raise ConfirmationError("CONFIRMATION_FORBIDDEN", "只能由发起人本人确认")
    if not hmac.compare_digest(task.confirm_token_hash or "", _token_hash(token or "")):
        raise ConfirmationError("CONFIRMATION_INVALID", "确认令牌无效")
    if binding.get("payload_hash") != payload_hash(payload):
        raise ConfirmationError("CONFIRMATION_MISMATCH", "确认内容与发起时不一致")
    won = db.execute(
        sa.update(InterventionTask)
        .where(InterventionTask.task_id == task_id, InterventionTask.status == PENDING,
               InterventionTask.version == task.version)
        .values(status=RESOLVED, result="confirmed", handled_by=f"employee:{oa}", handled_at=now,
                version=task.version + 1)).rowcount == 1
    if not won:
        raise ConfirmationError("CONFIRMATION_USED", "该确认已处理或已失效")
    return task
