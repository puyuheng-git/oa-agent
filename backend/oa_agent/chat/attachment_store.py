"""Employee uploads: content-addressed by SHA-256 via ExportStore."""

from __future__ import annotations

import hashlib

from oa_agent.executor.executor import ToolError
from oa_agent.executor.export_store import ExportStore, MSG_SAVE_FAILED, oss_configured

MSG_ATTACHMENT_CORRUPT = "\u9644\u4ef6\u5df2\u635f\u574f\u6216\u65e0\u6cd5\u8bfb\u53d6\uff0c\u8bf7\u91cd\u65b0\u4e0a\u4f20"


def upload_object_key(tenant: str, sha256: str, prefix: str = "") -> str:
    body = f"{tenant}/attachments/v1/objects/{sha256[:2]}/{sha256}"
    prefix = prefix.strip().strip("/")
    return f"{prefix}/{body}" if prefix else body


def _object_key_for_store(store: ExportStore, sha256: str) -> str:
    prefix = ""
    if oss_configured(store.oss):
        prefix = (store.oss.prefix or "").strip().strip("/")
    return upload_object_key(store._tenant, sha256, prefix)


def put_upload(store: ExportStore, data: bytes) -> tuple[str, str, str]:
    digest = hashlib.sha256(data).hexdigest()
    key = _object_key_for_store(store, digest)
    if oss_configured(store.oss):
        bucket = store._oss_bucket()
        try:
            if bucket.object_exists(key):
                return ("oss", key, digest)
            bucket.put_object(key, data)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError("EXPORT_STORE_FAILED", MSG_SAVE_FAILED) from exc
        return ("oss", key, digest)
    path = store._local_path(key)
    if path.is_file():
        return ("local", key, digest)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        raise ToolError("EXPORT_STORE_FAILED", MSG_SAVE_FAILED) from exc
    return ("local", key, digest)


def read_upload(store: ExportStore, storage: str, object_key: str, sha256: str) -> bytes:
    data = store.get(storage, object_key)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ToolError(
            "ATTACHMENT_CORRUPT",
            MSG_ATTACHMENT_CORRUPT,
            user_message=MSG_ATTACHMENT_CORRUPT,
        )
    return data
