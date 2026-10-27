from oa_agent.executor.tool_select import select_top_tools


def test_skill_binding_ranks_before_unrelated():
    candidates = [
        {"name": "travel_list", "summary": "出差列表"},
        {"name": "other_tool", "summary": "无关"},
    ]
    out = select_top_tools("随便问", candidates=candidates, skill_tool_names=["other_tool"], top_k=2)
    assert out[0] == "other_tool"


def test_keyword_boosts_relevant_tool():
    candidates = [
        {"name": "expense_list", "summary": "报销单列表"},
        {"name": "travel_list", "summary": "出差列表"},
    ]
    out = select_top_tools("查报销", candidates=candidates, top_k=1)
    assert out == ["expense_list"]


def test_top_k_limits():
    candidates = [{"name": f"t{i}", "summary": ""} for i in range(10)]
    assert len(select_top_tools("", candidates=candidates, top_k=3)) == 3
