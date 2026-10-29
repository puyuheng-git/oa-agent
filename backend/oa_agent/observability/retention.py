"""对话与模型调用日志保留策略。"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import ConversationMessage, ModelCallLog
from oa_agent.db.types import utcnow


def purge_conversation_logs(db: Session, older_than_days: int) -> dict[str, int]:
    """删除早于保留期的 conversation_message 与 model_call_log 行。"""
    days = max(int(older_than_days), 0)
    if days == 0:
        return {"conversation_messages": 0, "model_call_logs": 0}
    cutoff = utcnow() - timedelta(days=days)
    msg_result = db.execute(
        sa.delete(ConversationMessage).where(ConversationMessage.created_at < cutoff)
    )
    call_result = db.execute(
        sa.delete(ModelCallLog).where(ModelCallLog.created_at < cutoff)
    )
    return {
        "conversation_messages": int(msg_result.rowcount or 0),
        "model_call_logs": int(call_result.rowcount or 0),
    }
