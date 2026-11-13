"""行程报销只读 harness：OpenAPI ↔ Skill ↔ 请求拼装（不扩 bindable/confirm/写接口）。"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import yaml

from oa_agent.executor.catalog import parse_openapi
from oa_agent.executor.executor import ToolError, validate_args
from oa_agent.executor.registry import ToolRegistry
from oa_agent.executor.tool_routing import FALLBACK_RULE_TOOLS
from oa_agent.integrations.open_oa import employee_facing_error
from oa_agent.runtime import intent_rules
from oa_agent.runtime.graphs import travel_query as tq
from oa_agent.runtime.intent_rules import DETAIL as INTENT_DETAIL
from oa_agent.runtime.intent_rules import LIST as INTENT_LIST
from oa_agent.settings import REPO_ROOT
from tests.test_chat import INVOKE_URL, chat, office, open_chat, send  # noqa: F401

OPENAPI = REPO_ROOT / "openapi" / "travel_expense.yaml"
SKILL = REPO_ROOT / "skills" / "travel_expense_query.yaml"

LIST = "query_my_travel_expense_list"
DETAIL = "query_my_travel_expense_detail"
READ_TOOLS = frozenset({LIST, DETAIL})


def test_openapi_exposes_only_two_read_tools():
    _, ops = parse_openapi(OPENAPI)
    enabled = {name for name, spec in ops.items() if spec["spec_enabled"]}
    assert enabled == READ_TOOLS
    assert ops[LIST]["path"] == "/agent/invoke"
    assert ops[DETAIL]["path"] == "/agent/invoke"
    assert ops[LIST]["invoke_service"] == "out_attendance/go_out_application"
    assert ops[LIST]["invoke_method"] == "getTravelExpensePageList"
    assert ops[DETAIL]["invoke_method"] == "getTravelExpenseOneByParams"
    assert "oa" not in ops[LIST]["model_params"]
    assert "oa" not in ops[DETAIL]["model_params"]


def test_skill_wires_same_two_tools():
    doc = yaml.safe_load(SKILL.read_text(encoding="utf-8"))
    assert doc["enabled"] is True
    assert set(doc["tools"]) == READ_TOOLS


def test_fallback_rule_tools_map_list_and_detail():
    assert FALLBACK_RULE_TOOLS[INTENT_LIST] == LIST
    assert FALLBACK_RULE_TOOLS[INTENT_DETAIL] == DETAIL


def test_registry_loads_open_oa_invoke_tools():
    reg = ToolRegistry.load()
    assert set(reg.names()) == READ_TOOLS
    list_spec = reg.get(LIST)
    detail_spec = reg.get(DETAIL)
    assert list_spec.kind == "open_oa_invoke"
    assert detail_spec.kind == "open_oa_invoke"
    assert list_spec.path == "/agent/invoke"
    assert list_spec.invoke_service == "out_attendance/go_out_application"
    clean, dropped = validate_args(list_spec, {"oa": "evil", "page": 2, "limit": 5, "date_gte": "2026-09-01"})
    assert "oa" in dropped
    assert clean["page"] == 2 and clean["limit"] == 5 and clean["date_gte"] == "2026-09-01"
    detail_clean, _ = validate_args(detail_spec, {"id": 42})
    assert detail_clean == {"id": 42}


def test_skill_instructions_require_id_before_detail():
    doc = yaml.safe_load(SKILL.read_text(encoding="utf-8"))
    assert "单号" in doc["instructions"] and "追问" in doc["instructions"]


def test_intent_detail_without_id_does_not_fall_back_to_list():
    parsed = intent_rules.parse("查看报销单的详情", date(2026, 11, 5))
    assert parsed == {"intent": "detail", "params": {}}


def test_detail_without_id_asks_instead_of_calling_tool(chat, office):
    route = office.post(INVOKE_URL)
    h = open_chat(chat)
    body = send(chat, h, "查看报销单的详情").json()
    assert body["run_status"] == "waiting_input"
    content = body["reply"]["content"]
    assert "单号" in content
    assert "查询" not in content or content.count("查询") <= 1
    assert "查询行程报销查询" not in content
    assert not route.called


def test_ask_reply_has_no_duplicated_query_prefix():
    reg = ToolRegistry.load()
    spec = reg.get(DETAIL)
    reply = tq._ask_reply(spec, None, ["id"])
    assert reply["content"] == "请提供 **单号** 后再问我一次。"
    assert "查询行程报销" not in reply["content"]


def test_last_week_on_thursday_2026_11_05():
    thu = date(2026, 11, 5)
    parsed = intent_rules.parse("查上周的行程报销", thu)
    assert (parsed["params"]["date_gte"], parsed["params"]["date_lte"]) == ("2026-10-26", "2026-11-01")


def test_understand_overrides_llm_wrong_last_week_dates(monkeypatch, chat, office):
    """模型填错「上周」区间时，仍以规则（Asia/Shanghai 日历周）为准。"""
    from tests.test_agent_chat import ScriptedModel, use_model

    wrong = {
        "action": "tool",
        "tool": LIST,
        "args": {"date_gte": "2026-10-19", "date_lte": "2026-10-25"},
    }
    route = office.post(INVOKE_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}}),
    )
    use_model(monkeypatch, [wrong])
    h = open_chat(chat)
    body = send(chat, h, "查上周的行程报销").json()
    assert body["run_status"] == "succeeded"
    from tests.test_chat import china_today, last_week

    payload = json.loads(route.calls.last.request.content.decode())
    assert payload["service"] == "out_attendance/go_out_application"
    assert payload["method"] == "getTravelExpensePageList"
    gte, lte = last_week(china_today())
    assert payload["args"]["date_gte"] == gte and payload["args"]["date_lte"] == lte


def test_validate_args_rejects_detail_without_id():
    spec = ToolRegistry.load().get(DETAIL)
    with pytest.raises(ToolError) as err:
        validate_args(spec, {})
    assert err.value.code == "INVALID_ARGUMENT"


def test_rules_understand_asks_for_missing_detail_id():
    reg = ToolRegistry.load()
    tools = {DETAIL: (reg.get(DETAIL), None)}
    parsed = tq._rules("查看报销单的详情", date(2026, 11, 5), tools)
    assert parsed["intent"] == tq.TOOL and parsed["tool"] == DETAIL
    coerced = tq._coerce_tool_required_params(parsed, tools)
    assert coerced["intent"] == tq.ASK and coerced["missing"] == ["id"]


def test_employee_facing_error_maps_vague_biz_failure():
    assert employee_facing_error("UPSTREAM_BIZ_ERROR", hint="请求失败") == "查询失败，请稍后再试。"
    assert employee_facing_error("UPSTREAM_BIZ_ERROR", hint="报销单不存在") == "未找到该报销单，请核对单号是否正确。"
    assert employee_facing_error("UPSTREAM_BIZ_ERROR", hint="暂无权限查看") == "你没有权限查看该报销单。"
    assert employee_facing_error("UPSTREAM_BIZ_ERROR", hint="财年未开放") is None


def test_detail_not_found_shows_distinct_copy(chat, office):
    office.post(INVOKE_URL).mock(
        return_value=httpx.Response(200, json={"code": 1, "msg": "请求失败", "data": None}),
    )
    h = open_chat(chat)
    body = send(chat, h, "查看报销单 999999 的详情").json()
    assert body["run_status"] == "failed"
    assert body["reply"]["content"] == "查询失败，请稍后再试。"
    assert body["reply"]["error_code"] == "UPSTREAM_BIZ_ERROR"
