"""M3 Task 6：/v1/admin/packs 列表与启停（复用 ops.tool.manage）。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

URL = "/v1/admin/packs"
OA_TRAVEL = "oa_travel"


def _by_id(items: list[dict], pack_id: str) -> dict:
    return next(p for p in items if p["id"] == pack_id)


def test_list_includes_oa_travel_enabled(admin):
    r = admin.get(URL)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    travel = _by_id(items, OA_TRAVEL)
    assert travel["display_name"]
    assert travel["version"]
    assert travel["enabled"] is True
    assert travel["default_enabled"] is True
    assert "office" in travel["connectors"]
    assert "validation_errors" in travel


def test_disable_then_enable_oa_travel(admin):
    r = admin.post(f"{URL}/{OA_TRAVEL}/disable", json={"reason": "临时关闭行程包"})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False

    listed = _by_id(admin.get(URL).json()["items"], OA_TRAVEL)
    assert listed["enabled"] is False

    r = admin.post(f"{URL}/{OA_TRAVEL}/enable", json={"reason": "恢复行程包"})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert _by_id(admin.get(URL).json()["items"], OA_TRAVEL)["enabled"] is True

    actions = {a["action"] for a in audit_rows(admin)}
    assert "pack.disable" in actions
    assert "pack.enable" in actions


def test_packs_requires_ops_tool_manage(admin, installed):
    role = _role(admin, "run_only_packs", ["ops.run.view"])
    _user(admin, "packview", [role["id"]])
    other = login(TestClient(installed.app), "packview", VIEWER_PASS)
    assert other.get(URL).status_code == 403
    assert other.post(f"{URL}/{OA_TRAVEL}/disable", json={"reason": "越权"}).status_code == 403
    assert other.post(f"{URL}/{OA_TRAVEL}/enable", json={"reason": "越权"}).status_code == 403
    assert _by_id(admin.get(URL).json()["items"], OA_TRAVEL)["enabled"] is True
