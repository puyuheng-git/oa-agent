"""后台新建/编辑 Tool 与 Skill：校验、版本规则、审计，以及新 Tool 无需改代码即可被对话使用。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from oa_agent.runtime.llm import ModelConfig
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_chat import OFFICE, chat, make_assertion, office, open_chat, runtime, send  # noqa: F401

LEAVE_URL = f"{OFFICE}/hr/leave/index"

LEAVE_TOOL = {
    "name": "query_my_leave_list",
    "summary": "查询本人请假记录",
    "description": "按日期区间查询员工本人的请假单",
    "path": "/hr/leave/index",
    "inject_identity_fields": ["oa"],
    "top_level_fields": ["limit"],
    "query_params_field": "queryParams",
    "model_params": {
        "date_gte": {"type": "string", "format": "date", "label": "开始日期"},
        "leave_type": {"type": "integer", "enum": [1, 2], "label": "假期类型", "enum_labels": {"1": "年假", "2": "病假"}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10, "label": "条数"},
    },
    "result": {"kind": "list", "fields": ["id", "start_date", "days", "leave_type_text"],
               "labels": {"id": "单号", "start_date": "开始日期", "days": "天数", "leave_type_text": "类型"},
               "list_columns": ["start_date", "days", "leave_type_text"]},
    "reason": "新增请假查询",
}

LEAVE_SKILL = {
    "name": "leave_query",
    "display_name": "请假查询",
    "description": "查询员工本人的请假记录",
    "instructions": "年假对应 leave_type=1",
    "examples": ["我今年请了几次年假", "查上个月的请假"],
    "tools": ["query_my_leave_list"],
    "reason": "新增请假查询",
}


def fake_model(monkeypatch, reply: dict, prompts: list):
    def invoke(messages):
        prompts.append(messages[0][1])
        return SimpleNamespace(content=json.dumps(reply, ensure_ascii=False),
                               response_metadata={"token_usage": {"prompt_tokens": 9, "completion_tokens": 4}})

    cfg = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (SimpleNamespace(invoke=invoke), cfg))


def test_admin_created_tool_is_used_without_code_change(admin, chat, office, monkeypatch):
    r = admin.post("/v1/admin/tools", json=LEAVE_TOOL)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "initial" and r.json()["tool"]["registered"] is True
    assert r.json()["tool"]["source_file"] == "admin"
    r = admin.post("/v1/admin/skills", json=LEAVE_SKILL)
    assert r.status_code == 200, r.text
    assert r.json()["validation_status"] == "valid" and r.json()["examples"] == LEAVE_SKILL["examples"]

    route = office.get(LEAVE_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "list": [{"id": 9, "start_date": "2026-03-02", "days": 2, "leave_type_text": "年假", "secret": "x"}],
        "total": 1}}))
    prompts: list = []
    fake_model(monkeypatch, {"tool": "query_my_leave_list", "args": {"leave_type": 1, "oa": "lisi"}}, prompts)

    code = chat.post("/v1/chat/launch", json={"assertion": make_assertion()}).json()["launch_code"]
    session = chat.post("/v1/chat/session", json={"launch_code": code}).json()
    names = [s["display_name"] for s in session["skills"]]
    assert "请假查询" in names and "行程报销查询" in names
    h = {"Authorization": f"Bearer {session['ticket']}"}

    body = send(chat, h, "我今年请了几次年假").json()
    assert body["run_status"] == "succeeded", body
    qp = json.loads(route.calls.last.request.url.params["queryParams"])
    assert qp == {"leave_type": 1, "oa": "zhangsan"}, "身份由服务端注入，模型给的 oa 被丢弃"
    assert route.calls.last.request.url.params["limit"] == "10"
    assert route.calls.last.request.headers["Authorization"] == "tok-zhangsan"
    data = body["reply"]["data"]
    assert data["kind"] == "table" and data["title"] == "请假查询"
    assert [c["label"] for c in data["columns"]] == ["开始日期", "天数", "类型"]
    assert "secret" not in data["items"][0]
    assert "假期类型：年假" in body["reply"]["content"]
    assert "请假查询" in prompts[0] and "年假对应 leave_type=1" in prompts[0] and "query_my_leave_list" in prompts[0]

    actions = [a["action"] for a in audit_rows(admin)]
    assert "tool.create" in actions and "skill.create" in actions


def test_tool_form_validation(admin):
    leaked = {**LEAVE_TOOL, "model_params": {**LEAVE_TOOL["model_params"], "oa": {"type": "string"}}}
    r = admin.post("/v1/admin/tools", json=leaked)
    assert r.status_code == 422 and "身份字段" in r.json()["error"]["message"]

    post = admin.post("/v1/admin/tools", json={**LEAVE_TOOL, "method": "POST"})
    assert post.status_code == 422 and "GET" in post.json()["error"]["message"]

    for bad in ({"name": "Bad-Name"}, {"path": "http://evil/x"}, {"query_params_field": None},
                {"result": {"kind": "list", "fields": []}}):
        r = admin.post("/v1/admin/tools", json={**LEAVE_TOOL, **bad})
        assert r.status_code == 422, (bad, r.text)

    assert admin.post("/v1/admin/tools", json=LEAVE_TOOL).status_code == 200
    dup = admin.post("/v1/admin/tools", json=LEAVE_TOOL)
    assert dup.status_code == 409
    rename = admin.put("/v1/admin/tools/query_my_leave_list", json={**LEAVE_TOOL, "name": "other_name"})
    assert rename.status_code == 422
    assert admin.put("/v1/admin/tools/not_exists", json={**LEAVE_TOOL, "name": "not_exists"}).status_code == 404

    unknown = admin.post("/v1/admin/skills", json={**LEAVE_SKILL, "tools": ["nope_tool"]})
    assert unknown.status_code == 422 and "nope_tool" in unknown.json()["error"]["message"]
    no_desc = admin.post("/v1/admin/skills", json={**LEAVE_SKILL, "description": ""})
    assert no_desc.status_code == 422


def test_tool_edit_follows_version_rules(admin):
    admin.post("/v1/admin/tools", json=LEAVE_TOOL)
    relabel = {**LEAVE_TOOL, "result": {**LEAVE_TOOL["result"], "labels": {"days": "请假天数"}}, "reason": "改名称"}
    r = admin.put("/v1/admin/tools/query_my_leave_list", json=relabel)
    assert r.status_code == 200 and r.json()["result"] == "compatible" and r.json()["tool"]["current_version_no"] == 2
    spec = runtime(admin.client).engine.registry.get("query_my_leave_list")
    assert spec.label("days") == "请假天数"

    params = dict(LEAVE_TOOL["model_params"])
    del params["leave_type"]
    r = admin.put("/v1/admin/tools/query_my_leave_list", json={**relabel, "model_params": params, "reason": "删参数"})
    assert r.json()["result"] == "breaking_pending" and r.json()["tool"]["pending_version_no"] == 3
    assert "leave_type" in runtime(admin.client).engine.registry.get("query_my_leave_list").model_params

    skill = admin.post("/v1/admin/skills", json=LEAVE_SKILL).json()
    assert skill["current_version_no"] == 1
    r = admin.put("/v1/admin/skills/leave_query", json={**LEAVE_SKILL, "examples": ["查请假"], "reason": "改示例"})
    assert r.status_code == 200 and r.json()["current_version_no"] == 2 and r.json()["examples"] == ["查请假"]
    assert "tool.update" in [a["action"] for a in audit_rows(admin)]
    assert "skill.update" in [a["action"] for a in audit_rows(admin)]


def test_catalog_write_requires_permission(admin, installed):
    role = _role(admin, "tool_view", ["ops.run.view"])
    _user(admin, "toolview", [role["id"]])
    other = login(TestClient(installed.app), "toolview", VIEWER_PASS)
    assert other.post("/v1/admin/tools", json=LEAVE_TOOL).status_code == 403
    assert other.post("/v1/admin/skills", json=LEAVE_SKILL).status_code == 403


def test_help_is_generated_from_skills(chat, office):
    h = open_chat(chat)
    body = send(chat, h, "你好").json()
    assert "行程报销查询" in body["reply"]["content"] and "查上周的行程报销" in body["reply"]["content"]
