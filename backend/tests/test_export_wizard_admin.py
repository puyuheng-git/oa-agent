"""Export 向导管理 API：discover / probe / save。"""

from __future__ import annotations


SAMPLE_DESC = {
    "service": "out_attendance/go_out_application",
    "method": "getTravelExpensePageList",
    "params": [
        {"name": "page", "type": "integer", "required": False, "label": "页码"},
        {"name": "limit", "type": "integer", "required": False, "label": "每页条数"},
    ],
    "call_suggest": "page_list",
    "returns": None,
    "summary": "分页查询行程报销",
}


def _patch_client(monkeypatch, *, probe_ok=True):
    from oa_agent.admin import catalog_api

    class C:
        def discover_exports(self, service, *, gateway_secret: str):
            assert gateway_secret and service
            return [{"name": "getTravelExpensePageList", "param_names": ["params", "page", "limit"]}]

        def describe_export(self, service, method, *, gateway_secret: str):
            assert method
            return dict(SAMPLE_DESC)

        def probe_export(self, **kw):
            assert kw.get("gateway_secret")
            if not probe_ok:
                from oa_agent.integrations.open_oa import OpenOaError

                raise OpenOaError("UPSTREAM_BIZ_ERROR", "业务失败")
            return {"list": [], "total": 0}

    def fake_client(ctx):
        return C(), "secret"

    monkeypatch.setattr(catalog_api, "_open_oa_wizard_client", fake_client)


def test_wizard_discover(admin, monkeypatch):
    _patch_client(monkeypatch)
    r = admin.post(
        "/v1/admin/tools/export-wizard/discover",
        json={"service": "out_attendance/go_out_application"},
    )
    assert r.status_code == 200, r.text
    methods = r.json()["methods"]
    hit = next(m for m in methods if m["name"] == "getTravelExpensePageList")
    assert "already_added" in hit
    assert isinstance(hit["already_added"], bool)


def test_wizard_save_requires_successful_probe(admin, monkeypatch):
    _patch_client(monkeypatch, probe_ok=False)
    r = admin.post(
        "/v1/admin/tools/export-wizard/save",
        json={
            "reason": "试保存",
            "service": SAMPLE_DESC["service"],
            "method": SAMPLE_DESC["method"],
            "oa": "testuser",
            "args": {"page": 1, "limit": 5},
            "call": "page_list",
            "op": "read",
            "risk": "low",
            "name": "query_my_travel_expense_list",
            "summary": "list",
            "model_params": {"page": {"type": "integer", "label": "页码"}},
            "result": {"kind": "list", "fields": ["id"], "labels": {"id": "单号"}, "list_columns": ["id"]},
        },
    )
    assert r.status_code == 422, r.text


def test_wizard_save_persists_open_oa_invoke(admin, monkeypatch):
    _patch_client(monkeypatch, probe_ok=True)
    r = admin.post(
        "/v1/admin/tools/export-wizard/save",
        json={
            "reason": "导入行程",
            "service": SAMPLE_DESC["service"],
            "method": SAMPLE_DESC["method"],
            "oa": "testuser",
            "args": {"page": 1, "limit": 5},
            "call": "page_list",
            "op": "read",
            "risk": "low",
            "name": "query_my_travel_expense_list",
            "summary": "分页查询本人行程报销单",
            "model_params": {
                "page": {"type": "integer", "label": "页码", "required": False},
                "limit": {"type": "integer", "label": "每页条数", "required": False},
            },
            "result": {
                "kind": "list",
                "fields": ["id", "date"],
                "labels": {"id": "单号", "date": "日期"},
                "list_columns": ["id", "date"],
            },
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "open_oa_invoke"
    assert body["name"] == "query_my_travel_expense_list"
    listing = admin.get("/v1/admin/tools", params={"kind": "open_oa_invoke"}).json()
    tool = next(t for t in listing["items"] if t["name"] == "query_my_travel_expense_list")
    assert tool["kind"] == "open_oa_invoke"
