"""管理端导出文件列表 / 下载：ops.file.view + 访问即审计。"""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi.testclient import TestClient

from oa_agent.db.models import ExportFile
from oa_agent.db.types import utcnow
from oa_agent.executor.export_store import ExportStore
from oa_agent.ids import new_export_file_id
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

LIST_URL = "/v1/admin/export-files"


def _download_url(file_id: str) -> str:
    return f"{LIST_URL}/{file_id}/download"


def _seed_export_file(
    rt,
    *,
    oa: str = "file_alice",
    filename: str = "report.txt",
    content: bytes = b"hello-export",
    thread_id: str | None = "thr_export_1",
    run_id: str | None = "run_export_1",
    created_at=None,
) -> str:
    ticket = secrets.token_urlsafe(18)
    file_id = new_export_file_id()
    store = ExportStore(data_dir=rt.settings.data_dir, tenant_id=rt.tenant_id)
    storage, object_key = store.put(ticket, content)
    with rt.session() as db, db.begin():
        db.add(
            ExportFile(
                file_id=file_id,
                tenant_id=rt.tenant_id,
                ticket=ticket,
                oa=oa,
                thread_id=thread_id,
                run_id=run_id,
                filename=filename,
                size_bytes=len(content),
                content_type="text/plain",
                storage=storage,
                object_key=object_key,
                created_at=created_at or utcnow(),
            )
        )
    return file_id


def test_list_requires_perm(admin, installed):
    role = _role(admin, "file_viewer", ["ops.file.view"])
    empty = _role(admin, "no_file_role", [])
    _user(admin, "file_reader", [role["id"]])
    _user(admin, "no_file_user", [empty["id"]])

    reader = login(TestClient(installed.app), "file_reader", VIEWER_PASS)
    assert reader.get(LIST_URL).status_code == 200

    denied = login(TestClient(installed.app), "no_file_user", VIEWER_PASS)
    assert denied.get(LIST_URL).status_code == 403
    assert denied.get(_download_url("exp_missing")).status_code == 403


def test_list_and_download_with_audit(admin, installed):
    rt = installed.app.state.runtime
    content = b"admin-download-bytes"
    file_id = _seed_export_file(rt, filename="notes.txt", content=content, oa="file_bob")

    r = admin.get(LIST_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    item = next(i for i in body["items"] if i["file_id"] == file_id)
    assert "ticket" not in item
    assert "object_key" not in item
    assert item["oa"] == "file_bob"
    assert item["thread_id"] == "thr_export_1"
    assert item["run_id"] == "run_export_1"
    assert item["filename"] == "notes.txt"
    assert item["size_bytes"] == len(content)
    assert item["storage"] == "local"
    assert item["created_at"]

    d = admin.get(_download_url(file_id))
    assert d.status_code == 200, d.text
    assert d.content == content
    assert "notes.txt" in d.headers.get("content-disposition", "")

    actions = {a["action"] for a in audit_rows(admin)}
    assert "export_file.list" in actions
    assert "export_file.download" in actions


def test_download_missing_file_is_404(admin):
    r = admin.get(_download_url("exp_01DOESNOTEXIST000000000000"))
    assert r.status_code == 404
    assert r.json()["error"]["message"] == "文件不存在"


def test_list_filters_oa_thread_filename_and_time(admin, installed):
    rt = installed.app.state.runtime
    now = utcnow()
    keep = _seed_export_file(
        rt, oa="filter_alice", filename="keep_report.txt", thread_id="thr_keep",
        created_at=now - timedelta(hours=1),
    )
    _seed_export_file(
        rt, oa="filter_bob", filename="other.csv", thread_id="thr_other",
        created_at=now - timedelta(hours=1),
    )
    _seed_export_file(
        rt, oa="filter_alice", filename="old_report.txt", thread_id="thr_keep",
        created_at=now - timedelta(days=10),
    )

    by_oa = admin.get(LIST_URL, params={"oa": "filter_alice"})
    assert by_oa.status_code == 200, by_oa.text
    oas = {i["oa"] for i in by_oa.json()["items"]}
    assert oas == {"filter_alice"}

    by_thread = admin.get(LIST_URL, params={"thread_id": "thr_keep"})
    assert {i["thread_id"] for i in by_thread.json()["items"]} == {"thr_keep"}

    by_name = admin.get(LIST_URL, params={"filename": "keep_report"})
    names = {i["filename"] for i in by_name.json()["items"]}
    assert names == {"keep_report.txt"}
    assert by_name.json()["items"][0]["file_id"] == keep

    by_time = admin.get(
        LIST_URL,
        params={
            "oa": "filter_alice",
            "start": (now - timedelta(hours=2)).isoformat(),
            "end": now.isoformat(),
        },
    )
    ids = {i["file_id"] for i in by_time.json()["items"]}
    assert ids == {keep}
