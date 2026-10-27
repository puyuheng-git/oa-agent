import pytest

from oa_agent.runtime.chain_plan import plan_list_then_detail


def test_plan_list_then_detail_two_steps():
    plan = plan_list_then_detail("expense_list", "expense_detail", "id")
    assert len(plan) == 2
    assert plan[0]["tool"] == "expense_list" and plan[0]["purpose"] == "list"
    assert plan[1]["tool"] == "expense_detail" and plan[1]["detail_id_field"] == "id"


def test_plan_list_then_detail_requires_fields():
    with pytest.raises(ValueError):
        plan_list_then_detail("", "detail", "id")
