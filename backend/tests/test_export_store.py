"""导出文件登记：模型、ID、权限点（Task 1）；ExportStore 本地/OSS（Task 2）。"""

from __future__ import annotations

import secrets

import pytest
import sqlalchemy as sa

from oa_agent.auth.perms import PERMISSIONS
from oa_agent.db.models import ExportFile
from oa_agent.executor.executor import ToolError
from oa_agent.executor.export_store import ExportStore, OssConfig, oss_configured
from oa_agent.ids import new_export_file_id

OPS_FILE_VIEW = "导出文件：列表与下载（访问即审计）"


def test_export_file_id_prefix():
    assert new_export_file_id().startswith("exp_")


def test_ops_file_view_permission_registered():
    assert "ops.file.view" in PERMISSIONS
    assert PERMISSIONS["ops.file.view"] == OPS_FILE_VIEW


def test_export_file_model_insert_and_query(installed):
    rt = installed.app.state.runtime
    file_id = new_export_file_id()
    ticket = secrets.token_urlsafe(18)
    tenant_id = rt.tenant_id
    object_key = f"{tenant_id}/{ticket}.bin"

    with rt.session() as db, db.begin():
        db.add(
            ExportFile(
                file_id=file_id,
                tenant_id=tenant_id,
                ticket=ticket,
                oa="export_smoke_oa",
                thread_id="thr_01JABCDEFGHJKMNPQRSTVWXYZ0",
                run_id="run_01JABCDEFGHJKMNPQRSTVWXYZ0",
                filename="report.txt",
                size_bytes=42,
                content_type="text/plain",
                storage="local",
                object_key=object_key,
            )
        )

    with rt.session() as db:
        row = db.execute(sa.select(ExportFile).where(ExportFile.file_id == file_id)).scalar_one()
        assert row.ticket == ticket
        assert row.oa == "export_smoke_oa"
        assert row.thread_id == "thr_01JABCDEFGHJKMNPQRSTVWXYZ0"
        assert row.storage == "local"
        assert row.object_key == object_key


def test_oss_configured_requires_endpoint_bucket_and_keys():
    assert not oss_configured(None)
    assert not oss_configured(OssConfig("", "b", "p", "id", "secret"))
    assert not oss_configured(OssConfig("https://oss.example.com", "", "p", "id", "secret"))
    assert not oss_configured(OssConfig("https://oss.example.com", "b", "p", "", "secret"))
    assert not oss_configured(OssConfig("https://oss.example.com", "b", "p", "id", ""))
    assert oss_configured(OssConfig("https://oss.example.com", "b", "", "id", "secret"))
    assert oss_configured(OssConfig("https://oss.example.com", "b", "p", "id", "secret"))


def test_put_local_when_oss_missing(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=None)
    storage, key = store.put("abcdefghijklmnopqrst", b"hello")
    assert storage == "local"
    assert store.get(storage, key) == b"hello"


def test_put_oss_when_configured(tmp_path):
    calls = []
    class Fake:
        def put_object(self, key, data): calls.append((key, data))
        def get_object(self, key):
            class R:
                def read(self_inner):
                    return b"from-oss"
            return R()
    cfg = OssConfig("https://oss.example.com", "b", "p", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=Fake())
    storage, key = store.put("abcdefghijklmnopqrst", b"x")
    assert storage == "oss" and key.startswith("p/")
    assert store.get(storage, key) == b"from-oss"


def test_put_oss_failure_does_not_write_local(tmp_path):
    class Fake:
        def put_object(self, key, data):
            raise RuntimeError("oss down")
    cfg = OssConfig("https://oss.example.com", "b", "p", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=Fake())
    with pytest.raises(ToolError) as ei:
        store.put("abcdefghijklmnopqrst", b"x")
    assert ei.value.message == "文件保存失败"
    root = tmp_path / "exports"
    leftover = list(root.rglob("*")) if root.exists() else []
    assert leftover == []


def test_put_local_object_key_is_relative_not_url(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=None)
    storage, key = store.put("abcdefghijklmnopqrst", b"hello")
    assert storage == "local"
    assert key == "dscpa/abcdefghijklmnopqrst.bin"
    assert "://" not in key
    assert not key.startswith("/")


def test_get_local_rejects_path_escape(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=None)
    store.put("abcdefghijklmnopqrst", b"hello")
    with pytest.raises(ToolError):
        store.get("local", "dscpa/../secret.bin")
    with pytest.raises(ToolError):
        store.get("local", "https://evil.example/x.bin")
    with pytest.raises(ToolError):
        store.get("local", "/etc/passwd")


def test_delete_local_ignores_missing(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=None)
    storage, key = store.put("abcdefghijklmnopqrst", b"hello")
    store.delete(storage, key)
    store.delete(storage, key)
    with pytest.raises(ToolError):
        store.get(storage, key)


def test_delete_oss_ignores_missing(tmp_path):
    deleted = []

    class Fake:
        def put_object(self, key, data):
            return None

        def delete_object(self, key):
            deleted.append(key)

    cfg = OssConfig("https://oss.example.com", "b", "p", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=Fake())
    storage, key = store.put("abcdefghijklmnopqrst", b"x")
    store.delete(storage, key)
    assert deleted == [key]
    store.delete(storage, "p/dscpa/no-such.bin")
    assert deleted[-1] == "p/dscpa/no-such.bin"


def test_object_key_for_empty_prefix(tmp_path):
    cfg = OssConfig("https://oss.example.com", "b", "", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=object())
    assert store.object_key_for("abcdefghijklmnopqrst") == "dscpa/abcdefghijklmnopqrst.bin"


def _export_spec():
    from oa_agent.executor.registry import ToolSpec

    return ToolSpec(
        name="builtin.export", method="", path="", version="builtin", schema_hash="",
        risk_level="medium", requires_confirmation=False, timeout_seconds=10,
        inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params={}, result_kind="text", result_fields=("text",), summary="导出",
        kind="builtin", builtin_id="sys.export",
    )


def test_identity_thread_and_run_default_none():
    from oa_agent.executor.executor import Identity

    ident = Identity(oa="a", authorization="t")
    assert getattr(ident, "thread_id", "missing") is None
    assert getattr(ident, "run_id", "missing") is None


def test_identity_for_run_sets_thread_and_run():
    import inspect
    from types import SimpleNamespace

    from oa_agent.auth.chat_launch import ChatSession
    from oa_agent.chat import service

    session = ChatSession(
        oa="alice", uid=1, display_name="Alice", thread_id="thr_thread",
        office_token="tok", token_expires_at=9_999_999_999, created_at=1,
    )
    fn = getattr(service, "_identity_for_run", None)
    assert callable(fn)
    ident = fn(session, SimpleNamespace(run_id="run_run"))
    assert ident.oa == "alice" and ident.authorization == "tok"
    assert ident.thread_id == "thr_thread" and ident.run_id == "run_run"
    assert "_identity_for_run" in inspect.getsource(service._build_context)
    assert "_identity_for_run" in inspect.getsource(service._build_write_context)


def test_export_insert_failure_deletes_object(tmp_path, installed):
    from oa_agent.executor.builtin_runtime import BuiltinRuntime
    from oa_agent.executor.executor import Identity

    rt = installed.app.state.runtime

    def factory():
        raise RuntimeError("insert failed")

    runtime = BuiltinRuntime(tenant_id=rt.tenant_id, session_factory=factory, data_dir=tmp_path)
    with pytest.raises(RuntimeError, match="insert failed"):
        runtime.call(
            _export_spec(),
            {"filename": "note.txt", "content": "hello"},
            identity=Identity(oa="alice", authorization="", thread_id="thr_x", run_id="run_x"),
        )
    root = tmp_path / "exports"
    files = [p for p in root.rglob("*") if p.is_file()] if root.exists() else []
    assert files == []
    with rt.session() as db:
        rows = db.scalars(sa.select(ExportFile).where(ExportFile.oa == "alice")).all()
    assert rows == []


def _save_oss(rt, secret="sekret-value-ABCD"):
    with rt.session() as db, db.begin():
        rt.settings_svc.update(
            db,
            "oss",
            {
                "endpoint": "https://oss.example.com",
                "bucket": "bucket-a",
                "prefix": "pfx",
                "access_key_id": "akid",
                "access_key_secret": secret,
            },
            [],
            "tester",
        )


def test_build_builtin_runtime_registers_oss_object(installed, monkeypatch):
    from oa_agent.executor.builtin_runtime import build_builtin_runtime
    from oa_agent.executor.executor import Identity

    rt = installed.app.state.runtime
    secret = "sekret-value-ABCD"
    _save_oss(rt, secret)
    saved = {}

    class Fake:
        def put_object(self, key, data):
            saved["key"] = key
            saved["data"] = data

        def get_object(self, key):
            class R:
                def read(self_inner):
                    return saved["data"]

            return R()

    monkeypatch.setattr("oss2.Auth", lambda *a, **k: object())
    monkeypatch.setattr("oss2.Bucket", lambda *a, **k: Fake())
    runtime = build_builtin_runtime(rt)
    out = runtime.call(
        _export_spec(),
        {"filename": "a.txt", "content": "hello"},
        identity=Identity(oa="oss_alice", authorization="t", thread_id="thr_oss", run_id="run_oss"),
    )
    assert str(out.get("file_id") or "").startswith("exp_")
    assert "expires_in" not in out and "expires_at" not in out
    assert saved["key"].startswith("pfx/") and secret not in saved["key"]
    assert "://" not in saved["key"]
    with rt.session() as db:
        row = db.scalar(sa.select(ExportFile).where(ExportFile.ticket == out["ticket"]))
    assert row is not None and row.storage == "oss" and row.object_key == saved["key"]
    assert row.thread_id == "thr_oss" and row.run_id == "run_oss" and row.oa == "oss_alice"
    assert row.content_type == "text/plain"
    assert secret not in repr(row.object_key)
    first = runtime.take_export(out["ticket"], "oss_alice")
    second = runtime.take_export(out["ticket"], "oss_alice")
    assert first == (b"hello", "a.txt") and second == first
    assert runtime.take_export(out["ticket"], "bob") is None


def test_oss_put_failure_writes_no_row_and_no_local(installed, monkeypatch):
    from oa_agent.executor.builtin_runtime import build_builtin_runtime
    from oa_agent.executor.executor import Identity

    rt = installed.app.state.runtime
    _save_oss(rt)
    root = rt.settings.data_dir / "exports"
    before = set(root.rglob("*")) if root.exists() else set()

    class Fake:
        def put_object(self, key, data):
            raise RuntimeError("oss down")

    monkeypatch.setattr("oss2.Auth", lambda *a, **k: object())
    monkeypatch.setattr("oss2.Bucket", lambda *a, **k: Fake())
    runtime = build_builtin_runtime(rt)
    with pytest.raises(ToolError) as ei:
        runtime.call(
            _export_spec(),
            {"filename": "a.txt", "content": "hello"},
            identity=Identity(oa="oss_fail_oa", authorization="t"),
        )
    assert ei.value.code == "EXPORT_STORE_FAILED"
    assert ei.value.message == "文件保存失败"
    after = set(root.rglob("*")) if root.exists() else set()
    assert after == before
    with rt.session() as db:
        rows = db.scalars(sa.select(ExportFile).where(ExportFile.oa == "oss_fail_oa")).all()
    assert rows == []
