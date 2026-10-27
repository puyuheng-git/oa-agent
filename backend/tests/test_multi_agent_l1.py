"""O5 L1：Orchestrator 默认 general；注册 finance 时关键词可路由。"""

from oa_agent.runtime.multi_agent import DEFAULT_DOMAINS, DomainSpec, Orchestrator


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
