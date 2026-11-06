"""导出文件存储：本地 data/exports/{tenant} 或阿里云 OSS。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from oa_agent.executor.executor import ToolError
from oa_agent.observability.redact import redact

log = logging.getLogger(__name__)

_TICKET_RE = re.compile(r"^[A-Za-z0-9_\-]{16,64}$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNSAFE_NAME = re.compile(r"[^0-9A-Za-z_.\-]+")

MSG_SAVE_FAILED = "文件保存失败"
MSG_NOT_FOUND = "文件不存在"


@dataclass(frozen=True)
class OssConfig:
    endpoint: str
    bucket: str
    prefix: str
    access_key_id: str
    access_key_secret: str


def oss_configured(cfg: OssConfig | None) -> bool:
    if cfg is None:
        return False
    return all(
        str(part).strip()
        for part in (cfg.endpoint, cfg.bucket, cfg.access_key_id, cfg.access_key_secret)
    )


def check_oss(endpoint: str, bucket: str, access_key_id: str, access_key_secret: str) -> dict:
    """真实探测 OSS bucket（get_bucket_info）；失败原因经 redact，且不含 secret 明文。"""
    import oss2

    secret = str(access_key_secret or "")
    try:
        auth = oss2.Auth(access_key_id, secret)
        bucket_obj = oss2.Bucket(auth, endpoint, bucket)
        bucket_obj.get_bucket_info()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001 —— 测试连接需如实返回任意失败原因
        msg = f"{type(exc).__name__}: {exc}"
        if secret:
            msg = msg.replace(secret, "***")
        return {"ok": False, "error": redact(msg)}


def _safe_segment(value: str) -> str:
    seg = _UNSAFE_NAME.sub("_", str(value or "")).strip("._")
    return seg or "default"


class ExportStore:
    def __init__(
        self,
        *,
        data_dir: Path,
        tenant_id: str,
        oss: OssConfig | None = None,
        oss_client=None,
    ):
        self.data_dir = Path(data_dir)
        self._tenant = _safe_segment(tenant_id)
        self.oss = oss
        self._oss_client = oss_client

    def object_key_for(self, ticket: str) -> str:
        """local: {tenant}/{ticket}.bin；oss: {prefix}/{tenant}/{ticket}.bin（prefix 可空）"""
        self._require_ticket(ticket)
        rel = f"{self._tenant}/{ticket}.bin"
        if not oss_configured(self.oss):
            return rel
        prefix = (self.oss.prefix or "").strip().strip("/")
        if prefix:
            return f"{prefix}/{rel}"
        return rel

    def put(self, ticket: str, data: bytes) -> tuple[str, str]:
        """返回 (storage, object_key)；oss 配齐走 OSS，否则 local。OSS put 失败不写 local。"""
        key = self.object_key_for(ticket)
        if oss_configured(self.oss):
            try:
                self._oss_bucket().put_object(key, data)
            except ToolError:
                raise
            except Exception as exc:
                raise ToolError("EXPORT_STORE_FAILED", MSG_SAVE_FAILED) from exc
            return ("oss", key)
        path = self._local_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise ToolError("EXPORT_STORE_FAILED", MSG_SAVE_FAILED) from exc
        return ("local", key)

    def get(self, storage: str, object_key: str) -> bytes:
        """按行上 storage 读取；本地路径必须落在租户导出根下。"""
        key = self._normalized_key(object_key)
        if storage == "oss":
            try:
                return self._oss_bucket().get_object(key).read()
            except ToolError:
                raise
            except Exception as exc:
                raise ToolError("NOT_FOUND", MSG_NOT_FOUND, user_message=MSG_NOT_FOUND) from exc
        if storage != "local":
            raise ToolError("NOT_FOUND", MSG_NOT_FOUND, user_message=MSG_NOT_FOUND)
        path = self._local_path(key)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ToolError("NOT_FOUND", MSG_NOT_FOUND, user_message=MSG_NOT_FOUND) from exc

    def delete(self, storage: str, object_key: str) -> None:
        """尽力删除（insert 失败回滚用）；忽略不存在。"""
        try:
            key = self._normalized_key(object_key)
        except ToolError:
            return
        if storage == "oss":
            try:
                self._oss_bucket().delete_object(key)
            except Exception as exc:
                log.warning("export delete oss failed: %s", type(exc).__name__)
            return
        if storage != "local":
            return
        try:
            self._local_path(key).unlink(missing_ok=True)
        except (OSError, ToolError) as exc:
            log.warning("export delete local failed: %s", type(exc).__name__)

    def _oss_bucket(self):
        if self._oss_client is not None:
            return self._oss_client
        if not oss_configured(self.oss):
            raise ToolError("EXPORT_STORE_FAILED", MSG_SAVE_FAILED)
        import oss2

        cfg = self.oss
        auth = oss2.Auth(cfg.access_key_id, cfg.access_key_secret)
        self._oss_client = oss2.Bucket(auth, cfg.endpoint, cfg.bucket)
        return self._oss_client

    def _tenant_root(self) -> Path:
        return (self.data_dir / "exports" / self._tenant).resolve()

    def _local_path(self, object_key: str) -> Path:
        tenant_root = self._tenant_root()
        target = (self.data_dir / "exports" / object_key).resolve()
        if not target.is_relative_to(tenant_root):
            raise ToolError("PATH_NOT_ALLOWED", "对象键越出租户目录", user_message=MSG_NOT_FOUND)
        return target

    def _normalized_key(self, object_key: str) -> str:
        if not isinstance(object_key, str) or not object_key.strip():
            raise ToolError("PATH_NOT_ALLOWED", "对象键无效", user_message=MSG_NOT_FOUND)
        key = object_key.replace("\\", "/").strip()
        if key.startswith("/") or _DRIVE_RE.match(key) or "://" in key:
            raise ToolError("PATH_NOT_ALLOWED", "对象键无效", user_message=MSG_NOT_FOUND)
        if ".." in key.split("/") or "\x00" in key:
            raise ToolError("PATH_NOT_ALLOWED", "对象键无效", user_message=MSG_NOT_FOUND)
        parts = [p for p in key.split("/") if p and p != "."]
        if not parts:
            raise ToolError("PATH_NOT_ALLOWED", "对象键无效", user_message=MSG_NOT_FOUND)
        return "/".join(parts)

    def _require_ticket(self, ticket: str) -> None:
        if not _TICKET_RE.match(ticket or ""):
            raise ToolError("INVALID_ARGUMENT", "票据无效")
