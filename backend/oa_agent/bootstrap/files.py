"""data/ 下的本机文件：master.key、setup.token、bootstrap.json。"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from oa_agent.config.crypto import Cipher
from oa_agent.settings import AppSettings

log = logging.getLogger(__name__)

DB_PASSWORD_AAD = "bootstrap:database.password"


def _write_private(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(data)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows 上仅能控制只读位，权限依赖目录 ACL
        pass


def load_or_create_master_key(settings: AppSettings) -> bytes:
    if settings.master_key:
        key = base64.b64decode(settings.master_key)
        if len(key) != 32:
            raise RuntimeError("OA_AGENT_MASTER_KEY 必须是 base64 编码的 32 字节")
        return key
    path = settings.master_key_path
    if path.exists():
        key = base64.b64decode(path.read_text(encoding="utf-8").strip())
        if len(key) != 32:
            raise RuntimeError(f"{path} 内容无效")
        return key
    key = secrets.token_bytes(32)
    _write_private(path, base64.b64encode(key).decode() + "\n")
    log.warning("已生成主密钥 %s —— 请立即备份；丢失后所有密钥需重新录入", path)
    return key


def ensure_setup_token(settings: AppSettings) -> str:
    path = settings.setup_token_path
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
    else:
        token = secrets.token_urlsafe(24)
        _write_private(path, token + "\n")
    log.warning("系统未安装。安装令牌：%s （打开 /setup/ 完成安装）", token)
    return token


def read_setup_token(settings: AppSettings) -> str | None:
    path = settings.setup_token_path
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def delete_setup_token(settings: AppSettings) -> None:
    settings.setup_token_path.unlink(missing_ok=True)


@dataclass
class DbParams:
    host: str
    port: int
    user: str
    password: str
    database: str
    driver: str = "mysql"


@dataclass
class Bootstrap:
    database: DbParams
    tenant_id: str
    installed_at: str


def is_installed(settings: AppSettings) -> bool:
    return settings.bootstrap_path.exists()


def write_bootstrap(settings: AppSettings, cipher: Cipher, db: DbParams, installed_at: str | None = None) -> None:
    payload = {
        "version": 1,
        "installed_at": installed_at or datetime.now(UTC).isoformat(),
        "tenant_id": settings.tenant_id,
        "database": {
            "driver": db.driver,
            "host": db.host,
            "port": db.port,
            "user": db.user,
            "database": db.database,
            "password_enc": cipher.encrypt_b64(db.password, DB_PASSWORD_AAD),
        },
    }
    _write_private(settings.bootstrap_path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_bootstrap(settings: AppSettings, cipher: Cipher) -> Bootstrap:
    raw = json.loads(settings.bootstrap_path.read_text(encoding="utf-8"))
    d = raw["database"]
    params = DbParams(
        host=d["host"],
        port=int(d["port"]),
        user=d["user"],
        password=cipher.decrypt_b64(d["password_enc"], DB_PASSWORD_AAD),
        database=d["database"],
        driver=d.get("driver", "mysql"),
    )
    return Bootstrap(database=params, tenant_id=raw.get("tenant_id", settings.tenant_id), installed_at=raw["installed_at"])


def db_public_view(db: DbParams) -> dict:
    view = asdict(db)
    view.pop("password")
    return view
