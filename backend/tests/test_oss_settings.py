"""系统设置 oss 组与测试连接。"""

from unittest.mock import MagicMock, patch

import pytest

from oa_agent.admin.settings_api import _run_test
from oa_agent.config.schema import GROUPS
from oa_agent.errors import AppError

OSS_SECRET = "oss-access-secret-XYZZ9876"
OSS_CFG = {
    "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
    "bucket": "my-bucket",
    "prefix": "exports",
    "access_key_id": "LTAI_test_id",
    "access_key_secret": OSS_SECRET,
}


def test_oss_group_fields():
    g = GROUPS["oss"]
    assert g.testable is True
    assert g.apply_mode == "热生效"
    assert g.description
    keys = {f.key: f for f in g.fields}
    assert set(keys) == {"endpoint", "bucket", "prefix", "access_key_id", "access_key_secret"}
    assert keys["endpoint"].kind == "url"
    assert keys["bucket"].kind == "str"
    assert keys["prefix"].kind == "str" and keys["prefix"].default == ""
    assert keys["access_key_id"].kind == "str"
    assert keys["access_key_secret"].kind == "secret"
    for f in g.fields:
        assert f.help, f.key
    assert "OSS" in keys["access_key_secret"].help or "本地" in g.description


def test_run_test_oss_missing_bucket():
    cfg = dict(OSS_CFG, bucket="")
    with pytest.raises(AppError) as ei:
        _run_test("oss", cfg)
    assert ei.value.status == 422
    assert "Bucket" in ei.value.message or "bucket" in ei.value.message.lower()


def test_run_test_oss_missing_secret():
    cfg = dict(OSS_CFG, access_key_secret=None)
    with pytest.raises(AppError) as ei:
        _run_test("oss", cfg)
    assert ei.value.status == 422


@patch("oss2.Bucket")
@patch("oss2.Auth")
def test_run_test_oss_success(mock_auth, mock_bucket_cls):
    bucket = MagicMock()
    mock_bucket_cls.return_value = bucket
    out = _run_test("oss", OSS_CFG)
    assert out == {"ok": True}
    bucket.get_bucket_info.assert_called_once()
    mock_auth.assert_called_once_with(OSS_CFG["access_key_id"], OSS_SECRET)


@patch("oss2.Bucket")
@patch("oss2.Auth")
def test_run_test_oss_failure_redacts_secret(mock_auth, mock_bucket_cls):
    bucket = MagicMock()
    bucket.get_bucket_info.side_effect = RuntimeError(f"auth failed for {OSS_SECRET}")
    mock_bucket_cls.return_value = bucket
    out = _run_test("oss", OSS_CFG)
    assert out["ok"] is False
    assert OSS_SECRET not in out["error"]


def test_oss_test_api_masks_secret(admin):
    with patch("oss2.Bucket") as mock_bucket_cls, patch("oss2.Auth"):
        bucket = MagicMock()
        mock_bucket_cls.return_value = bucket
        r = admin.post(
            "/v1/admin/settings/oss/test",
            json={"values": {**OSS_CFG, "access_key_secret": OSS_SECRET}},
        )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert OSS_SECRET not in r.text
