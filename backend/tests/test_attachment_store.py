import pytest

from oa_agent.chat.attachment_store import put_upload, read_upload, upload_object_key
from oa_agent.executor.executor import ToolError
from oa_agent.executor.export_store import ExportStore, OssConfig

MSG_ATTACHMENT_CORRUPT = "\u9644\u4ef6\u5df2\u635f\u574f\u6216\u65e0\u6cd5\u8bfb\u53d6\uff0c\u8bf7\u91cd\u65b0\u4e0a\u4f20"


def test_same_bytes_one_object(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa")
    a = put_upload(store, b"same-bytes")
    b = put_upload(store, b"same-bytes")
    assert a[1] == b[1]
    assert a[2] == b[2]
    assert read_upload(store, *a) == b"same-bytes"


def test_key_has_no_scheme():
    key = upload_object_key("dscpa", "ab" * 32)
    assert "://" not in key
    assert key.startswith("dscpa/attachments/v1/objects/ab/")


def test_read_upload_rejects_hash_mismatch(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa")
    storage, key, _digest = put_upload(store, b"payload")
    wrong = "0" * 64
    with pytest.raises(ToolError) as ei:
        read_upload(store, storage, key, wrong)
    assert ei.value.code == "ATTACHMENT_CORRUPT"
    assert ei.value.user_message == MSG_ATTACHMENT_CORRUPT


def test_put_upload_oss_dedup_single_put_object(tmp_path):
    puts = []
    stored_keys = set()

    class Fake:
        def object_exists(self, key):
            return key in stored_keys

        def put_object(self, key, data):
            puts.append((key, data))
            stored_keys.add(key)

    cfg = OssConfig("https://oss.example.com", "b", "p", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=Fake())
    a = put_upload(store, b"same-bytes")
    b = put_upload(store, b"same-bytes")
    assert a == b
    assert len(puts) == 1
    assert puts[0][1] == b"same-bytes"


def test_put_upload_oss_failure_no_local_file(tmp_path):
    class Fake:
        def object_exists(self, key):
            return False

        def put_object(self, key, data):
            raise RuntimeError("oss down")

    cfg = OssConfig("https://oss.example.com", "b", "p", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=Fake())
    with pytest.raises(ToolError) as ei:
        put_upload(store, b"x")
    assert ei.value.code == "EXPORT_STORE_FAILED"
    root = tmp_path / "exports"
    leftover = list(root.rglob("*")) if root.exists() else []
    assert leftover == []
