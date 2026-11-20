import pytest

from oa_agent.executor.skill_draft import _tool_brief, draft_skill_from_tools
from oa_agent.runtime.llm import ModelCallError


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


def test_tool_brief_tolerates_malformed_schema():
    """历史/坏契约不得在 brief 阶段抛 TypeError（否则接口冒成 500）。"""
    brief = _tool_brief({
        "name": "weird_tool",
        "summary": "x",
        "model_params": ["not", "a", "dict"],
        "result": {"fields": {"a": 1}, "labels": ["bad"]},
    })
    assert brief["name"] == "weird_tool"
    assert brief["model_params"] == {}
    assert brief["result"]["fields"] == ["a"]
    assert brief["result"]["labels"] == {}


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


def test_draft_skill_from_tools_normalizes_examples_string():
    class M:
        def invoke(self, messages):
            class R:
                content = (
                    '{"name":"leave_query_skill","display_name":"请假",'
                    '"description":"d","instructions":"i","examples":"我的年假\\n上个月请假"}'
                )
            return R()

    out = draft_skill_from_tools(M(), [{"name": "query_leave", "summary": "请假"}])
    assert out["examples"] == ["我的年假", "上个月请假"]


def test_draft_skill_from_tools_rejects_non_object_json():
    class M:
        def invoke(self, messages):
            class R:
                content = '["only","array"]'

            return R()

    with pytest.raises(ModelCallError, match="JSON 对象"):
        draft_skill_from_tools(M(), [{"name": "query_leave", "summary": "请假"}])
