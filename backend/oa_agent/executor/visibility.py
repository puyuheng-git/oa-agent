"""Skill 可见性裁剪（D19=C：无规则即全员可见）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import SkillVisibilityRule

_VALID_EFFECTS = frozenset({"allow", "deny"})
_VALID_PRINCIPAL_TYPES = frozenset({"all", "oa", "tag"})


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    oa: str
    tags: list[str]


def _principal_matches(rule: SkillVisibilityRule, principal: PrincipalContext) -> bool:
    if rule.principal_type == "all":
        return True
    if rule.principal_type == "oa":
        return principal.oa == rule.principal_value
    if rule.principal_type == "tag":
        return rule.principal_value in (principal.tags or [])
    return False


class VisibilityService:
    @staticmethod
    def _load_rules(db: Session, *, tenant_id: str, skill_id: int) -> list[SkillVisibilityRule]:
        return list(
            db.scalars(
                sa.select(SkillVisibilityRule)
                .where(
                    SkillVisibilityRule.tenant_id == tenant_id,
                    SkillVisibilityRule.skill_id == skill_id,
                )
                .order_by(SkillVisibilityRule.id)
            ).all()
        )

    @staticmethod
    def is_skill_visible(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
        principal: PrincipalContext,
    ) -> bool:
        rules = VisibilityService._load_rules(db, tenant_id=tenant_id, skill_id=skill_id)
        if not rules:
            return True
        for rule in rules:
            if rule.effect == "deny" and _principal_matches(rule, principal):
                return False
        for rule in rules:
            if rule.effect == "allow" and _principal_matches(rule, principal):
                return True
        return False

    @staticmethod
    def filter_skill_ids(
        db: Session,
        *,
        tenant_id: str,
        skill_ids: Iterable[int],
        principal: PrincipalContext,
    ) -> set[int]:
        return {
            sid
            for sid in skill_ids
            if VisibilityService.is_skill_visible(
                db, tenant_id=tenant_id, skill_id=sid, principal=principal
            )
        }

    @staticmethod
    def list_rules(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
    ) -> list[SkillVisibilityRule]:
        return VisibilityService._load_rules(db, tenant_id=tenant_id, skill_id=skill_id)

    @staticmethod
    def _normalize_rule(raw: Mapping[str, Any]) -> tuple[str, str, str]:
        effect = raw.get("effect")
        principal_type = raw.get("principal_type")
        if effect not in _VALID_EFFECTS:
            raise ValueError(f"invalid effect: {effect!r}")
        if principal_type not in _VALID_PRINCIPAL_TYPES:
            raise ValueError(f"invalid principal_type: {principal_type!r}")
        principal_value = str(raw.get("principal_value") or "")
        if principal_type == "all":
            principal_value = ""
        return effect, principal_type, principal_value

    @staticmethod
    def hidden_reason(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
        principal: PrincipalContext,
    ) -> str | None:
        """不可见时返回原因码 `deny` / `no_allow`；可见则 None。"""
        if VisibilityService.is_skill_visible(
            db, tenant_id=tenant_id, skill_id=skill_id, principal=principal
        ):
            return None
        rules = VisibilityService._load_rules(db, tenant_id=tenant_id, skill_id=skill_id)
        for rule in rules:
            if rule.effect == "deny" and _principal_matches(rule, principal):
                return "deny"
        return "no_allow"

    @staticmethod
    def _find_oa_rule(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
        oa: str,
        effect: str,
    ) -> SkillVisibilityRule | None:
        return db.scalar(
            sa.select(SkillVisibilityRule).where(
                SkillVisibilityRule.tenant_id == tenant_id,
                SkillVisibilityRule.skill_id == skill_id,
                SkillVisibilityRule.effect == effect,
                SkillVisibilityRule.principal_type == "oa",
                SkillVisibilityRule.principal_value == oa,
            )
        )

    @staticmethod
    def add_oa_grant(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
        oa: str,
        effect: str,
        created_by: str,
    ) -> bool:
        """追加针对单 oa 的规则；已存在则幂等。deny 且尚无规则时先补 allow/all 以免误伤他人。"""
        if effect not in _VALID_EFFECTS:
            raise ValueError(f"invalid effect: {effect!r}")
        oa = oa.strip()
        if not oa:
            raise ValueError("oa must be non-empty")
        if VisibilityService._find_oa_rule(
            db, tenant_id=tenant_id, skill_id=skill_id, oa=oa, effect=effect
        ):
            return False
        rules = VisibilityService._load_rules(db, tenant_id=tenant_id, skill_id=skill_id)
        if effect == "deny" and not rules:
            db.add(
                SkillVisibilityRule(
                    tenant_id=tenant_id,
                    skill_id=skill_id,
                    effect="allow",
                    principal_type="all",
                    principal_value="",
                    created_by=created_by,
                )
            )
        db.add(
            SkillVisibilityRule(
                tenant_id=tenant_id,
                skill_id=skill_id,
                effect=effect,
                principal_type="oa",
                principal_value=oa,
                created_by=created_by,
            )
        )
        return True

    @staticmethod
    def remove_oa_grant(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
        oa: str,
        effect: str | None = None,
    ) -> int:
        """删除该 skill 上 principal_type=oa 且 principal_value=oa 的行；可选按 effect 过滤。"""
        oa = oa.strip()
        clause = sa.delete(SkillVisibilityRule).where(
            SkillVisibilityRule.tenant_id == tenant_id,
            SkillVisibilityRule.skill_id == skill_id,
            SkillVisibilityRule.principal_type == "oa",
            SkillVisibilityRule.principal_value == oa,
        )
        if effect is not None:
            if effect not in _VALID_EFFECTS:
                raise ValueError(f"invalid effect: {effect!r}")
            clause = clause.where(SkillVisibilityRule.effect == effect)
        result = db.execute(clause)
        return int(result.rowcount or 0)

    @staticmethod
    def replace_rules(
        db: Session,
        *,
        tenant_id: str,
        skill_id: int,
        rules: Iterable[Mapping[str, Any]],
        created_by: str,
    ) -> None:
        db.execute(
            sa.delete(SkillVisibilityRule).where(
                SkillVisibilityRule.tenant_id == tenant_id,
                SkillVisibilityRule.skill_id == skill_id,
            )
        )
        for raw in rules:
            effect, principal_type, principal_value = VisibilityService._normalize_rule(raw)
            db.add(
                SkillVisibilityRule(
                    tenant_id=tenant_id,
                    skill_id=skill_id,
                    effect=effect,
                    principal_type=principal_type,
                    principal_value=principal_value,
                    created_by=created_by,
                )
            )
