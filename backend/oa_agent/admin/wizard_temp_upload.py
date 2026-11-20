"""导入向导：文件型参数测试用的临时落盘（runtime/wizard-temp/，已 gitignore）。"""

from __future__ import annotations

import hashlib
import re
import time
import uuid

from oa_agent.settings import REPO_ROOT

TEMP_DIR = REPO_ROOT / "runtime" / "wizard-temp"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
# 临时文件保留时长（秒）：超过即在下次上传时清理
TEMP_TTL_SECONDS = 24 * 3600


def _purge_expired(now: float | None = None) -> int:
    """删除 TEMP_DIR 下修改时间早于 TTL 的文件，返回删除数量；单个文件失败不影响上传。"""
    cutoff = (time.time() if now is None else now) - TEMP_TTL_SECONDS
    removed = 0
    for p in TEMP_DIR.iterdir():
        try:
            # 只清理普通文件，跳过目录/符号链接
            if p.is_file() and not p.is_symlink() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def save_wizard_temp_file(data: bytes, filename: str) -> dict:
    """落盘临时文件，返回 {ref, filename, sha256, size}；ref 为绝对路径，filename 为净化后的文件名。
    写入前顺带清理超过 24 小时的旧文件。"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    _purge_expired()
    digest = hashlib.sha256(data).hexdigest()
    # 只保留安全字符并限长，避免路径穿越与超长文件名
    safe = _SAFE.sub("_", (filename or "file").strip())[:120] or "file"
    path = TEMP_DIR / f"{uuid.uuid4().hex}_{safe}"
    path.write_bytes(data)
    return {"ref": str(path.resolve()), "filename": safe, "sha256": digest, "size": len(data)}
