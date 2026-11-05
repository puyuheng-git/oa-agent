"""行程报销只读 harness：OpenAPI ↔ Skill ↔ Pack ↔ 请求拼装（不扩 bindable/confirm/写接口）。"""

from __future__ import annotations

import json

import yaml

from oa_agent.executor.catalog import parse_openapi
from oa_agent.executor.executor import Identity, build_request, validate_args
from oa_agent.executor.registry import ToolRegistry
from oa_agent.packs.registry import PackRegistry
from oa_agent.settings import REPO_ROOT

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
