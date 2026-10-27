"""O5 L1：逻辑多 Agent 路由骨架（关键词 → domain）。

未接 LangGraph 引擎；O2 写闭环与 O4 可见性门禁通过后再挂 chat 路由。
"""

from __future__ import annotations

from dataclasses import dataclass, field

GENERAL_DOMAIN = "general"

_FINANCE_KEYWORDS = frozenset({"报销", "发票", "财务", "费用", "请款"})


@dataclass(frozen=True)
class DomainSpec:
    name: str
    skill_names: frozenset[str] = field(default_factory=frozenset)
    system_extra: str = ""


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
        names = {d.name for d in active}
        text = (message or "").strip()
        if "finance" in names and any(kw in text for kw in _FINANCE_KEYWORDS):
            return "finance"
        return GENERAL_DOMAIN
