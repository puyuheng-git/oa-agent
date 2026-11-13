"""open-oa catalog → Tool schema 规范化与导入。"""

from __future__ import annotations

import httpx

from oa_agent.executor.catalog import normalize_open_oa_catalog_item
from oa_agent.integrations.open_oa import DEFAULT_UPSTREAM, INVOKE_PATH


SAMPLE = {
    "service": "out_attendance/go_out_application",
    "method": "getTravelExpensePageList",
    "op": "read",
    "risk": "low",
    "tool_name": "query_my_travel_expense_list",
    "summary": "分页查询本人行程报销单",
    "params": [
        {"name": "page", "type": "integer", "required": False, "label": "页码"},
        {"name": "limit", "type": "integer", "required": False, "label": "每页条数"},
    ],
    "returns": {
        "kind": "list",
        "fields": ["id", "date"],
        "list_columns": ["id", "date"],
        "labels": {"id": "单号", "date": "日期"},
    },
    "extensions": {"mcp": None},
}


def test_normalize_open_oa_catalog_item():
    spec, errs = normalize_open_oa_catalog_item(SAMPLE)
    assert errs == []
    assert spec["name"] == "query_my_travel_expense_list"
    assert spec["method"] == "POST"
    assert spec["path"] == INVOKE_PATH
    assert spec["invoke_service"] == "out_attendance/go_out_application"
    assert spec["invoke_method"] == "getTravelExpensePageList"
    assert "page" in spec["model_params"]
    assert spec["result"]["kind"] == "list"
    assert spec.get("upstream") in (None, DEFAULT_UPSTREAM)


def test_list_open_oa_catalog(admin, monkeypatch):
    from oa_agent.admin import catalog_api

    def fake_client(ctx):
        class C:
            def get_export_catalog(self, *, gateway_secret: str):
                assert gateway_secret
                return [SAMPLE]

        return C(), "secret"

    monkeypatch.setattr(catalog_api, "_open_oa_catalog_client", fake_client)
    r = admin.get("/v1/admin/tools/import/open-oa-catalog")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["service"] == SAMPLE["service"]
    assert items[0]["method"] == SAMPLE["method"]


def test_import_open_oa_catalog_persists_kind(admin, monkeypatch):
    from oa_agent.admin import catalog_api

    def fake_client(ctx):
        class C:
            def get_export_catalog(self, *, gateway_secret: str):
                assert gateway_secret
                return [SAMPLE]

        return C(), "secret"

    monkeypatch.setattr(catalog_api, "_open_oa_catalog_client", fake_client)
    r = admin.post(
        "/v1/admin/tools/import/open-oa-catalog",
        json={"reason": "导入行程", "items": [{"service": SAMPLE["service"], "method": SAMPLE["method"]}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["errors"] == []
    assert any(i["name"] == "query_my_travel_expense_list" for i in body["imported"])
    listing = admin.get("/v1/admin/tools").json()
    tool = next(t for t in listing["items"] if t["name"] == "query_my_travel_expense_list")
    assert tool["kind"] == "open_oa_invoke"
