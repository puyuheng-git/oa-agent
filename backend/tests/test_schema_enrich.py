"""enrich-schema：LLM 候选校验与管理 API。"""

from __future__ import annotations

from types import SimpleNamespace

from oa_agent.executor.schema_enrich import _collect_keys, enrich_from_probe


def test_collect_keys_from_list_envelope():
    keys = _collect_keys({"list": [{"id": 1, "user": {"name": "a"}}], "total": 1})
    assert "id" in keys
    assert "user.name" in keys


def test_enrich_from_probe_filters_fields_and_params(monkeypatch):
    def fake_complete(model, messages):
        return {
            "name": "query_leave_list",
            "summary": "请假列表",
            "description": "查询本人请假",
            "result_kind": "list",
            "fields": [
                {"field": "id", "label": "单号"},
                {"field": "ghost", "label": "不存在"},
                {"field": "bad-field!", "label": "非法"},
            ],
            "list_columns": ["id", "ghost"],
            "params": {
                "page": {"label": "页码", "description": "从 1 开始"},
                "unknown": {"label": "忽略"},
            },
            "skill": {
                "name": "leave_skill",
                "display_name": "请假查询",
                "description": "查请假",
                "instructions": "提取时间范围",
                "examples": ["我的请假"],
            },
        }

    monkeypatch.setattr("oa_agent.executor.schema_enrich.complete_json", fake_complete)
    suggestion, skill, warnings = enrich_from_probe(
        SimpleNamespace(),
        {
            "name": "",
            "summary": "",
            "path": "/hr/leave",
            "model_params": {"page": {"type": "integer"}},
            "result": {"kind": "list", "fields": [], "labels": {}},
        },
        {"page": 1},
        {"list": [{"id": 9, "status": "ok"}], "total": 1},
    )
    fields = {f["field"] for f in suggestion["fields"]}
    assert "id" in fields
    assert "ghost" not in fields
    assert "bad-field!" not in fields
    assert suggestion["list_columns"] == ["id"]
    assert "page" in suggestion["params"]
    assert "unknown" not in suggestion["params"]
    assert skill and skill["name"] == "leave_skill"
    assert warnings


def test_enrich_schema_api(admin, monkeypatch):
    from oa_agent.admin import catalog_api

    monkeypatch.setattr(
        catalog_api,
        "_draft_model",
        lambda ctx: SimpleNamespace(invoke=lambda *a, **k: None),
    )

    def fake_enrich(model, draft, probe_args, probe_data, **kw):
        return (
            {
                "name": "query_demo",
                "summary": "演示",
                "description": "说明",
                "result_kind": "list",
                "fields": [{"field": "id", "label": "编号"}],
                "list_columns": ["id"],
                "params": {},
            },
            {
                "name": "demo_skill",
                "display_name": "演示",
                "description": "d",
                "instructions": "i",
                "examples": ["q"],
                "tools": ["query_demo"],
            },
            ["请检查"],
        )

    monkeypatch.setattr("oa_agent.executor.schema_enrich.enrich_from_probe", fake_enrich)

    r = admin.post(
        "/v1/admin/tools/enrich-schema",
        json={
            "probe_args": {"page": 1},
            "probe_data": {"list": [{"id": 1}]},
            "draft": {"name": "", "model_params": {}, "result": {"kind": "list", "fields": []}},
            "include_skill": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestion"]["name"] == "query_demo"
    assert body["skill"]["name"] == "demo_skill"
