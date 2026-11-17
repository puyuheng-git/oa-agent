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


# 市场上架状态：仅 published 对全员可见
_MARKET_ACTIVE = frozenset({"pending_admin", "published", "rejected"})


def list_user_library(db: Session, *, tenant_id: str, oa: str) -> list[dict[str, Any]]:
    """员工「我的 Skill」：仅本人自建 + 市场安装；后台系统包不展示（仍注入系统提示词）。"""
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
                SkillMarketListing.status.in_(list(_MARKET_ACTIVE)),
            )
        ).all()
    }
    items: list[dict[str, Any]] = []
    for pack in packs:
        if pack.kind == "system":
            continue
        row = user_rows.get(pack.id)
        version = _version(db, pack)
        listing = listings.get(pack.id)
        if pack.owner_oa == oa:
            enabled = row.enabled if row is not None else True
            items.append(_pack_dict(
                pack, version, enabled=enabled, origin=row.origin if row else "created",
                in_library=True, listed=listing is not None and listing.status != "withdrawn",
                listing=listing,
            ))
            continue
        if row is not None and row.origin == "market_install":
            items.append(_pack_dict(
                pack, version, enabled=row.enabled, origin="market_install",
                in_library=True, listed=False, listing=None,
            ))
    items.sort(key=lambda x: x["name"])
    return items


def _pack_dict(
    pack: SkillPack,
    version: SkillPackVersion | None,
    *,
    enabled: bool,
    origin: str,
    in_library: bool,
    listed: bool,
    listing: SkillMarketListing | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
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
    if listing is not None:
        data.update(_listing_public(listing))
    return data


def _listing_public(listing: SkillMarketListing) -> dict[str, Any]:
    return {
        "market_status": listing.status,
        "market_description": listing.description or "",
        "model_review_status": listing.model_review_status or "",
        "model_review_summary": listing.model_review_summary or "",
        "model_review_recommend": listing.model_review_recommend or "",
        "model_reviewed_at": listing.model_reviewed_at,
        "admin_note": listing.admin_note or "",
        "admin_reviewer": listing.admin_reviewer or "",
        "admin_reviewed_at": listing.admin_reviewed_at,
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


def _user_library_row(db: Session, *, tenant_id: str, oa: str, pack_id: int) -> UserSkillPack | None:
    return db.scalar(
        sa.select(UserSkillPack).where(
            UserSkillPack.tenant_id == tenant_id, UserSkillPack.oa == oa, UserSkillPack.pack_id == pack_id,
        )
    )


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
    row = _user_library_row(db, tenant_id=tenant_id, oa=oa, pack_id=pack_id)
    # 本人创建、市场安装到自己库、或系统包均可改正文
    if pack.owner_oa != oa and pack.kind != "system" and (row is None or row.origin != "market_install"):
        raise AppError(403, "FORBIDDEN", "只能编辑自己库中的 Skill")
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
    # 系统包仅后台可改；对话页「我的 Skill」不再展示系统包
    if pack.kind == "system":
        raise AppError(403, "FORBIDDEN", "系统 Skill 由后台统一启停，无法在对话页修改")
    row = _user_library_row(db, tenant_id=tenant_id, oa=oa, pack_id=pack_id)
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


def _purge_pack(db: Session, *, pack: SkillPack, data_dir: Path) -> None:
    """彻底删除包、版本文件与全员安装记录。"""
    listing = db.scalar(
        sa.select(SkillMarketListing).where(
            SkillMarketListing.tenant_id == pack.tenant_id, SkillMarketListing.pack_id == pack.id,
        )
    )
    if listing is not None:
        listing.status = "withdrawn"
        listing.updated_at = utcnow()
    db.execute(sa.delete(UserSkillPack).where(UserSkillPack.pack_id == pack.id))
    versions = list(db.scalars(sa.select(SkillPackVersion).where(SkillPackVersion.pack_id == pack.id)).all())
    for v in versions:
        path = pack_bundle_dir(data_dir, v.storage_path)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        db.delete(v)
    db.delete(pack)


def delete_user_pack(db: Session, *, tenant_id: str, oa: str, pack_id: int, data_dir: Path) -> None:
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    row = _user_library_row(db, tenant_id=tenant_id, oa=oa, pack_id=pack_id)
    # 市场安装：只从个人库移除，不删原包
    if row is not None and row.origin == "market_install" and pack.owner_oa != oa:
        db.delete(row)
        return
    if pack.owner_oa == oa or pack.kind == "system":
        _purge_pack(db, pack=pack, data_dir=data_dir)
        return
    raise AppError(403, "FORBIDDEN", "只能删除自己库中的 Skill")


def admin_update_pack(
    db: Session,
    *,
    tenant_id: str,
    pack_id: int,
    data_dir: Path,
    skill_md: str,
    operator: str,
) -> SkillPack:
    """管理端更新任意 Skill 包正文。"""
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    version = _version(db, pack)
    if version is None:
        raise AppError(404, "NOT_FOUND", "Skill 包无版本")
    root = pack_bundle_dir(data_dir, version.storage_path)
    files = load_bundle_files(root)
    files["SKILL.md"] = skill_md.encode("utf-8")
    try:
        save_pack_version(db, pack=pack, files=files, data_dir=data_dir, operator=operator)
    except SkillMdError as exc:
        raise AppError(422, "VALIDATION_ERROR", exc.message) from None
    return pack


def admin_delete_pack(db: Session, *, tenant_id: str, pack_id: int, data_dir: Path) -> None:
    """管理端删除任意 Skill 包。"""
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    _purge_pack(db, pack=pack, data_dir=data_dir)


def publish_to_market(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    pack_id: int,
    description: str | None = None,
) -> SkillMarketListing:
    """提交上架：写入待审记录（模型审查由调用方随后写入）。"""
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
    now = utcnow()
    if listing is None:
        listing = SkillMarketListing(
            tenant_id=tenant_id,
            pack_id=pack_id,
            publisher_oa=oa,
            description=market_desc,
            status="pending_admin",
            invoke_count=int(pack.invoke_count or 0),
            model_review_status="",
            model_review_summary="",
            model_review_recommend="",
            admin_note="",
            admin_reviewer="",
            admin_reviewed_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(listing)
    else:
        if listing.status == "published":
            raise AppError(409, "ALREADY_PUBLISHED", "该 Skill 已在市场中，请先下架再重新推送")
        listing.status = "pending_admin"
        listing.publisher_oa = oa
        listing.description = market_desc
        listing.invoke_count = int(pack.invoke_count or 0)
        listing.admin_note = ""
        listing.admin_reviewer = ""
        listing.admin_reviewed_at = None
        listing.updated_at = now
    return listing


def apply_model_review(
    listing: SkillMarketListing,
    *,
    status: str,
    summary: str,
    recommend: str,
) -> None:
    """写回模型审查结果（不改变 pending_admin，仍待管理员终审）。"""
    listing.model_review_status = status
    listing.model_review_summary = (summary or "")[:8000]
    listing.model_review_recommend = recommend or ""
    listing.model_reviewed_at = utcnow()
    listing.updated_at = utcnow()


def run_model_skill_review(
    *,
    vault,
    tenant_id: str,
    db: Session,
    pack: SkillPack,
    skill_md: str,
    market_desc: str,
) -> dict[str, str]:
    """调用租户默认模型审查 Skill；失败时返回 skipped/error，不阻断提交。"""
    from oa_agent.runtime.llm import build_chat_model, resolve_model

    cfg = resolve_model(db, vault, tenant_id) if vault is not None else None
    if cfg is None:
        return {
            "status": "skipped",
            "summary": "未配置可用模型，已跳过自动审查，请管理员人工审核。",
            "recommend": "review",
        }
    prompt = (
        "你是企业内部 Skill 安全与质量审查员。根据 SKILL.md 与市场上架描述，判断是否适合发布到员工 Skill 市场。\n"
        "只输出一个 JSON 对象，不要其它文字：\n"
        '{"recommend":"approve|reject|review","summary":"中文审查意见，分点说明安全性、可用性、描述是否准确"}\n'
        "规则：\n"
        "- 含明显恶意指令、泄露密钥、越权操作、外泄数据倾向 → reject\n"
        "- 内容空洞、无法执行、描述与正文严重不符 → reject 或 review\n"
        "- 基本可用且风险可控 → approve；存疑 → review\n"
    )
    human = (
        f"## 市场上架描述\n{market_desc}\n\n"
        f"## Skill 元信息\nname={pack.name}\ndisplay={pack.display_name}\n"
        f"description={pack.description}\n\n"
        f"## SKILL.md\n{skill_md[:12000]}"
    )
    try:
        model = build_chat_model(cfg)
        resp = model.invoke([("system", prompt), ("human", human)])
        raw = getattr(resp, "content", None) or str(resp)
        if isinstance(raw, list):
            raw = "".join(str(x) for x in raw)
        text = str(raw).strip()
        parsed = _parse_review_json(text)
        recommend = str(parsed.get("recommend") or "review").strip().lower()
        if recommend not in ("approve", "reject", "review"):
            recommend = "review"
        summary = str(parsed.get("summary") or text)[:4000].strip() or "模型未给出明确意见"
        return {"status": "passed", "summary": summary, "recommend": recommend}
    except Exception as exc:  # noqa: BLE001
        log.exception("Skill 模型审查失败 pack=%s", pack.name)
        return {
            "status": "error",
            "summary": f"自动审查失败：{type(exc).__name__}，请管理员人工审核。",
            "recommend": "review",
        }


def _parse_review_json(text: str) -> dict:
    import json
    import re

    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.replace("```", "").strip()
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else {}
    except ValueError:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}


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
    """管理端设置包默认启停（系统包改 enabled_default；用户包同步写 owner 的 UserSkillPack）。"""
    pack = db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    pack.enabled_default = enabled_default
    pack.updated_at = utcnow()
    if pack.kind != "system" and pack.owner_oa:
        row = _user_library_row(db, tenant_id=tenant_id, oa=pack.owner_oa, pack_id=pack.id)
        if row is None:
            db.add(UserSkillPack(
                tenant_id=tenant_id, oa=pack.owner_oa, pack_id=pack.id, enabled=enabled_default,
                origin="created", created_at=utcnow(), updated_at=utcnow(),
            ))
        else:
            row.enabled = enabled_default
            row.updated_at = utcnow()
    return pack


def admin_list_market_submissions(
    db: Session,
    *,
    tenant_id: str,
    status: str = "pending_admin",
) -> list[dict[str, Any]]:
    """管理端：市场投稿列表（默认待审）。"""
    q = sa.select(SkillMarketListing).where(SkillMarketListing.tenant_id == tenant_id)
    if status and status != "all":
        q = q.where(SkillMarketListing.status == status)
    rows = list(db.scalars(q.order_by(SkillMarketListing.updated_at.desc(), SkillMarketListing.id.desc())).all())
    items: list[dict[str, Any]] = []
    for listing in rows:
        pack = db.get(SkillPack, listing.pack_id)
        if pack is None:
            continue
        version = _version(db, pack)
        items.append({
            **_pack_dict(pack, version, enabled=True, origin="market", in_library=False, listed=True, listing=listing),
            "listing_id": listing.id,
            "publisher_oa": listing.publisher_oa,
            "skill_md_preview": (version.skill_md[:2000] if version else ""),
        })
    return items


def admin_approve_market(
    db: Session,
    *,
    tenant_id: str,
    listing_id: int,
    reviewer: str,
    note: str = "",
) -> SkillMarketListing:
    listing = db.get(SkillMarketListing, listing_id)
    if listing is None or listing.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "投稿不存在")
    if listing.status not in ("pending_admin", "rejected"):
        raise AppError(409, "INVALID_STATUS", f"当前状态不可通过：{listing.status}")
    listing.status = "published"
    listing.admin_note = (note or "").strip()[:512]
    listing.admin_reviewer = reviewer
    listing.admin_reviewed_at = utcnow()
    listing.updated_at = utcnow()
    return listing


def admin_reject_market(
    db: Session,
    *,
    tenant_id: str,
    listing_id: int,
    reviewer: str,
    note: str,
) -> SkillMarketListing:
    listing = db.get(SkillMarketListing, listing_id)
    if listing is None or listing.tenant_id != tenant_id:
        raise AppError(404, "NOT_FOUND", "投稿不存在")
    if listing.status != "pending_admin":
        raise AppError(409, "INVALID_STATUS", f"当前状态不可驳回：{listing.status}")
    note = (note or "").strip()
    if len(note) < 2:
        raise AppError(422, "VALIDATION_ERROR", "请填写驳回原因")
    listing.status = "rejected"
    listing.admin_note = note[:512]
    listing.admin_reviewer = reviewer
    listing.admin_reviewed_at = utcnow()
    listing.updated_at = utcnow()
    return listing
