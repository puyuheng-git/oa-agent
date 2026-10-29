"""O5 L1：Orchestrator 默认 general；配置可注册 finance；引擎挂接裁剪 Skill。"""

from __future__ import annotations

from types import SimpleNamespace

from oa_agent.runtime.multi_agent import (
    DEFAULT_DOMAINS,
    DomainSpec,
    Orchestrator,
    domains_from_config,
    filter_skills,
    pick_domain,
)


def test_default_routes_to_general():
    orch = Orchestrator()
    assert orch.route("你好") == "general"
    assert orch.route("查一下天气") == "general"


def test_finance_domain_when_registered():
    finance = DomainSpec(name="finance", skill_names=frozenset({"travel_expense"}))
    domains = (*DEFAULT_DOMAINS, finance)
    orch = Orchestrator(domains)
    assert orch.route("帮我看看发票", domains=domains) == "finance"
    assert orch.route("你好", domains=domains) == "general"


def test_domains_from_config_and_filter_skills():
    domains = domains_from_config({
        "multi_agent_domains": [
            {"name": "finance", "skill_names": ["travel_expense"], "system_extra": "你是财务助理"},
        ],
    })
    names = {d.name for d in domains}
    assert names == {"general", "finance"}
    finance = next(d for d in domains if d.name == "finance")
    assert finance.system_extra == "你是财务助理"
    assert pick_domain("报销进度", domains).name == "finance"

    skills = [
        SimpleNamespace(name="travel_expense"),
        SimpleNamespace(name="leave_query"),
    ]
    assert [s.name for s in filter_skills(skills, finance)] == ["travel_expense"]
    assert len(filter_skills(skills, pick_domain("你好", domains))) == 2
