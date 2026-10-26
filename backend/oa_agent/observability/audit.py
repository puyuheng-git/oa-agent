"""审计（仅追加）。管理操作在业务同一事务内写审计：审计失败 → 整个操作失败。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from oa_agent.db.models import AuditLog
from oa_agent.db.types import utcnow
from oa_agent.ids import new_audit_id
from oa_agent.observability.redact import redact


@dataclass
class AuditMeta:
    request_id: str = ""
    source_ip: str = ""
    correlation_id: str = ""


class AuditService:
    def __init__(self, tenant_id: str):
        self.tenant = tenant_id

    def record(
        self,
        db: Session,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        resource_type: str = "",
        resource_id: str = "",
        before: str | None = None,
        after: str | None = None,
        result: str = "success",
        reason: str = "",
        meta: AuditMeta | None = None,
    ) -> str:
        meta = meta or AuditMeta()
        audit_id = new_audit_id()
        db.add(
            AuditLog(
                audit_id=audit_id,
                actor_type=actor_type,
                actor_id=actor_id,
                tenant_id=self.tenant,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id),
                before_summary=redact(before) if before else None,
                after_summary=redact(after) if after else None,
                result=result,
                reason=redact(reason, 255),
                occurred_at=utcnow(),
                request_id=meta.request_id,
                source_ip=meta.source_ip,
                correlation_id=meta.correlation_id,
            )
        )
        db.flush()
        return audit_id
