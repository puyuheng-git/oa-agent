"""员工说导出时必须调用 builtin.export，而不是当成闲聊。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from oa_agent.executor.catalog import SkillState
from oa_agent.executor.registry import ToolSpec
from oa_agent.runtime.graphs import oa_assistant
from oa_agent.runtime.intent_rules import LIST


def _export_spec() -> ToolSpec:
    return ToolSpec(
        name="builtin.export", method="", path="", version="builtin", schema_hash="",
        risk_level="medium", requires_confirmation=False, timeout_seconds=10,
        inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params={
            "content": {"type": "string", "label": "内容", "required": True},
            "filename": {"type": "string", "label": "文件名"},
        },
        result_kind="text", result_fields=("text",), summary="导出文件并返回下载票据",
        kind="builtin", builtin_id="sys.export",
    )


def _list_spec() -> ToolSpec:
    return ToolSpec(
        name="query_my_travel_expense_list", method="GET", path="/x", version="1", schema_hash="h",
        risk_level="low", requires_confirmation=False, timeout_seconds=10,
        inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params={
            "date_gte": {"type": "string", "format": "date"},
            "date_lte": {"type": "string", "format": "date"},
        },
        result_kind="list", result_fields=("id", "amount"), summary="行程报销列表",
    )


def _ctx(registry, skills):
    return oa_assistant.RunContext(
        recorder=SimpleNamespace(),
        identity=SimpleNamespace(oa="alice"),
        executor=SimpleNamespace(registry=registry),
        today=date(2026, 11, 5),
        skills=skills,
        config={"chat_mode": "llm", "intent_mode": "auto"},
    )


class _Reg:
    def __init__(self, specs: dict[str, ToolSpec]):
        self._specs = specs

    def names(self):
        return sorted(self._specs)

    def get(self, name):
        return self._specs.get(name)


def test_enabled_export_is_visible_even_when_skill_does_not_bind_it():
    travel = SkillState(
        name="travel_expense_query", enabled=True, valid=True,
        display_name="行程报销查询", tools=["query_my_travel_expense_list"],
    )
    reg = _Reg({
        "query_my_travel_expense_list": _list_spec(),
        "builtin.export": _export_spec(),
    })
    names = set(_ctx(reg, [travel]).tools())
    assert "builtin.export" in names
    assert "query_my_travel_expense_list" in names


def test_export_utterance_calls_export_tool_with_previous_text():
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "chat", "tool": None, "params": {}, "chat_reply": "好的，我帮你整理一下"}
    out = oa_assistant._prefer_export(
        parsed, "把数据导出", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="姓名,金额\n张三,10",
    )
    assert out["intent"] == "tool"
    assert out["tool"] == "builtin.export"
    assert "张三,10" in out["params"]["content"]
    assert out["params"]["filename"] == "张三.xlsx"


def test_export_with_empty_model_content_fills_from_last_text():
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "tool", "tool": "builtin.export", "params": {"content": ""}}
    out = oa_assistant._prefer_export(
        parsed, "导出", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="id,amount\n1,2", last_title="列表",
    )
    assert out["intent"] == "tool"
    assert out["params"]["content"] == "id,amount\n1,2"


def test_export_with_empty_content_fills_from_attachment_chat_reply():
    """附件环路：模型调了 builtin.export 但没填 content，用本轮整理正文回填。"""
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {
        "intent": "tool",
        "tool": "builtin.export",
        "params": {},
        "chat_reply": "姓名,部门\n李四,财务",
    }
    out = oa_assistant._prefer_export(
        parsed, "整理后导出", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text=None,
    )
    assert out["intent"] == "tool"
    assert out["tool"] == "builtin.export"
    assert "李四,财务" in out["params"]["content"]


def test_export_request_uses_chat_reply_when_model_only_answered():
    """附件环路：模型只 answer 整理结果，员工要求导出时仍应落到 builtin.export。"""
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {
        "intent": "chat",
        "tool": None,
        "params": {},
        "chat_reply": "项目,金额\n差旅,1200",
    }
    out = oa_assistant._prefer_export(
        parsed, "把文件整理后导出给我", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text=None,
    )
    assert out["intent"] == "tool"
    assert out["tool"] == "builtin.export"
    assert "差旅,1200" in out["params"]["content"]


def test_attachment_empty_export_step_filled_in_chain():
    tools = {
        "query_my_travel_expense_list": (_list_spec(), None),
        "builtin.export": (_export_spec(), None),
    }
    parsed = {
        "intent": "tool",
        "tool": "query_my_travel_expense_list",
        "params": {},
        "steps": [
            {"tool": "query_my_travel_expense_list", "args": {}},
            {"tool": "builtin.export", "args": {}},
        ],
        "chat_reply": "备用正文",
    }
    out = oa_assistant._prefer_export(
        parsed, "导出", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="姓名,金额\n张三,10",
    )
    assert out["steps"][1]["tool"] == "builtin.export"
    assert "张三,10" in out["steps"][1]["args"]["content"]


def test_export_these_uses_bundle_text():
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "chat", "tool": None, "params": {}}
    out = oa_assistant._prefer_export(
        parsed, "把这些数据导出", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="a,1", bundle_text="## A\na,1\n\n## B\nb,2",
    )
    assert out["intent"] == "tool"
    assert "## B" in out["params"]["content"]
    assert "b,2" in out["params"]["content"]


def test_generic_export_defaults_to_bundle_summary():
    """未指定「这条」时，自动汇总近期多份结果再导出。"""
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "chat", "tool": None, "params": {}}
    out = oa_assistant._prefer_export(
        parsed, "导出给我", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="a,1", bundle_text="## A\na,1\n\n## B\nb,2",
    )
    assert out["intent"] == "tool"
    assert "b,2" in out["params"]["content"]


def test_send_me_a_file_triggers_export():
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "chat", "tool": None, "params": {}}
    out = oa_assistant._prefer_export(
        parsed, "给我一份表格", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="姓名,金额\n张三,10",
    )
    assert out["tool"] == "builtin.export"
    assert "张三,10" in out["params"]["content"]


def test_ensure_export_content_rescues_ask_with_attachment():
    parsed = {
        "intent": "ask",
        "tool": "builtin.export",
        "params": {},
        "missing": ["content"],
    }
    out = oa_assistant._ensure_export_content(
        parsed, "整理后导出",
        last_text=None, last_title=None, bundle_text=None,
        attachment_text="项目,金额\n差旅,88",
    )
    assert out["intent"] == "tool"
    assert "差旅,88" in out["params"]["content"]


def test_expand_export_args_fills_empty_from_all_steps():
    args = {"content": ""}
    results = [
        {"list": [{"姓名": "甲"}], "columns": [{"key": "姓名", "label": "姓名"}]},
        {"text": "备注一行"},
    ]
    out = oa_assistant._expand_export_args("builtin.export", args, results)
    assert out is not None
    assert "甲" in out["content"]
    assert "备注一行" in out["content"]


def test_export_keeps_model_query_then_export_steps():
    tools = {
        "query_my_travel_expense_list": (_list_spec(), None),
        "builtin.export": (_export_spec(), None),
    }
    parsed = {
        "intent": "tool",
        "tool": "query_my_travel_expense_list",
        "params": {},
        "steps": [
            {"tool": "query_my_travel_expense_list", "args": {}},
            {"tool": "builtin.export", "args": {"content": {"$from_step": 1}}},
        ],
    }
    out = oa_assistant._prefer_export(
        parsed, "导出报销", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text=None,
    )
    assert out["steps"][1]["tool"] == "builtin.export"
    assert out["steps"][1]["args"]["content"]["$from_step"] == 1


def test_export_this_record_uses_previous_result_not_a_new_query():
    """「将这条……导出来」指上一轮已经展示的那条，不要重新查列表。"""
    tools = {
        "query_my_travel_expense_list": (_list_spec(), None),
        "builtin.export": (_export_spec(), None),
    }
    parsed = {"intent": "chat", "tool": None, "params": {}, "chat_reply": "暂不支持导出"}
    out = oa_assistant._prefer_export(
        parsed, "将这条行程保险单给我导出来", tools, today=date(2026, 11, 5),
        rule_tool_map={LIST: "query_my_travel_expense_list"},
        last_text="单号,3843\n金额,5.00",
    )
    assert out["intent"] == "tool"
    assert out["tool"] == "builtin.export"
    assert "3843" in out["params"]["content"]
    assert out["params"]["filename"] == "3843.xlsx"
    assert "steps" not in out


def test_export_plus_query_chains_list_then_export():
    tools = {
        "query_my_travel_expense_list": (_list_spec(), None),
        "builtin.export": (_export_spec(), None),
    }
    parsed = {"intent": "chat", "tool": None, "params": {}, "chat_reply": "请稍等"}
    out = oa_assistant._prefer_export(
        parsed, "导出本月的报销", tools, today=date(2026, 11, 5),
        rule_tool_map={LIST: "query_my_travel_expense_list"}, last_text=None,
    )
    assert out["intent"] == "tool"
    assert out["tool"] == "query_my_travel_expense_list"
    assert out["steps"][1]["tool"] == "builtin.export"
    assert out["steps"][1]["args"]["content"]["$from_step"] == 1
    assert out["steps"][1]["args"]["_title"] == "行程报销列表"
    assert "filename" not in out["steps"][1]["args"]
    assert out["params"]["date_gte"] == "2026-11-01"


def test_user_named_file_is_kept():
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "chat", "tool": None, "params": {}, "chat_reply": "好"}
    out = oa_assistant._prefer_export(
        parsed, "导出为会议纪要", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="姓名,金额\n张三,10", last_title="行程报销列表",
    )
    assert out["params"]["filename"] == "会议纪要.xlsx"


def test_title_and_record_id_make_the_filename():
    tools = {"builtin.export": (_export_spec(), None)}
    parsed = {"intent": "chat", "tool": None, "params": {}, "chat_reply": "好"}
    out = oa_assistant._prefer_export(
        parsed, "把这条导出来", tools, today=date(2026, 11, 5), rule_tool_map={},
        last_text="单号,3843\n金额,5.00", last_title="行程报销",
    )
    assert out["params"]["filename"] == "行程报销-3843.xlsx"


def test_call_tool_names_chained_export_from_query_title():
    spec = _export_spec()

    class _Exec:
        registry = _Reg({"builtin.export": spec})

        def execute(self, name, args, identity, rec, node):
            return {"ok": True, "capability": name, "data": {"text": "ok"}, "message": ""}

    ctx = _ctx(_Exec.registry, [])
    ctx.executor = _Exec()
    state = {
        "steps": [
            {"tool": "query_my_travel_expense_list", "args": {}},
            {"tool": "builtin.export", "args": {"content": {"$from_step": 1}, "_title": "行程报销列表"}},
        ],
        "step_index": 1,
        "step_results": [{"list": [{"id": 7, "amount": 3}, {"id": 8, "amount": 4}], "total": 2}],
        "intent": "tool",
    }
    seen = oa_assistant._expand_export_args(
        "builtin.export", state["steps"][1]["args"], state["step_results"],
    )
    assert seen["filename"] == "行程报销列表.xlsx"
    assert "_title" not in seen


def test_call_tool_fills_export_content_from_previous_step():
    spec = _export_spec()
    seen: list[tuple[str, dict]] = []

    class _Exec:
        registry = _Reg({"builtin.export": spec})

        def execute(self, name, args, identity, rec, node):
            seen.append((name, dict(args)))
            return {"ok": True, "capability": name, "data": {"text": "ok"}, "message": ""}

    ctx = _ctx(_Exec.registry, [])
    ctx.executor = _Exec()
    state = {
        "steps": [
            {"tool": "query_my_travel_expense_list", "args": {}},
            {"tool": "builtin.export", "args": {"content": {"$from_step": 1}, "filename": "导出.csv"}},
        ],
        "step_index": 1,
        "step_results": [{"list": [{"id": 7, "amount": 3}], "total": 1}],
        "intent": "tool",
    }
    oa_assistant.call_tool(state, ctx)
    assert seen[0][0] == "builtin.export"
    assert "7" in seen[0][1]["content"] and "amount" in seen[0][1]["content"]


def test_export_reply_exposes_download_ticket_not_fence():
    from oa_agent.security.prompt_guard import wrap_untrusted

    spec = _export_spec()
    body = wrap_untrusted(
        '{"ticket": "abcdefghijklmnopqrst", "filename": "报销.csv", "expires_in": 3600, "size_bytes": 4}',
        source="builtin", name="builtin.export",
    )
    reply = oa_assistant._file_reply(spec, "导出文件", {"text": body})
    assert reply["data"]["kind"] == "file"
    assert reply["data"]["ticket"] == "abcdefghijklmnopqrst"
    assert reply["data"]["filename"] == "报销.csv"
    assert reply["content"] == "已生成文件 **报销.csv**，可下载。"
    assert "一次" not in reply["content"]
    assert "秒内" not in reply["content"]
    assert "UNTRUSTED_DATA" not in reply["content"]
    assert "abcdefghijklmnopqrst" not in reply["content"]


def test_take_export_is_owner_only_and_repeatable(tmp_path, installed):
    """本人可反复下载；他人票据拿不到；登记行与对象都不删除。"""
    import sqlalchemy as sa

    from oa_agent.db.models import ExportFile
    from oa_agent.executor.builtin_runtime import BuiltinRuntime
    from oa_agent.executor.executor import Identity

    rt = installed.app.state.runtime
    runtime = BuiltinRuntime(tenant_id=rt.tenant_id, session_factory=rt.session, data_dir=tmp_path)
    out = runtime.call(
        _export_spec(),
        {"filename": "报销.xlsx", "content": "id,amount\n7,3\n"},
        identity=Identity(oa="alice", authorization="", thread_id="thr_alice", run_id="run_alice"),
    )
    ticket = out["ticket"]
    assert out["filename"].endswith(".xlsx")
    assert str(out.get("file_id") or "").startswith("exp_")
    assert "expires_in" not in out and "expires_at" not in out
    assert runtime.take_export(ticket, "bob") is None
    taken = runtime.take_export(ticket, "alice")
    assert taken is not None and taken[1] == "报销.xlsx"
    assert taken[0][:2] == b"PK" and b"7" in taken[0] and b"3" in taken[0]
    again = runtime.take_export(ticket, "alice")
    assert again is not None and again[0] == taken[0] and again[1] == taken[1]
    blob = tmp_path / "exports" / rt.tenant_id / f"{ticket}.bin"
    assert blob.is_file()
    assert not list((tmp_path / "exports").rglob("*.json"))
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.ticket == ticket))
    assert row is not None
    assert row.oa == "alice" and row.thread_id == "thr_alice" and row.run_id == "run_alice"
    assert row.file_id == out["file_id"] and row.storage == "local"
    assert row.object_key == f"{rt.tenant_id}/{ticket}.bin"
    assert "://" not in row.object_key
    assert row.content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert row.size_bytes == len(taken[0])
