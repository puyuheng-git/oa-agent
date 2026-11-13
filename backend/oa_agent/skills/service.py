"""Agent Skill 包业务：启用解析、CRUD、市场、调用计数。"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import SkillMarketListing, SkillPack, SkillPackVersion, UserSkillPack
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.skills.github_import import import_from_github
from oa_agent.skills.parse import SkillMdError, parse_skill_md
from oa_agent.skills.pack_store import load_bundle_files, save_pack_version

log = logging.getLogger(__name__)


@dataclass
class SkillPackState:
    id: int
    name: str
    display_name: str
    description: str
    kind: str
    enabled: bool
    origin: str = "system"
    invoke_count: int = 0
    source: str = ""
    owner_oa: str | None = None
    version_no: int = 0
    storage_path: str = ""
    skill_md: str = ""
    loaded_body: bool = False
    files: list[str] = field(default_factory=list)


def pack_bundle_dir(data_dir: Path, storage_path: str) -> Path:
    return Path(data_dir) / storage_path


def _version(db: Session, pack: SkillPack) -> SkillPackVersion | None:
    if not pack.current_version_id:
        return None
    return db.get(SkillPackVersion, pack.current_version_id)


def _state(pack: SkillPack, version: SkillPackVersion | None, *, enabled: bool, origin: str) -> SkillPackState:
    meta = (version.bundle_meta or {}) if version else {}
    files = [f["path"] for f in (meta.get("files") or []) if isinstance(f, dict) and f.get("path")]
    return SkillPackState(
        id=pack.id,
        name=pack.name,
        display_name=pack.display_name or pack.name,
        description=pack.description or "",
        kind=pack.kind,
        enabled=enabled,
        origin=origin,
        invoke_count=int(pack.invoke_count or 0),
        source=pack.source,
        owner_oa=pack.owner_oa,
        version_no=version.version_no if version else 0,
        storage_path=version.storage_path if version else "",
        skill_md="",
        files=files,
    )


def enabled_packs_for(db: Session, *, tenant_id: str, oa: str) -> list[SkillPackState]:
    """系统包（仅看后台 enabled_default）+ 员工自建/市场安装且启用的包。"""
    packs = list(db.scalars(sa.select(SkillPack).where(SkillPack.tenant_id == tenant_id)).all())
    if not packs:
        return []
    user_rows = {
        r.pack_id: r
        for r in db.scalars(
            sa.select(UserSkillPack).where(UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa)
        ).all()
    }
    out: list[SkillPackState] = []
    for pack in packs:
        version = _version(db, pack)
        row = user_rows.get(pack.id)
        if pack.kind == "system":
            # 系统包由后台默认启停；不进入用户库，也不接受个人覆盖
            if not pack.enabled_default:
                continue
            out.append(_state(pack, version, enabled=True, origin="system"))
            continue
        # user / 安装包：必须有 user_skill 且 enabled
        if row is None or not row.enabled:
            continue
        # 非本人自建包仅当 market_install 可见
        if pack.owner_oa and pack.owner_oa != oa and row.origin != "market_install":
            continue
        out.append(_state(pack, version, enabled=True, origin=row.origin))
    return out


def list_user_library(db: Session, *, tenant_id: str, oa: str) -> list[dict[str, Any]]:
    """员工 Skill 管理页：仅本人自建 + 市场安装；系统包不出现在此列表。"""
    packs = list(db.scalars(sa.select(SkillPack).where(SkillPack.tenant_id == tenant_id)).all())
    user_rows = {
        r.pack_id: r
        for r in db.scalars(
            sa.select(UserSkillPack).where(UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa)
        ).all()
    }
    listings = {
        r.pack_id: r
        for r in db.scalars(
            sa.select(SkillMarketListing).where(
                SkillMarketListing.tenant_id == tenant_id,
                SkillMarketListing.status == "published",
            )
        ).all()
    }
    items: list[dict[str, Any]] = []
    for pack in packs:
        if pack.kind == "system":
            continue
        row = user_rows.get(pack.id)
        version = _version(db, pack)
        if pack.owner_oa == oa:
            enabled = row.enabled if row is not None else True
            items.append(_pack_dict(pack, version, enabled=enabled, origin=row.origin if row else "created",
                                    in_library=True, listed=pack.id in listings))
            continue
        if row is not None and row.origin == "market_install":
            items.append(_pack_dict(pack, version, enabled=row.enabled, origin="market_install",
                                    in_library=True, listed=pack.id in listings))
    items.sort(key=lambda x: (x["name"],))
    return items


def _pack_dict(pack: SkillPack, version: SkillPackVersion | None, *, enabled: bool, origin: str,
               in_library: bool, listed: bool) -> dict[str, Any]:
    return {
        "id": pack.id,
        "name": pack.name,
        "display_name": pack.display_name or pack.name,
        "description": pack.description or "",
        "kind": pack.kind,
        "source": pack.source,
        "source_url": pack.source_url or "",
        "owner_oa": pack.owner_oa,
        "enabled": enabled,
        "origin": origin,
        "invoke_count": int(pack.invoke_count or 0),
        "version_no": version.version_no if version else 0,
        "in_library": in_library,
        "listed": listed,
        "updated_at": pack.updated_at,
    }


def load_skill_body(db: Session, data_dir: Path, pack_id: int) -> str:
    pack = db.get(SkillPack, pack_id)
    if pack is None:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    version = _version(db, pack)
    if version is None:
        raise AppError(404, "NOT_FOUND", "Skill 包无版本")
    return version.skill_md


def bump_invoke(db: Session, pack_id: int, *, amount: int = 1) -> None:
    pack = db.get(SkillPack, pack_id)
    if pack is None:
        return
    pack.invoke_count = int(pack.invoke_count or 0) + amount
    pack.updated_at = utcnow()
    listing = db.scalar(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == pack.tenant_id,
            SkillMarketListing.pack_id == pack_id,
            SkillMarketListing.status == "published",
        )
    )
    if listing is not None:
        listing.invoke_count = int(pack.invoke_count or 0)
        listing.updated_at = utcnow()


def import_github_packs(
    db: Session,
    *,
    tenant_id: str,
    data_dir: Path,
    url: str,
    paths: list[str] | None,
    operator: str,
    kind: str = "system",
) -> list[dict[str, Any]]:
    try:
        bundles = import_from_github(url, paths=paths)
    except SkillMdError as exc:
        raise AppError(422, "IMPORT_FAILED", exc.message) from None
    results: list[dict[str, Any]] = []
    for item in bundles:
        files = item["files"]
        try:
            parsed = parse_skill_md((files.get("SKILL.md") or files.get("skill.md") or b"").decode("utf-8"))
        except (SkillMdError, UnicodeDecodeError) as exc:
            msg = getattr(exc, "message", str(exc))
            results.append({"dir": item["dir"], "ok": False, "errors": [msg]})
            continue
        pack = db.scalar(
            sa.select(SkillPack).where(SkillPack.tenant_id == tenant_id, SkillPack.name == parsed["name"])
        )
        if pack is None:
            pack = SkillPack(
                tenant_id=tenant_id,
                name=parsed["name"],
                kind=kind,
                source="github",
                source_url=url,
                enabled_default=True,
                created_by=operator,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(pack)
            db.flush()
        else:
            pack.source = "github"
            pack.source_url = url
            pack.kind = kind
            pack.updated_at = utcnow()
        try:
            version = save_pack_version(db, pack=pack, files=files, data_dir=data_dir, operator=operator)
        except SkillMdError as exc:
            results.append({"dir": item["dir"], "ok": False, "errors": [exc.message]})
            continue
        results.append({
            "dir": item["dir"], "ok": True, "errors": [],
            "name": pack.name, "id": pack.id, "version_no": version.version_no,
        })
    return results


def create_user_pack(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    data_dir: Path,
    skill_md: str,
    extra_files: dict[str, bytes] | None = None,
) -> SkillPack:
    files = {"SKILL.md": skill_md.encode("utf-8")}
    if extra_files:
        files.update(extra_files)
    try:
        parsed = parse_skill_md(skill_md)
    except SkillMdError as exc:
        raise AppError(422, "VALIDATION_ERROR", exc.message) from None
    existing = db.scalar(
        sa.select(SkillPack).where(SkillPack.tenant_id == tenant_id, SkillPack.name == parsed["name"])
    )
    if existing is not None:
        raise AppError(409, "ALREADY_EXISTS", f"Skill 名 {parsed['name']} 已被占用")
    pack = SkillPack(
        tenant_id=tenant_id,
        name=parsed["name"],
        kind="user",
        source="editor",
        owner_oa=oa,
        enabled_default=False,
        created_by=oa,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(pack)
    db.flush()
    try:
        save_pack_version(db, pack=pack, files=files, data_dir=data_dir, operator=oa)
    except SkillMdError as exc:
        raise AppError(422, "VALIDATION_ERROR", exc.message) from None
    db.add(UserSkillPack(
        tenant_id=tenant_id, oa=oa, pack_id=pack.id, enabled=True, origin="created",
        created_at=utcnow(), updated_at=utcnow(),
    ))
    return pack


def update_user_pack(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    pack_id: int,
    data_dir: Path,
    skill_md: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> SkillPack:
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    if pack.kind == "system" or pack.owner_oa != oa:
        raise AppError(403, "FORBIDDEN", "只能编辑自己创建的 Skill")
    version = _version(db, pack)
    if version is None:
        raise AppError(404, "NOT_FOUND", "Skill 包无版本")
    root = pack_bundle_dir(data_dir, version.storage_path)
    files = load_bundle_files(root)
    if skill_md is not None:
        files["SKILL.md"] = skill_md.encode("utf-8")
    if extra_files:
        files.update(extra_files)
    try:
        save_pack_version(db, pack=pack, files=files, data_dir=data_dir, operator=oa)
    except SkillMdError as exc:
        raise AppError(422, "VALIDATION_ERROR", exc.message) from None
    return pack


def set_pack_enabled(db: Session, *, tenant_id: str, oa: str, pack_id: int, enabled: bool) -> None:
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    if pack.kind == "system":
        raise AppError(403, "FORBIDDEN", "系统 Skill 由后台统一配置，员工不可启停")
    row = db.scalar(
        sa.select(UserSkillPack).where(
            UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa, UserSkillPack.pack_id == pack_id,
        )
    )
    if row is None:
        if pack.owner_oa != oa:
            raise AppError(404, "NOT_FOUND", "未安装该 Skill")
        row = UserSkillPack(
            tenant_id=tenant_id, oa=oa, pack_id=pack_id, enabled=enabled, origin="created",
            created_at=utcnow(), updated_at=utcnow(),
        )
        db.add(row)
        return
    row.enabled = enabled
    row.updated_at = utcnow()


def delete_user_pack(db: Session, *, tenant_id: str, oa: str, pack_id: int, data_dir: Path) -> None:
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    if pack.kind == "system" or pack.owner_oa != oa:
        raise AppError(403, "FORBIDDEN", "只能删除自己创建的 Skill")
    listing = db.scalar(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == tenant_id, SkillMarketListing.pack_id == pack_id,
        )
    )
    if listing is not None:
        listing.status = "withdrawn"
        listing.updated_at = utcnow()
    db.execute(sa.delete(UserSkillPack).where(UserSkillPack.pack_id == pack_id))
    versions = list(db.scalars(sa.select(SkillPackVersion).where(SkillPackVersion.pack_id == pack_id)).all())
    for v in versions:
        path = pack_bundle_dir(data_dir, v.storage_path)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        db.delete(v)
    db.delete(pack)


def publish_to_market(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    pack_id: int,
    description: str | None = None,
) -> SkillMarketListing:
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    if pack.owner_oa != oa or pack.kind != "user":
        raise AppError(403, "FORBIDDEN", "只能上架自己创建的 Skill")
    market_desc = (description if description is not None else "").strip()
    if not market_desc:
        market_desc = (pack.description or "").strip()
    if len(market_desc) > 1024:
        raise AppError(422, "VALIDATION_ERROR", "市场描述不能超过 1024 字")
    if not market_desc:
        raise AppError(422, "VALIDATION_ERROR", "请填写市场描述")
    listing = db.scalar(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == tenant_id, SkillMarketListing.pack_id == pack_id,
        )
    )
    if listing is None:
        listing = SkillMarketListing(
            tenant_id=tenant_id,
            pack_id=pack_id,
            publisher_oa=oa,
            description=market_desc,
            status="published",
            invoke_count=int(pack.invoke_count or 0),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(listing)
    else:
        listing.status = "published"
        listing.publisher_oa = oa
        listing.description = market_desc
        listing.invoke_count = int(pack.invoke_count or 0)
        listing.updated_at = utcnow()
    return listing


def withdraw_from_market(db: Session, *, tenant_id: str, oa: str, pack_id: int) -> None:
    listing = db.scalar(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == tenant_id, SkillMarketListing.pack_id == pack_id,
        )
    )
    if listing is None:
        raise AppError(404, "NOT_FOUND", "未上架")
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.owner_oa != oa:
        raise AppError(403, "FORBIDDEN", "只能下架自己发布的 Skill")
    listing.status = "withdrawn"
    listing.updated_at = utcnow()


def list_market(db: Session, *, tenant_id: str, oa: str, q: str = "") -> list[dict[str, Any]]:
    rows = list(db.scalars(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == tenant_id,
            SkillMarketListing.status == "published",
        ).order_by(SkillMarketListing.invoke_count.desc(), SkillMarketListing.id.desc())
    ).all())
    installed = {
        r.pack_id
        for r in db.scalars(
            sa.select(UserSkillPack).where(UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa)
        ).all()
    }
    query = (q or "").strip().lower()
    items: list[dict[str, Any]] = []
    for listing in rows:
        pack = db.get(SkillPack, listing.pack_id)
        if pack is None:
            continue
        version = _version(db, pack)
        market_desc = (listing.description or pack.description or "").strip()
        if query and query not in pack.name.lower() and query not in (pack.display_name or "").lower() \
                and query not in (pack.description or "").lower() \
                and query not in market_desc.lower():
            continue
        items.append({
            **_pack_dict(pack, version, enabled=True, origin="market", in_library=pack.id in installed,
                         listed=True),
            "publisher_oa": listing.publisher_oa,
            "market_description": market_desc,
            "market_invoke_count": int(listing.invoke_count or 0),
            "installed": pack.id in installed or pack.owner_oa == oa,
        })
    return items


def install_from_market(db: Session, *, tenant_id: str, oa: str, pack_id: int) -> UserSkillPack:
    listing = db.scalar(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == tenant_id,
            SkillMarketListing.pack_id == pack_id,
            SkillMarketListing.status == "published",
        )
    )
    if listing is None:
        raise AppError(404, "NOT_FOUND", "市场中不存在该 Skill")
    pack = db.get(SkillPack, pack_id)
    if pack is None:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    if pack.owner_oa == oa:
        # 作者自己：确保库内启用
        set_pack_enabled(db, tenant_id=tenant_id, oa=oa, pack_id=pack_id, enabled=True)
        row = db.scalar(
            sa.select(UserSkillPack).where(
                UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa, UserSkillPack.pack_id == pack_id,
            )
        )
        assert row is not None
        return row
    row = db.scalar(
        sa.select(UserSkillPack).where(
            UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa, UserSkillPack.pack_id == pack_id,
        )
    )
    if row is None:
        row = UserSkillPack(
            tenant_id=tenant_id, oa=oa, pack_id=pack_id, enabled=True, origin="market_install",
            created_at=utcnow(), updated_at=utcnow(),
        )
        db.add(row)
    else:
        row.enabled = True
        row.origin = "market_install"
        row.updated_at = utcnow()
    return row


SKILL_CREATOR_MD = """---
name: skill-creator
display_name: Skill 创建助手
description: Create a personal Agent Skill from natural language. Use when the employee wants to create a skill, write SKILL.md, teach the assistant a reusable personal workflow, or save instructions as their own Skill.
---

# Skill Creator（创建个人 Skill）

当员工要用自然语言创建**自己的** Skill 时按本说明执行。系统 Skill 由管理员配置，不要替员工创建系统包。

## 步骤

1. 与员工确认：Skill 英文名（小写字母/数字/连字符，如 `my-leave-tips`）、一句话描述（何时使用）、正文指引。
2. 起草完整 `SKILL.md`（必须含 YAML frontmatter）：

```markdown
---
name: example-skill
description: Use when …（含触发关键词）
---

# 标题

## 使用说明

分步骤写给助手的指引。
```

3. 调用工具 **builtin.skill_create**，参数 `skill_md` = 完整 Markdown 正文。
4. 用返回的 `name` / `display_name` 向员工确认已创建；之后该 Skill 会出现在「我的 Skill」，并在对话中自动可用。

## 注意

- 不要编造未确认的业务规则；不确定就先问员工。
- 同名 Skill 已存在时工具会报错，请换名或让员工先在工作空间编辑已有 Skill。
- 需要跑脚本的能力仍用其他系统 Skill + `builtin.skill_exec`；本工具只负责落盘个人 SKILL.md。
"""


def ensure_system_skill_packs(db: Session, *, tenant_id: str, data_dir: Path) -> int:
    """幂等写入内置系统包（如 skill-creator）；已存在则跳过。"""
    seeds = {
        "skill-creator": SKILL_CREATOR_MD,
    }
    created = 0
    for name, skill_md in seeds.items():
        exists = db.scalar(
            sa.select(SkillPack.id).where(SkillPack.tenant_id == tenant_id, SkillPack.name == name)
        )
        if exists is not None:
            continue
        try:
            parsed = parse_skill_md(skill_md)
        except SkillMdError:
            log.exception("系统 Skill 包种子解析失败 name=%s", name)
            continue
        pack = SkillPack(
            tenant_id=tenant_id,
            name=parsed["name"],
            display_name="Skill 创建助手" if name == "skill-creator" else parsed["name"],
            description=parsed["description"],
            kind="system",
            source="builtin",
            enabled_default=True,
            created_by="system",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.add(pack)
        db.flush()
        try:
            save_pack_version(
                db, pack=pack, files={"SKILL.md": skill_md.encode("utf-8")},
                data_dir=data_dir, operator="system",
            )
        except SkillMdError:
            log.exception("系统 Skill 包落盘失败 name=%s", name)
            continue
        created += 1
        log.info("已写入系统 Skill 包：%s", name)
    return created


def admin_list_packs(db: Session, *, tenant_id: str) -> list[dict[str, Any]]:
    packs = list(db.scalars(
        sa.select(SkillPack).where(SkillPack.tenant_id == tenant_id).order_by(SkillPack.kind, SkillPack.name)
    ).all())
    out = []
    for pack in packs:
        version = _version(db, pack)
        out.append(_pack_dict(pack, version, enabled=bool(pack.enabled_default), origin=pack.kind,
                              in_library=True, listed=False))
    return out


def admin_set_system_default(db: Session, *, tenant_id: str, pack_id: int, enabled_default: bool) -> SkillPack:
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    if pack.kind != "system":
        raise AppError(422, "VALIDATION_ERROR", "只能设置系统包默认启停")
    pack.enabled_default = enabled_default
    pack.updated_at = utcnow()
    return pack
