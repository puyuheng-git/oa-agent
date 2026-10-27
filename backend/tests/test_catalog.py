"""P4 验收：未 enabled 不注册；同步失败不覆盖；停用即拒绝调用；兼容性检测；Skill 依赖校验"""

from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from oa_agent.executor.catalog import BREAKING, COMPATIBLE, SpecError, compare, parse_openapi
from oa_agent.runtime.graphs import travel_query, oa_assistant
from oa_agent.settings import REPO_ROOT
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_chat import LIST_URL, ROW, chat, office, open_chat, runtime, send  # noqa: F401

SPEC = REPO_ROOT / "openapi" / "travel_expense.yaml"
LIST_TOOL = "query_my_travel_expense_list"
DETAIL_TOOL = "query_my_travel_expense_detail"


@pytest.fixture
def spec_dir(admin, tmp_path) -> Path:
    """把引擎的 OpenAPI 目录指向可修改的副本"""
    d = tmp_path / "openapi"
    d.mkdir()
    shutil.copy(SPEC, d / SPEC.name)
    runtime(admin.client).engine.catalog.openapi_dir = d
    return d


def load_doc(spec_dir: Path) -> dict:
    return yaml.safe_load((spec_dir / SPEC.name).read_text(encoding="utf-8"))


def save_doc(spec_dir: Path, doc: dict) -> None:
    (spec_dir / SPEC.name).write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def list_op(doc: dict) -> dict:
    return doc["paths"]["/out_attendance/go_out_travel_expense/index"]["get"]


def tools_by_name(admin) -> dict:
    """OpenAPI（office）Tool；启动时 upsert 的 builtin.* 内置工具不在此列。"""
    r = admin.get("/v1/admin/tools?kind=office")
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["items"]}


def test_boot_sync_registers_tools_and_skill(admin):
    tools = tools_by_name(admin)
    assert set(tools) == {LIST_TOOL, DETAIL_TOOL}
    assert all(t["registered"] and t["current_version_no"] == 1 for t in tools.values())
    skills = admin.get("/v1/admin/skills").json()["items"]
    assert skills[0]["name"] == "travel_expense_query" and skills[0]["validation_status"] == "valid"
    assert runtime(admin.client).engine.registry.get(LIST_TOOL).version == "1.0.0#v1"


def test_list_tools_serializes_kind_and_filters(admin):
    from oa_agent.db.models import Tool

    rt = runtime(admin.client)
    with rt.session() as db, db.begin():
        db.add(Tool(tenant_id=rt.tenant_id, name="_kind_builtin", kind="builtin", builtin_id="calc",
                    summary="内置", enabled=True))
    all_items = admin.get("/v1/admin/tools").json()["items"]
    assert all("kind" in t for t in all_items)
    assert {t["kind"] for t in all_items} >= {"office", "builtin"}

    office_items = admin.get("/v1/admin/tools?kind=office").json()["items"]
    assert office_items and {t["kind"] for t in office_items} == {"office"}
    assert {t["name"] for t in office_items} == {LIST_TOOL, DETAIL_TOOL}

    builtin_items = admin.get("/v1/admin/tools?kind=builtin").json()["items"]
    names = {t["name"] for t in builtin_items}
    assert "_kind_builtin" in names and "builtin.time" in names  # 启动 upsert 的内置工具也在列
    assert admin.get("/v1/admin/tools?kind=mcp").json()["items"] == []
    assert admin.get("/v1/admin/tools?kind=bogus").status_code == 422


def test_spec_validation_rejects_identity_params(tmp_path):
    doc = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    list_op(doc)["x-agent"]["model_params"]["oa"] = {"type": "string"}
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SpecError) as err:
        parse_openapi(bad)
    assert any("身份字段" in e for e in err.value.errors)


def test_not_enabled_or_high_risk_not_registered(admin, spec_dir):
    doc = load_doc(spec_dir)
    list_op(doc)["x-agent"]["enabled"] = False
    detail = doc["paths"]["/out_attendance/go_out_travel_expense/detail"]["get"]
    detail["x-agent"]["risk_level"] = "high"
    save_doc(spec_dir, doc)
    report = admin.post("/v1/admin/tools/sync").json()
    results = {t["name"]: t for t in report["tools"]}
    assert results[DETAIL_TOOL]["result"] == "breaking_pending"  # 风险等级变化属于不兼"
    tools = tools_by_name(admin)
    assert tools[LIST_TOOL]["registered"] is False and "规范未启" in tools[LIST_TOOL]["unregistered_reasons"][0]
    # 激活高风险版本后也不注"
    r = admin.post(f"/v1/admin/tools/{DETAIL_TOOL}/activate", json={"version_no": 2, "reason": "接受高风险定"})
    assert r.status_code == 200, r.text
    assert r.json()["registered"] is False and r.json()["risk_level"] == "high"
    skill = admin.get("/v1/admin/skills/travel_expense_query").json()
    assert skill["validation_status"] == "invalid"


def test_compatible_change_auto_activates_and_breaking_waits(admin, spec_dir):
    doc = load_doc(spec_dir)
    list_op(doc)["x-agent"]["model_params"]["keyword"] = {"type": "string"}
    list_op(doc)["x-agent"]["result"]["fields"].append("project_name")
    save_doc(spec_dir, doc)
    report = admin.post("/v1/admin/tools/sync").json()
    assert {t["name"]: t["result"] for t in report["tools"]}[LIST_TOOL] == COMPATIBLE
    assert tools_by_name(admin)[LIST_TOOL]["current_version_no"] == 2
    assert runtime(admin.client).engine.registry.get(LIST_TOOL).model_params.get("keyword") is not None

    del list_op(doc)["x-agent"]["model_params"]["status"]
    save_doc(spec_dir, doc)
    admin.post("/v1/admin/tools/sync")
    tool = tools_by_name(admin)[LIST_TOOL]
    assert tool["current_version_no"] == 2 and tool["pending_version_no"] == 3 and tool["pending_compat"] == BREAKING
    assert "status" in runtime(admin.client).engine.registry.get(LIST_TOOL).model_params, "不兼容版本未激活前不生"

    diff = admin.get(f"/v1/admin/tools/{LIST_TOOL}/diff", params={"from_no": 2, "to_no": 3}).json()
    assert diff["compat_level"] == BREAKING
    assert any(c["field"] == "model_params.status" and c["change"] == "removed" for c in diff["changes"])

    r = admin.post(f"/v1/admin/tools/{LIST_TOOL}/activate", json={"version_no": 3, "reason": "OA 已下线该参数"})
    assert r.status_code == 200 and r.json()["current_version_no"] == 3 and r.json()["pending_version_no"] is None
    assert "status" not in runtime(admin.client).engine.registry.get(LIST_TOOL).model_params
    # 回退到历史版"
    r = admin.post(f"/v1/admin/tools/{LIST_TOOL}/activate", json={"version_no": 1, "reason": "回退"})
    assert r.json()["current_version_no"] == 1
    actions = [a["action"] for a in audit_rows(admin)]
    assert "tool.sync" in actions and "tool.activate" in actions


def test_sync_failure_keeps_last_valid_version(admin, spec_dir):
    (spec_dir / SPEC.name).write_text("paths: [broken", encoding="utf-8")
    report = admin.post("/v1/admin/tools/sync").json()
    assert report["files"][0]["ok"] is False
    tools = tools_by_name(admin)
    assert all(t["last_sync_result"] == "error" and t["current_version_no"] == 1 and t["registered"]
               for t in tools.values())


def test_removed_operation_is_unregistered(admin, spec_dir):
    doc = load_doc(spec_dir)
    del doc["paths"]["/out_attendance/go_out_travel_expense/detail"]
    save_doc(spec_dir, doc)
    report = admin.post("/v1/admin/tools/sync").json()
    assert {t["name"]: t["result"] for t in report["tools"]}[DETAIL_TOOL] == "removed"
    assert tools_by_name(admin)[DETAIL_TOOL]["registered"] is False


def test_disable_tool_rejects_calls_immediately(chat, office, admin):
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW]}}))
    h = open_chat(chat)
    r = admin.post(f"/v1/admin/tools/{LIST_TOOL}/disable", json={"reason": "OA 接口维护"})
    assert r.status_code == 200 and r.json()["registered"] is False
    body = send(chat, h, "查上周的行程报销").json()
    assert body["run_status"] == "failed" and body["reply"]["error_code"] == "SKILL_DISABLED"
    assert route.call_count == 0

    admin.post(f"/v1/admin/tools/{LIST_TOOL}/enable", json={"reason": "维护结束"})
    assert send(chat, h, "查上周的行程报销").json()["run_status"] == "succeeded"

    admin.post("/v1/admin/skills/travel_expense_query/disable", json={"reason": "暂停功能"})
    body = send(chat, h, "查上周的行程报销").json()
    assert body["reply"]["error_code"] == "SKILL_DISABLED" and route.call_count == 1
    assert any(a["action"] == "skill.disable" for a in audit_rows(admin))


def test_tool_disabled_mid_run_is_refused(chat, office, admin, monkeypatch):
    """运行已开始（已选定 Tool）后 Tool 被停用：执行器按最新注册表拒绝调用"""
    rt = runtime(chat)
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": []}}))
    original = oa_assistant._rules

    def rules_then_disable(*args):
        out = original(*args)
        rt.engine.registry = type(rt.engine.registry)({})
        return out

    monkeypatch.setattr(oa_assistant, "_rules", rules_then_disable)
    body = send(chat, open_chat(chat), "查上周的行程报销").json()
    assert body["reply"]["error_code"] == "TOOL_NOT_AVAILABLE" and route.call_count == 0


def test_catalog_requires_permissions(admin, installed):
    role = _role(admin, "run_only", ["ops.run.view"])
    _user(admin, "runonly", [role["id"]])
    other = login(TestClient(installed.app), "runonly", VIEWER_PASS)
    assert other.get("/v1/admin/tools").status_code == 403
    assert other.post("/v1/admin/tools/sync").status_code == 403
    assert other.post(f"/v1/admin/tools/{LIST_TOOL}/disable", json={"reason": "越权"}).status_code == 403
    assert other.get("/v1/admin/skills").status_code == 403
    assert tools_by_name(admin)[LIST_TOOL]["enabled"] is True


def test_compare_rules():
    base = {"method": "GET", "path": "/x", "model_params": {"a": {"type": "integer", "enum": [0, 1]}},
            "result": {"kind": "list", "fields": ["id"]}}
    widened = {**base, "model_params": {"a": {"type": "integer", "enum": [0, 1, 2]}}}
    narrowed = {**base, "model_params": {"a": {"type": "integer", "enum": [0]}}}
    required_new = {**base, "model_params": {**base["model_params"], "b": {"type": "string", "required": True}}}
    assert compare(base, widened)[0] == COMPATIBLE
    assert compare(base, narrowed)[0] == BREAKING
    assert compare(base, required_new)[0] == BREAKING
    assert compare(base, {**base, "path": "/y"})[0] == BREAKING
