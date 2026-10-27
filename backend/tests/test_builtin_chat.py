"""builtin / mcp 在对话链路里可用：注册表参数 + 结果回复（最终评审 C3）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest_plugins = ("tests.test_chat",)

from oa_agent.executor.executor import Identity, ToolExecutor  # noqa: E402
from oa_agent.executor.registry import ToolRegistry  # noqa: E402
from oa_agent.runtime.graphs import oa_assistant  # noqa: E402

ID_ALICE = Identity(oa="alice", authorization="Bearer secret-token")


class _Rec:
    def __init__(self):
        self.tool_call_count = 0
        self.events: list[dict] = []

    def event(self, kind, **kw):
        self.events.append({"kind": kind, **kw})


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


def _registry(rt) -> ToolRegistry:
    with rt.session() as db:
        return rt.engine.catalog.load_registry(db)


def test_registry_builtin_time_and_calc_have_params_and_text_result(rt):
    reg = _registry(rt)
    time_spec, calc_spec = reg.get("builtin.time"), reg.get("builtin.calc")
    assert time_spec is not None and calc_spec is not None
    assert "timezone" in time_spec.model_params
    assert calc_spec.model_params["expression"]["required"] is True
    for spec in (time_spec, calc_spec):
        assert spec.result_kind == "text" and spec.result_fields == ("text",)


def test_registry_model_params_pass_normalize_steps_and_validate_args(rt):
    reg = _registry(rt)
    tools = {n: (reg.get(n), None) for n in ("builtin.calc",)}
    plan = oa_assistant._normalize_steps(
        [{"tool": "builtin.calc", "args": {"expression": "1+2*3", "oa": "forged", "junk": 1}}], tools)
    assert plan is not None
    assert plan["params"] == {"expression": "1+2*3"}  # 身份/未声明字段被丢弃


def _ctx_for(spec):
    return SimpleNamespace(tools=lambda: {spec.name: (spec, None)}, config={}, skills=[], model=None,
                           num=lambda key: 10)


def test_builtin_time_result_surfaces_in_reply_without_feeding_model_history(rt):
    reg = _registry(rt)
    spec = reg.get("builtin.time")
    res = ToolExecutor(reg, {}).execute("builtin.time", {"timezone": "Asia/Shanghai"}, ID_ALICE, _Rec(), "n")
    assert res["ok"] is True and "UNTRUSTED_DATA" in res["data"]["text"]

    state = {"intent": oa_assistant.TOOL, "tool": "builtin.time", "tool_result": res, "params": {},
             "message": "现在几点"}
    reply = oa_assistant._reply(state, _ctx_for(spec))
    assert "Asia/Shanghai" in reply["content"]            # 员工能看到结果
    assert "UNTRUSTED_DATA" not in reply["content"]        # 围栏标记不外露
    assert reply["data"]["kind"] == "text" and reply["data"]["tool"] == "builtin.time"

    summary = oa_assistant._history_summary(state, reply, _ctx_for(spec))
    assert "Asia/Shanghai" not in summary and "builtin.time" in summary  # 外部文本不回灌模型


def test_builtin_calc_result_surfaces_in_reply(rt):
    reg = _registry(rt)
    spec = reg.get("builtin.calc")
    res = ToolExecutor(reg, {}).execute("builtin.calc", {"expression": "(1+2)*3"}, ID_ALICE, _Rec(), "n")
    state = {"intent": oa_assistant.TOOL, "tool": "builtin.calc", "tool_result": res, "params": {}}
    reply = oa_assistant._reply(state, _ctx_for(spec))
    assert "9" in reply["content"] and reply["data"]["kind"] == "text"


def test_text_reply_cannot_be_referenced_by_later_steps(rt):
    reg = _registry(rt)
    tools = {n: (reg.get(n), None) for n in ("builtin.time", "builtin.calc")}
    steps = [{"tool": "builtin.time", "args": {}},
             {"tool": "builtin.calc", "args": {"expression": {"$ref": "step1.text"}}}]
    assert oa_assistant._normalize_steps(steps, tools) is None


def test_text_reply_survives_triple_backticks_in_body():
    from oa_agent.security.prompt_guard import wrap_untrusted

    spec = SimpleNamespace(name="mcp.x")
    reply = oa_assistant._text_reply(spec, "外部工具", {"text": wrap_untrusted("a ``` b", source="mcp", name="x")})
    assert "a ``` b" in reply["content"] and reply["content"].count("````") == 2


def test_admin_cannot_edit_core_fields_of_mcp_or_builtin_tool(rt, admin):
    import sqlalchemy as sa

    from oa_agent.db.models import Tool
    from tests.test_catalog_admin import LEAVE_TOOL

    with rt.session() as db, db.begin():  # 同名占位：模拟 MCP 同步出的 Tool（名称符合 office NAME_RE）
        db.add(Tool(tenant_id=rt.tenant_id, name=LEAVE_TOOL["name"], kind="mcp", enabled=False, mcp_server_id=1,
                    mcp_tool_name="leave", source_file="mcp:x", updated_by="system"))
    r = admin.put(f"/v1/admin/tools/{LEAVE_TOOL['name']}", json=LEAVE_TOOL)
    assert r.status_code == 422 and "核心字段" in r.json()["error"]["message"]
    with rt.session() as db:
        tool = db.scalar(sa.select(Tool).where(Tool.name == LEAVE_TOOL["name"]))
        assert tool.kind == "mcp" and tool.current_version_id is None  # 未写入 office 版本
