"""O5 L1：逻辑多 Agent 路由（关键词 → domain）并挂接主引擎。

同一进程多套 DomainSpec（提示词附加 + Skill 子集）；不拆服务。
模型输出不参与权限判定：Skill 仍须先经可见性裁剪，执行仍走 office-api。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

GENERAL_DOMAIN = "general"

_FINANCE_KEYWORDS = frozenset({"报销", "发票", "财务", "费用", "请款"})


@dataclass(frozen=True)
class DomainSpec:
    name: str
    skill_names: frozenset[str] = field(default_factory=frozenset)
    system_extra: str = ""
    keywords: frozenset[str] = field(default_factory=frozenset)


# D14：默认 domains 仅通用助理
DEFAULT_DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec(name=GENERAL_DOMAIN, skill_names=frozenset(), system_extra=""),
)


class Orchestrator:
    def __init__(self, domains: tuple[DomainSpec, ...] | None = None):
        self._domains = domains if domains is not None else DEFAULT_DOMAINS

    def route(self, message: str, domains: tuple[DomainSpec, ...] | None = None) -> str:
        """关键词命中已注册 domain，否则 general。"""
        active = domains if domains is not None else self._domains
        text = (message or "").strip()
        # 非 general 且带关键词的 domain：先匹配
        for d in active:
            if d.name == GENERAL_DOMAIN:
                continue
            kws = d.keywords or (_FINANCE_KEYWORDS if d.name == "finance" else frozenset())
            if kws and any(kw in text for kw in kws):
                return d.name
        return GENERAL_DOMAIN


def domains_from_config(config: dict | None) -> tuple[DomainSpec, ...]:
    """发布配置 multi_agent_domains：[{name, skill_names?, system_extra?, keywords?}]。"""
    specs: list[DomainSpec] = list(DEFAULT_DOMAINS)
    seen = {GENERAL_DOMAIN}
    raw = (config or {}).get("multi_agent_domains") or []
    if not isinstance(raw, list):
        return tuple(specs)
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in seen:
            continue
        skills = item.get("skill_names") or []
        kws = item.get("keywords") or []
        specs.append(DomainSpec(
            name=name,
            skill_names=frozenset(str(s) for s in skills if s),
            system_extra=str(item.get("system_extra") or ""),
            keywords=frozenset(str(k) for k in kws if k),
        ))
        seen.add(name)
    return tuple(specs)


def pick_domain(message: str, domains: tuple[DomainSpec, ...] | None = None) -> DomainSpec:
    active = domains if domains is not None else DEFAULT_DOMAINS
    name = Orchestrator(active).route(message, active)
    for d in active:
        if d.name == name:
            return d
    return active[0]


def filter_skills(skills: Iterable, domain: DomainSpec) -> list:
    """domain.skill_names 为空 = 不裁剪（通用助理看见全部已可见 Skill）。"""
    items = list(skills)
    if not domain.skill_names:
        return items
    return [s for s in items if getattr(s, "name", None) in domain.skill_names]
