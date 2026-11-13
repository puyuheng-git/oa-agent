"""Skill 包落盘与版本写入。"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import SkillPack, SkillPackVersion
from oa_agent.db.types import utcnow
from oa_agent.skills.parse import SkillMdError, parse_skill_md

ALLOWED_EXT = frozenset({
    ".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yaml", ".yml",
    ".html", ".css", ".csv", ".tsv", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".pdf", ".docx", ".xlsx", ".pptx", ".dotx", ".potx", ".xlsm", "",
})
MAX_FILES = 200
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
_SAFE_REL = re.compile(r"^[A-Za-z0-9_./\-]+$")


def _seg(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", value)[:64] or "x"


def _norm_rel(path: str) -> str:
    rel = path.replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/") or not _SAFE_REL.fullmatch(rel):
        raise SkillMdError(f"非法路径：{path}")
    name = Path(rel).name
    if name.upper() == "SKILL.MD":
        return "SKILL.md"
    suffix = Path(rel).suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise SkillMdError(f"不允许的文件类型：{path}")
    return rel


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_files(files: dict[str, bytes]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for path, data in files.items():
        rel = _norm_rel(path)
        if not isinstance(data, (bytes, bytearray)):
            raise SkillMdError(f"{rel} 内容无效")
        out[rel] = bytes(data)
    return out


def validate_bundle(files: dict[str, bytes]) -> tuple[str, list[dict[str, Any]], str]:
    """校验包文件；返回 (bundle_hash, meta_files, skill_md_text)。"""
    normalized = normalize_files(files)
    if "SKILL.md" not in normalized:
        raise SkillMdError("缺少 SKILL.md")
    if len(normalized) > MAX_FILES:
        raise SkillMdError(f"文件数不能超过 {MAX_FILES}")
    total = 0
    meta: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for rel in sorted(normalized):
        raw = normalized[rel]
        if len(raw) > MAX_FILE_BYTES:
            raise SkillMdError(f"{rel} 超过单文件上限")
        total += len(raw)
        if total > MAX_TOTAL_BYTES:
            raise SkillMdError("包总体积过大")
        h = hash_bytes(raw)
        digest.update(rel.encode("utf-8"))
        digest.update(h.encode("utf-8"))
        meta.append({"path": rel, "size": len(raw), "sha256": h})
    try:
        skill_text = normalized["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillMdError("SKILL.md 必须是 UTF-8") from exc
    parse_skill_md(skill_text)
    return digest.hexdigest(), meta, skill_text


def write_bundle(data_dir: Path, tenant_id: str, pack_id: int, version_no: int,
                 files: dict[str, bytes]) -> str:
    """写入磁盘，返回相对 data_dir 的 storage_path。"""
    normalized = normalize_files(files)
    rel_dir = f"skill_packs/{_seg(tenant_id)}/{pack_id}/v{version_no}"
    target = Path(data_dir) / rel_dir
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for rel, data in normalized.items():
        out = target / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    return rel_dir.replace("\\", "/")


def load_bundle_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if not root.is_dir():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            rel = _norm_rel(rel)
        except SkillMdError:
            continue
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            continue
        files[rel] = data
    return files


def save_pack_version(
    db: Session,
    *,
    pack: SkillPack,
    files: dict[str, bytes],
    data_dir: Path,
    operator: str,
) -> SkillPackVersion:
    bundle_hash, meta, skill_text = validate_bundle(files)
    parsed = parse_skill_md(skill_text)
    version_no = 1
    if pack.id:
        version_no = (db.scalar(sa.select(sa.func.max(SkillPackVersion.version_no))
                                .where(SkillPackVersion.pack_id == pack.id)) or 0) + 1
    pack.name = parsed["name"]
    pack.display_name = parsed["display_name"]
    pack.description = parsed["description"]
    pack.bundle_hash = bundle_hash
    pack.updated_at = utcnow()
    db.flush()
    storage = write_bundle(data_dir, pack.tenant_id, pack.id, version_no, files)
    version = SkillPackVersion(
        pack_id=pack.id,
        version_no=version_no,
        skill_md=skill_text,
        bundle_meta={"files": meta},
        content_hash=bundle_hash,
        storage_path=storage,
        created_by=operator,
        created_at=utcnow(),
    )
    db.add(version)
    db.flush()
    pack.current_version_id = version.id
    return version
