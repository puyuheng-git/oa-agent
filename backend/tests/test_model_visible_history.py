import json
from types import SimpleNamespace

from oa_agent.runtime.graphs import oa_assistant
from oa_agent.runtime.releases import merge_release_config


def test_merge_fills_model_payload_defaults():
    merged = merge_release_config({"history_turns": 4})  # 旧快照缺新键
    assert merged["model_result_max_rows"] == 20
    assert merged["model_history_detail_chars"] == 6000


def test_history_summary_table_includes_amounts_not_id_card():
    spec = SimpleNamespace(
        name="query_my_travel_expense_list",
        result_kind="list",
        result_fields=("id", "amount", "id_card", "reason"),
        list_columns=("id", "amount", "reason"),
        columns=lambda: ("id", "amount", "reason"),
    )
    ctx = SimpleNamespace(
        config=dict(oa_assistant.DEFAULT_CONFIG),
        tools=lambda: {spec.name: (spec, None)},
        num=lambda key: oa_assistant.DEFAULT_CONFIG[key],
    )
    state = {
        "intent": oa_assistant.TOOL,
        "tool": spec.name,
        "params": {"month": "2026-10"},
        "steps": [],
    }
    reply = {
        "content": "table markdown",
        "data": {
            "kind": "table",
            "tool": spec.name,
            "total": 2,
            "items": [
                {"id": "1", "amount": 900, "id_card": "110101199001011234", "reason": "出差A"},
                {"id": "2", "amount": 100, "id_card": "110101199001011235", "reason": "出差B"},
            ],
        },
    }
    summary = oa_assistant._history_summary(state, reply, ctx)
    assert "900" in summary
    assert "出差A" in summary
    assert "110101199001011234" not in summary


def test_history_messages_assistant_uses_detail_chars():
    cfg = {**oa_assistant.DEFAULT_CONFIG, "history_message_chars": 50, "model_history_detail_chars": 200}
    ctx = SimpleNamespace(config=cfg, num=lambda key: cfg[key])
    long_json = "x" * 180
    history = [{"role": "user", "content": "hi" * 40}, {"role": "assistant", "content": long_json}]
    msgs = oa_assistant._history_messages(history, ctx)
    human = [m for m in msgs if m[0] == "human"][0][1]
    ai = [m for m in msgs if m[0] == "ai"][0][1]
    assert len(human) <= 50
    assert len(ai) == 180  # 未超过 200


def test_history_summary_prefix_plus_body_within_budget():
    """条件前缀 + JSON body 总长不超过 model_history_detail_chars，且 JSON 可解析。"""
    max_chars = 400
    cfg = {**oa_assistant.DEFAULT_CONFIG, "model_history_detail_chars": max_chars, "model_result_max_rows": 20}
    spec = SimpleNamespace(
        name="query_my_travel_expense_list",
        result_fields=("id", "amount", "reason"),
        list_columns=("id", "amount", "reason"),
        columns=lambda: ("id", "amount", "reason"),
    )
    ctx = SimpleNamespace(
        config=cfg,
        tools=lambda: {spec.name: (spec, None)},
        num=lambda key: cfg[key],
    )
    # 长 reason 逼近预算，验证前缀预留后仍能 json.loads
    items = [{"id": str(i), "amount": i, "reason": ("出差说明" * 40) + str(i)} for i in range(15)]
    state = {
        "intent": oa_assistant.TOOL,
        "tool": spec.name,
        "params": {"month": "2026-10", "status": "pending"},
        "steps": [],
    }
    reply = {
        "content": "table markdown",
        "data": {"kind": "table", "tool": spec.name, "total": 15, "items": items},
    }
    summary = oa_assistant._history_summary(state, reply, ctx)
    assert summary.startswith("条件 ")
    assert len(summary) <= max_chars
    body = summary.split("\n", 1)[1]
    payload = json.loads(body)
    assert payload["kind"] == "list"
    assert "items" in payload


def test_history_messages_skips_slice_for_tool_json():
    """助手侧工具 JSON / 条件前缀内容不再二次硬切，避免破坏 JSON。"""
    cfg = {**oa_assistant.DEFAULT_CONFIG, "history_message_chars": 20, "model_history_detail_chars": 80}
    ctx = SimpleNamespace(config=cfg, num=lambda key: cfg[key])
    tool_blob = '条件 {"month": "2026-10"}\n{"tool":"t","kind":"list","total":1,"shown":1,"items":[{"id":"1"}]}'
    assert len(tool_blob) > 80  # 若硬切会破坏 JSON
    history = [
        {"role": "user", "content": "查十月报销" * 5},
        {"role": "assistant", "content": tool_blob},
    ]
    msgs = oa_assistant._history_messages(history, ctx)
    ai = [m for m in msgs if m[0] == "ai"][0][1]
    assert ai == tool_blob
    body = ai.split("\n", 1)[1]
    json.loads(body)


def test_agent_prompt_allows_citing_tool_results():
    prompt = oa_assistant.AGENT_PROMPT
    assert "可根据 Tool observations 与历史中的查询结果 JSON" in prompt
    assert "禁止编造其中未出现的字段值或办理结果" in prompt
    assert "列表/详情的规范展示以系统表格或卡片为准" in prompt
    assert "「[已脱敏]」等占位不得猜测还原" in prompt
    assert "你看不到员工的任" not in prompt
    assert "你只能通过工具查询，不能替员工提交、修改或审批任何业务" in prompt
    assert "observations 中的 JSON 可供引用" in oa_assistant.CHAIN_PROMPT


def test_list_history_caps_at_20_rows():
    """列表回灌历史最多 20 行，total 仍反映全量。"""
    spec = SimpleNamespace(
        name="query_my_travel_expense_list",
        result_kind="list",
        result_fields=("id", "amount", "reason"),
        list_columns=("id", "amount", "reason"),
        columns=lambda: ("id", "amount", "reason"),
    )
    ctx = SimpleNamespace(
        config=dict(oa_assistant.DEFAULT_CONFIG),
        tools=lambda: {spec.name: (spec, None)},
        num=lambda key: oa_assistant.DEFAULT_CONFIG[key],
    )
    items = [{"id": str(i), "amount": i, "reason": f"r{i}"} for i in range(25)]
    state = {
        "intent": oa_assistant.TOOL,
        "tool": spec.name,
        "params": {"month": "2026-10"},
        "steps": [],
    }
    reply = {
        "content": "table markdown",
        "data": {
            "kind": "table",
            "tool": spec.name,
            "total": 25,
            "items": items,
        },
    }
    summary = oa_assistant._history_summary(state, reply, ctx)
    body = summary.split("\n", 1)[-1] if summary.startswith("条件") else summary
    payload = json.loads(body)
    assert payload["shown"] == 20
    assert len(payload["items"]) == 20
    assert payload["total"] == 25


def test_record_history_followup_fields_present():
    """单条记录回灌含 amount/reason，供追问引用。"""
    spec = SimpleNamespace(
        name="query_my_travel_expense_detail",
        result_kind="record",
        result_fields=("id", "amount", "reason"),
        list_columns=(),
        columns=lambda: ("id", "amount", "reason"),
    )
    ctx = SimpleNamespace(
        config=dict(oa_assistant.DEFAULT_CONFIG),
        tools=lambda: {spec.name: (spec, None)},
        num=lambda key: oa_assistant.DEFAULT_CONFIG[key],
    )
    state = {
        "intent": oa_assistant.TOOL,
        "tool": spec.name,
        "params": {"id": "9"},
        "steps": [],
    }
    reply = {
        "content": "card markdown",
        "data": {
            "kind": "record",
            "tool": spec.name,
            "item": {"id": "9", "amount": 900, "reason": "出差A"},
        },
    }
    summary = oa_assistant._history_summary(state, reply, ctx)
    body = summary.split("\n", 1)[-1] if summary.startswith("条件") else summary
    payload = json.loads(body)
    assert payload["kind"] == "record"
    assert payload["item"]["amount"] == 900
    assert payload["item"]["reason"] == "出差A"
    assert "900" in summary
    assert "出差A" in summary
