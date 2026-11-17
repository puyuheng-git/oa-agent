"""open-oa 向导契约 → Tool schema 规范化（原 catalog 导入已下线）。"""

from __future__ import annotations

from oa_agent.executor.catalog import normalize_open_oa_catalog_item
from oa_agent.integrations.open_oa import DEFAULT_UPSTREAM, INVOKE_PATH


SAMPLE = {
    "service": "out_attendance/go_out_application",
    "method": "getTravelExpensePageList",
    "op": "read",
    "risk": "low",
    "call": "page_list",
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
}


def test_normalize_open_oa_catalog_item():
    spec, errs = normalize_open_oa_catalog_item(SAMPLE)
    assert errs == []
    assert spec["name"] == "query_my_travel_expense_list"
    assert spec["method"] == "POST"
    assert spec["path"] == INVOKE_PATH
    assert spec["invoke_service"] == "out_attendance/go_out_application"
    assert spec["invoke_method"] == "getTravelExpensePageList"
    assert spec["invoke_call"] == "page_list"
    assert "page" in spec["model_params"]
    assert spec["result"]["kind"] == "list"
    assert spec.get("upstream") in (None, DEFAULT_UPSTREAM)
