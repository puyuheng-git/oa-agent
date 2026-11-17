"""统一 Tool Contract（P1/P3）：从 ToolSpec 派生执行语义，不改注册表 schema。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolContract:
    name: str
    effect_type: str  # read | write | irreversible
    idempotent: bool
    requires_confirmation: bool
    timeout_seconds: float
    compensation_tool: str | None = None
    reconciliation_strategy: str | None = None  # none | query_status | manual_review

    @property
    def is_side_effect(self) -> bool:
        return self.effect_type in ("write", "irreversible")


def contract_for_spec(spec: Any | None) -> ToolContract:
    if spec is None:
        return ToolContract(
            name="", effect_type="read", idempotent=True,
            requires_confirmation=False, timeout_seconds=30.0,
        )
    name = str(getattr(spec, "name", "") or "")
    risk = str(getattr(spec, "risk_level", "") or "").lower()
    requires_confirmation = bool(getattr(spec, "requires_confirmation", False))
    builtin_id = str(getattr(spec, "builtin_id", "") or "")
    timeout = float(getattr(spec, "timeout_seconds", 30) or 30)

    if builtin_id == "sys.skill_exec" or requires_confirmation or risk == "high":
        effect = "write"
        idempotent = False
        reconcile = "manual_review"
    elif builtin_id in ("sys.skill", "sys.skill_read", "sys.time", "sys.calc", "sys.memory"):
        effect = "read"
        idempotent = True
        reconcile = "none"
    elif risk == "medium":
        effect = "write"
        idempotent = True
        reconcile = "query_status"
    else:
        effect = "read"
        idempotent = True
        reconcile = "none"

    return ToolContract(
        name=name,
        effect_type=effect,
        idempotent=idempotent,
        requires_confirmation=requires_confirmation,
        timeout_seconds=timeout,
        reconciliation_strategy=reconcile,
    )
