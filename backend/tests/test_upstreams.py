"""多个 office-api 地址：配置校验、Tool 选择地址、员"token 走所选地址、mint 只走主地址、删除保护"""

from __future__ import annotations

import json

import httpx
import sqlalchemy as sa

from oa_agent.db.models import Setting
from oa_agent.executor.catalog import compare, normalize_tool_form
from tests.conftest import audit_rows
from tests.test_catalog_admin import LEAVE_SKILL, LEAVE_TOOL, fake_model
from tests.test_chat import OFFICE, chat, office, open_chat, run_and_events, runtime, send  # noqa: F401

HR = "http://hr-gateway.test/api"
HR_UPSTREAM = {"key": "hr", "label": "人事网关", "base_url": HR + "/"}
HR_TOOL = {**LEAVE_TOOL, "upstream": "hr"}


def set_upstreams(admin, items):
    return admin.put("/v1/admin/settings/oa", json={"values": {"extra_upstreams": items}})


def test_upstreams_validated_and_normalized(admin):
    r = set_upstreams(admin, [HR_UPSTREAM, {"key": "fin", "base_url": "https://fin.example.com"}])
    assert r.status_code == 200, r.text
    assert r.json()["group"]["values"]["extra_upstreams"] == [
        {"key": "hr", "label": "人事网关", "base_url": HR},
        {"key": "fin", "label": "fin", "base_url": "https://fin.example.com"},
    ]
    assert r.json()["changed"] == ["extra_upstreams"]

    for bad in ([{"key": "office", "base_url": HR}],
                [{"key": "Bad-Key", "base_url": HR}],
                [HR_UPSTREAM, {"key": "hr", "base_url": "https://x.example.com"}],
                [{"key": "ftp", "base_url": "ftp://files.example.com"}],
                [{"key": "q1", "base_url": "https://x.example.com/api?token=1"}],
                [{"key": "pw", "base_url": "https://u:p@x.example.com"}],
                [{"key": "nourl"}],
                "not json"):
        r = set_upstreams(admin, bad)
        assert r.status_code == 422, (bad, r.text)


def test_tool_on_other_upstream_uses_employee_token(admin, chat, office, monkeypatch):
    r = admin.post("/v1/admin/tools", json=HR_TOOL)
    assert r.status_code == 422 and "未在「OA 对接」中配置" in r.json()["error"]["message"]

    assert set_upstreams(admin, [HR_UPSTREAM]).status_code == 200
    listing = admin.get("/v1/admin/tools").json()
    assert [u["key"] for u in listing["upstreams"]] == ["office", "hr"]

    r = admin.post("/v1/admin/tools", json=HR_TOOL)
    assert r.status_code == 200, r.text
    assert r.json()["tool"]["upstream"] == "hr" and r.json()["tool"]["registered"] is True
    assert admin.post("/v1/admin/skills", json=LEAVE_SKILL).status_code == 200
    after = audit_rows(admin, action="tool.create")[0]["after_summary"]
    assert "'upstream': 'hr'" in after

    hr_route = office.get(f"{HR}/hr/leave/index").mock(return_value=httpx.Response(200, json={
        "code": 0, "data": {"list": [{"id": 1, "start_date": "2026-03-02", "days": 1, "leave_type_text": "年假"}],
                            "total": 1}}))
    main_route = office.get(f"{OFFICE}/hr/leave/index")
    fake_model(monkeypatch, {"tool": "query_my_leave_list", "args": {"leave_type": 1}}, [])

    h = open_chat(chat)
    body = send(chat, h, "我今年请了几次年").json()
    assert body["run_status"] == "succeeded", body
    req = hr_route.calls.last.request
    assert req.headers["Authorization"] == "tok-zhangsan"
    assert json.loads(req.url.params["queryParams"])["oa"] == "zhangsan"
    assert not main_route.called

    _, events = run_and_events(chat, body["run_id"])
    start = next(e for e in events if e.event_type == "tool_call_start")
    assert start.metadata_json["upstream"] == "hr"


def test_upstream_in_use_cannot_be_removed(admin):
    set_upstreams(admin, [HR_UPSTREAM])
    assert admin.post("/v1/admin/tools", json=HR_TOOL).status_code == 200
    r = set_upstreams(admin, [])
    assert r.status_code == 409 and r.json()["error"]["code"] == "UPSTREAM_IN_USE"
    assert "query_my_leave_list（hr" in r.json()["error"]["message"]
    assert admin.get("/v1/admin/settings/oa").json()["values"]["extra_upstreams"][0]["key"] == "hr"

    renamed = {**HR_UPSTREAM, "label": "人事网关（新"}
    assert set_upstreams(admin, [renamed]).status_code == 200, "只改名称不算删除"


def test_missing_upstream_at_runtime_fails_clearly(admin, chat, office, monkeypatch):
    set_upstreams(admin, [HR_UPSTREAM])
    admin.post("/v1/admin/tools", json=HR_TOOL)
    admin.post("/v1/admin/skills", json=LEAVE_SKILL)
    rt = runtime(chat)
    with rt.session() as db, db.begin():
        row = db.scalar(sa.select(Setting).where(Setting.setting_key == "extra_upstreams"))
        row.value_json = []
    fake_model(monkeypatch, {"tool": "query_my_leave_list", "args": {}}, [])

    body = send(chat, open_chat(chat), "查请").json()
    assert body["run_status"] == "failed"
    assert body["reply"]["error_code"] == "UPSTREAM_NOT_CONFIGURED"
    assert body["reply"]["content"] == "该查询功能尚未完成配置，请联系管理员"


def test_upstream_change_is_breaking_and_default_keeps_hash():
    form = {k: v for k, v in LEAVE_TOOL.items() if k != "reason"}
    legacy, errors = normalize_tool_form(form)
    assert not errors and "upstream" not in legacy
    explicit, _ = normalize_tool_form({**form, "upstream": "office"})
    assert compare(legacy, explicit)[0] == "unchanged"
    hr, _ = normalize_tool_form({**form, "upstream": "hr"})
    level, diff = compare(legacy, hr)
    assert level == "breaking" and [d["field"] for d in diff] == ["upstream"]
    _, errors = normalize_tool_form({**form, "upstream": "Bad Key"})
    assert any("upstream" in e for e in errors)
    _, errors = normalize_tool_form({**form, "path": "//evil.example.com/x"})
    assert errors
