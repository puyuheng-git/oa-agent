"""导入向导 upload-temp：落盘、净化文件名、校验空文件/权限。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from oa_agent.admin import wizard_temp_upload
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

URL = "/v1/admin/tools/export-wizard/upload-temp"


@pytest.fixture(autouse=True)
def temp_dir(tmp_path, monkeypatch):
    """把落盘目录指到 tmp，避免测试污染 runtime/wizard-temp。"""
    d = tmp_path / "wizard-temp"
    monkeypatch.setattr(wizard_temp_upload, "TEMP_DIR", d)
    return d


def _post(admin, files):
    return admin.client.post(URL, files=files, headers=admin._h())


def test_upload_temp_returns_ref(admin, temp_dir):
    payload = b"%PDF-1.4"
    r = _post(admin, {"file": ("a.pdf", payload, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["filename"] == "a.pdf"
    assert body["ref"]
    assert body["sha256"] == hashlib.sha256(payload).hexdigest()
    assert body["size"] == len(payload)
    saved = Path(body["ref"])
    assert saved.parent == temp_dir.resolve() and saved.read_bytes() == payload
    assert any(row["action"] == "tool.export_wizard_upload_temp" for row in audit_rows(admin))


def test_upload_temp_sanitizes_filename(admin, temp_dir):
    r = _post(admin, {"file": ("../../evil name?.pdf", b"x", "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert "/" not in body["filename"] and "\\" not in body["filename"] and " " not in body["filename"]
    assert Path(body["ref"]).parent == temp_dir.resolve()


def test_save_purges_files_older_than_ttl(temp_dir):
    """写入前清理超过 24 小时的旧文件，新文件保留。"""
    import os
    import time

    temp_dir.mkdir(parents=True)
    old = temp_dir / "old.pdf"
    fresh = temp_dir / "fresh.pdf"
    old.write_bytes(b"o")
    fresh.write_bytes(b"f")
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    wizard_temp_upload.save_wizard_temp_file(b"new", "n.pdf")
    assert not old.exists()
    assert fresh.exists()


def test_upload_temp_rejects_empty(admin):
    r = _post(admin, {"file": ("a.pdf", b"", "application/pdf")})
    assert r.status_code == 400, r.text


RESULT_SCHEMA = {"type": "object", "properties": {"id": {"type": "string", "label": "单号"}}}


def _result_schema(admin, name):
    """读取 Tool 当前版本落库的 result.schema。"""
    r = admin.get(f"/v1/admin/tools/{name}/versions/1")
    assert r.status_code == 200, r.text
    return r.json()["schema"]["result"].get("schema")


def test_tool_result_schema_persists_on_create(admin):
    from tests.test_catalog_admin import LEAVE_TOOL, _ensure_office_upstream

    _ensure_office_upstream(admin)
    body = {**LEAVE_TOOL, "result": {**LEAVE_TOOL["result"], "schema": RESULT_SCHEMA}}
    r = admin.post("/v1/admin/tools", json=body)
    assert r.status_code == 200, r.text
    saved = _result_schema(admin, LEAVE_TOOL["name"])
    assert saved["type"] == "object" and saved["properties"]["id"]["label"] == "单号"


def test_wizard_save_persists_result_schema(admin, monkeypatch):
    from tests.test_export_wizard_admin import SAMPLE_DESC, _patch_client

    _patch_client(monkeypatch, probe_ok=True)
    r = admin.post("/v1/admin/tools/export-wizard/save", json={
        "reason": "导入行程", "service": SAMPLE_DESC["service"], "method": SAMPLE_DESC["method"],
        "oa": "testuser", "args": {}, "call": "page_list", "op": "read", "risk": "low",
        "name": "wizard_schema_tool", "summary": "带返回结构",
        "result": {"kind": "list", "fields": ["id"], "labels": {"id": "单号"}, "list_columns": ["id"],
                   "schema": RESULT_SCHEMA},
    })
    assert r.status_code == 200, r.text
    saved = _result_schema(admin, "wizard_schema_tool")
    assert saved["type"] == "object" and saved["properties"]["id"]["label"] == "单号"


def test_upload_temp_requires_tool_manage(admin, installed):
    role = _role(admin, "viewer_only", ["ops.run.view"])
    _user(admin, "viewer1", [role["id"]])
    viewer = login(TestClient(installed.app), "viewer1", VIEWER_PASS)
    r = viewer.client.post(URL, files={"file": ("a.pdf", b"x", "application/pdf")}, headers=viewer._h())
    assert r.status_code == 403, r.text
