"""行程报销只读 harness：OpenAPI ↔ Skill ↔ Pack ↔ 请求拼装（不扩 bindable/confirm/写接口）。"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
import yaml

from oa_agent.executor.catalog import parse_openapi
from oa_agent.executor.executor import Identity, ToolError, build_request, validate_args
from oa_agent.executor.registry import ToolRegistry
from oa_agent.integrations.office_api import employee_facing_error
from oa_agent.packs.registry import PackRegistry
from oa_agent.runtime import intent_rules
from oa_agent.runtime.graphs import travel_query as tq
from oa_agent.settings import REPO_ROOT
from tests.test_chat import DETAIL_URL, chat, office, open_chat, send  # noqa: F401

OPENAPI = REPO_ROOT / "openapi" / "travel_expense.yaml"
SKILL = REPO_ROOT / "skills" / "travel_expense_query.yaml"
PACKS = REPO_ROOT / "packs"

LIST = "query_my_travel_expense_list"
DETAIL = "query_my_travel_expense_detail"
READ_TOOLS = frozenset({LIST, DETAIL})


def test_openapi_exposes_only_two_read_tools():
    _, ops = parse_openapi(OPENAPI)
    enabled = {name for name, spec in ops.items() if spec["spec_enabled"]}
    assert enabled == READ_TOOLS
    assert ops[LIST]["path"] == "/out_attendance/go_out_travel_expense/index"
    assert ops[DETAIL]["path"] == "/out_attendance/go_out_travel_expense/detail"
    assert "oa" not in ops[LIST]["model_params"]
    assert "oa" not in ops[DETAIL]["model_params"]


def test_skill_wires_same_two_tools():
    doc = yaml.safe_load(SKILL.read_text(encoding="utf-8"))
    assert doc["enabled"] is True
    assert set(doc["tools"]) == READ_TOOLS


def test_oa_travel_pack_aggregates_list_and_detail_rules():
    registry = PackRegistry.from_disk(PACKS, disabled_ids=[])
    assert registry.is_enabled("oa_travel")
    assert set(registry.owned_tool_names("oa_travel")) == READ_TOOLS
    rules = registry.aggregated_rule_tools()
    assert rules["list"] == LIST and rules["detail"] == DETAIL


def test_registry_and_build_request_match_office_api_shape():
    reg = ToolRegistry.load()
    assert set(reg.names()) == READ_TOOLS
    list_spec = reg.get(LIST)
    detail_spec = reg.get(DETAIL)
    clean, dropped = validate_args(list_spec, {"oa": "evil", "page": 2, "limit": 5, "date_gte": "2026-09-01"})
    assert "oa" in dropped
    params = build_request(list_spec, clean, Identity(oa="zhangsan", authorization="tok"))
    assert params["page"] == 2 and params["limit"] == 5
    qp = json.loads(params["queryParams"])
    assert qp == {"date_gte": "2026-09-01", "oa": "zhangsan"}

    detail_clean, _ = validate_args(detail_spec, {"id": 42})
    detail_params = build_request(detail_spec, detail_clean, Identity(oa="zhangsan", authorization="tok"))
    assert json.loads(detail_params["queryParams"]) == {"id": 42, "oa": "zhangsan"}


def test_skill_instructions_require_id_before_detail():
    doc = yaml.safe_load(SKILL.read_text(encoding="utf-8"))
    assert "单号" in doc["instructions"] and "追问" in doc["instructions"]


def test_intent_detail_without_id_does_not_fall_back_to_list():
    parsed = intent_rules.parse("查看报销单的详情", date(2026, 11, 5))
    assert parsed == {"intent": "detail", "params": {}}


def test_detail_without_id_asks_instead_of_calling_tool(chat, office):
    route = office.get(DETAIL_URL)
    h = open_chat(chat)
    body = send(chat, h, "查看报销单的详情").json()
    assert body["run_status"] == "succeeded"
    assert "单号" in body["reply"]["content"]
    assert not route.called


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
    office.get(DETAIL_URL).mock(
        return_value=httpx.Response(200, json={"code": 1, "msg": "请求失败", "data": None}),
    )
    h = open_chat(chat)
    body = send(chat, h, "查看报销单 999999 的详情").json()
    assert body["run_status"] == "failed"
    assert body["reply"]["content"] == "查询失败，请稍后再试。"
    assert body["reply"]["error_code"] == "UPSTREAM_BIZ_ERROR"
