from oa_agent.executor.skill_draft import _tool_brief, draft_skill_from_tools


def test_tool_brief_strips_to_labels():
    brief = _tool_brief({
        "name": "query_leave",
        "summary": "请假",
        "model_params": {"status": {"type": "integer", "label": "状态", "required": True, "enum": [1]}},
        "result": {"kind": "list", "fields": ["id"], "labels": {"id": "单号"}},
    })
    assert brief["name"] == "query_leave"
    assert brief["model_params"]["status"]["label"] == "状态"
    assert "enum" in brief["model_params"]["status"]


def test_draft_skill_from_tools_uses_model(monkeypatch):
    class M:
        def invoke(self, messages):
            class R:
                content = (
                    '{"name":"leave_query_skill","display_name":"请假查询",'
                    '"description":"查请假","instructions":"把自然语言转参数",'
                    '"examples":["我的年假","上个月请假"]}'
                )
            return R()

    out = draft_skill_from_tools(M(), [{"name": "query_leave", "summary": "请假", "model_params": {}, "result": {}}])
    assert out["name"] == "leave_query_skill"
    assert out["display_name"] == "请假查询"
    assert out["tools"] == ["query_leave"]
    assert len(out["examples"]) == 2
