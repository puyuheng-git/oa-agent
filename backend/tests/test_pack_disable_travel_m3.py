"""M3 Task 4/5 — 禁用 oa_travel 后规则、Skill/Tool 与写 workflow 不可见。"""

from oa_agent.packs.registry import PackRegistry
from oa_agent.runtime import workflow_catalog as wc
from oa_agent.runtime.intent_rules import DETAIL, LIST
from oa_agent.settings import REPO_ROOT

PACKS_ROOT = REPO_ROOT / "packs"

TRAVEL_SKILL = "travel_expense_query"
TRAVEL_TOOLS = {
    "query_my_travel_expense_list",
    "query_my_travel_expense_detail",
}


def test_aggregated_rule_tools_enabled_has_list_detail():
    registry = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=[])
    assert registry.is_enabled("oa_travel") is True
    tools = registry.aggregated_rule_tools()
    assert tools.get(LIST) == "query_my_travel_expense_list"
    assert tools.get(DETAIL) == "query_my_travel_expense_detail"


def test_aggregated_rule_tools_disabled_omits_travel():
    registry = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=["oa_travel"])
    assert registry.is_enabled("oa_travel") is False
    tools = registry.aggregated_rule_tools()
    assert tools == {}
    assert tools.get(LIST) is None
    assert tools.get(DETAIL) is None
    assert "query_my_travel_expense_list" not in tools.values()
    assert "query_my_travel_expense_detail" not in tools.values()


def test_load_intent_rules_from_oa_travel_yaml():
    from oa_agent.packs.rules_load import load_intent_rules

    path = PACKS_ROOT / "oa_travel" / "rules" / "intent.yaml"
    loaded = load_intent_rules(path)
    assert loaded["rule_tools"][LIST] == "query_my_travel_expense_list"
    assert loaded["rule_tools"][DETAIL] == "query_my_travel_expense_detail"


def test_owned_skill_and_tool_names_for_oa_travel():
    registry = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=[])
    skills = registry.owned_skill_names("oa_travel")
    tools = registry.owned_tool_names("oa_travel")
    assert TRAVEL_SKILL in skills
    assert TRAVEL_TOOLS <= tools


def test_disabled_owned_names_helper():
    enabled = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=[])
    assert enabled.disabled_owned_skill_names() == set()
    assert enabled.disabled_owned_tool_names() == set()

    disabled = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=["oa_travel"])
    assert TRAVEL_SKILL in disabled.disabled_owned_skill_names()
    assert TRAVEL_TOOLS <= disabled.disabled_owned_tool_names()


def test_filter_skills_excludes_disabled_pack_owned():
    from oa_agent.executor.catalog import SkillState

    registry = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=["oa_travel"])
    skills = [
        SkillState(
            name=TRAVEL_SKILL,
            enabled=True,
            valid=True,
            display_name="行程",
            tools=list(TRAVEL_TOOLS),
        ),
        SkillState(
            name="other_skill",
            enabled=True,
            valid=True,
            display_name="其它",
            tools=["some_builtin"],
        ),
    ]
    filtered = registry.filter_skills(skills)
    assert [s.name for s in filtered] == ["other_skill"]


def test_workflow_catalog_marks_travel_submit_unavailable_when_pack_disabled():
    registry = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=["oa_travel"])
    items = wc.list_entries(write_enabled=True, pack_registry=registry)
    submit = next(i for i in items if i["workflow_id"] == "travel_reimburse_submit")
    assert submit["available"] is False
    assert submit["unavailable_reason"] == "pack_disabled"

    enabled = PackRegistry.from_disk(PACKS_ROOT, disabled_ids=[])
    items_on = wc.list_entries(write_enabled=True, pack_registry=enabled)
    submit_on = next(i for i in items_on if i["workflow_id"] == "travel_reimburse_submit")
    assert submit_on["available"] is True
    assert submit_on["unavailable_reason"] is None
