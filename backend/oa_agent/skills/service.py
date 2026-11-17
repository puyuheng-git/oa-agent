"""Agent Skill 包业务：启用解析、CRUD、市场、调用计数。"""

from __future__ import annotations

import logging
import re
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
from oa_agent.skills.parse import (
    SkillMdError,
    invocation_flags_from_skill_md,
    parse_skill_md,
    truncate_catalog_description,
)
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
    # DSH：模型目录/skill 工具 vs 用户 /name
    disable_model_invocation: bool = False
    user_invocable: bool = True


def pack_bundle_dir(data_dir: Path, storage_path: str) -> Path:
    return Path(data_dir) / storage_path


def _version(db: Session, pack: SkillPack) -> SkillPackVersion | None:
    if not pack.current_version_id:
        return None
    return db.get(SkillPackVersion, pack.current_version_id)


def _state(pack: SkillPack, version: SkillPackVersion | None, *, enabled: bool, origin: str) -> SkillPackState:
    meta = (version.bundle_meta or {}) if version else {}
    files = [f["path"] for f in (meta.get("files") or []) if isinstance(f, dict) and f.get("path")]
    disable_model, user_invocable = False, True
    if version and version.skill_md:
        disable_model, user_invocable = invocation_flags_from_skill_md(version.skill_md)
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
        disable_model_invocation=disable_model,
        user_invocable=user_invocable,
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


# 薄层 OA 适配：不替代 Anthropic skill-creator；只约定落盘/确认/Memory 分流。
# 种子包名 oa-skill-persist，避免覆盖管理员从 GitHub 导入的 anthropics/skills/skill-creator。
OA_SKILL_PERSIST_MD = """---
name: oa-skill-persist
description: >-
  OA 个人 Skill 落盘与修订适配。Use when the employee wants to save, create, update, or solidify a personal
  Skill after drafting with skill-creator; or when deciding Skill vs Memory.
---

# OA 个人 Skill 落盘适配

本说明是 **Anthropic skill-creator 的运行时桥接**，不替代 skill-creator。

## 与 skill-creator 的分工

1. **怎么写好 / 改好** → 遵循已安装的系统包 **skill-creator**（意图捕获、草稿、迭代 description）。
2. **写到哪里 / 何时生效** → 本说明 + 工具 `builtin.skill_create` / `builtin.skill_update`。
3. OA 聊天环境 **没有** Claude Code 式子代理 eval、`eval-viewer` 浏览器、可写技能目录；不要调用不存在的 eval 脚本，也不要往虚构路径写文件。

## Skill vs Memory

- **Memory**（`builtin.memory` / 「请记住」）：身份偏好、长期约束、短事实。
- **个人 Skill**：有明确触发场景 + 可复用分步指引，要当「能力」反复用。
- **不要固化**：一次性闲聊、未验证结论、纯叙事「这次怎么做的」。

## 落盘步骤（强制）

1. 用 skill-creator（若已启用）起草完整 `SKILL.md`（含 YAML `name` / `description`）。
2. 在对话中向员工展示草稿摘要；员工同意后再调工具。
3. **新建** → `builtin.skill_create`，参数 `skill_md` = 全文。工具会发起确认卡，**未确认不入库**。
4. **修改已有个人 Skill** → `builtin.skill_update`，参数 `name` + `skill_md`。同样走确认卡。
5. 工具返回「待确认」后，告知员工在确认卡上点确认；不要谎称已写入。

## 禁止

- 不要用短版自造流程替换 skill-creator 正文。
- 不要在未获员工确认时声称 Skill 已创建或已更新。
"""

# DSH 风格运行时口令：目录 → builtin.skill → 按正文；个人落盘另走确认工具
OA_SKILL_PERSIST_PROMPT = """## Skill 渐进披露（DSH / agentskills）
- 上方目录只有 name 与 description 摘要，不能当作操作步骤。
- 任务匹配某 Skill 时，先调用 builtin.skill（参数 name=精确包名）加载完整 SKILL.md，再严格按正文执行。
- 正文要求读 references/assets 时用 builtin.skill_read；跑 scripts 时用 builtin.skill_exec。
- 创建/修订个人 Skill：遵循 skill-creator（若已启用），落盘用 builtin.skill_create / builtin.skill_update（须确认卡）。
- 偏好/短事实用 Memory，不要建成 Skill。
"""


def catalog_entries_for_model(packs: list[SkillPackState]) -> list[dict[str, str]]:
    """模型可见目录：排除 disable-model-invocation；description 截断至 500。"""
    out: list[dict[str, str]] = []
    for pack in packs:
        if pack.disable_model_invocation:
            continue
        out.append({
            "name": pack.name,
            "description": truncate_catalog_description(pack.description or ""),
        })
    return out


def find_enabled_pack(packs: list[SkillPackState], name: str) -> SkillPackState | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    for pack in packs:
        if pack.name == key:
            return pack
    return None


def render_skill_content(*, name: str, instructions: str, resource_hint: str = "") -> str:
    """接近 DSH <skill_content> 的工具结果正文。"""
    hint = (resource_hint or "").strip() or (
        "Resources are under this skill pack root. "
        "Read references/assets via builtin.skill_read(skill, path). "
        "Run scripts via builtin.skill_exec(skill, script)."
    )
    return (
        f'<skill_content name="{name}">\n'
        f"<skill_resources>\n{hint}\n</skill_resources>\n\n"
        f"<skill_instructions>\n{instructions}\n</skill_instructions>\n"
        f"</skill_content>"
    )


_SLASH_SKILL_RE = re.compile(r"(?<!\S)/([a-z0-9]+(?:-[a-z0-9]+)*)(?!\S)")


def resolve_slash_skills(
    db: Session,
    *,
    data_dir: Path,
    packs: list[SkillPackState],
    message: str,
) -> str:
    """DSH user-explicit：空白边界的 /name 直注 user-invocable 包正文。"""
    names = _SLASH_SKILL_RE.findall(message or "")
    if not names:
        return ""
    blocks: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        pack = find_enabled_pack(packs, name)
        if pack is None or not pack.user_invocable:
            continue
        try:
            body = load_skill_body(db, data_dir, pack.id)
        except AppError:
            continue
        hint = resource_hint_for_pack(pack)
        blocks.append(render_skill_content(name=pack.name, instructions=body, resource_hint=hint))
        bump_invoke(db, pack.id)
    return "\n\n".join(blocks)


SKILL_READ_MAX_CHARS = 200_000
SKILL_READ_PREFIXES = ("references/", "assets/")
SKILL_READ_ROOT_EXTS = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".tsv"})


def assert_skill_read_relpath(rel: str) -> str:
    """校验包内只读相对路径；拒绝穿越与非白名单路径。返回规范化 posix 相对路径。"""
    raw = (rel or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in raw.split("/"):
        raise AppError(422, "INVALID_ARGUMENT", "Skill 资源路径无效")
    parts = raw.split("/")
    for i, part in enumerate(parts):
        # 禁止隐藏目录段；文件名允许 .md 等扩展名
        if part.startswith(".") and i < len(parts) - 1:
            raise AppError(422, "INVALID_ARGUMENT", "Skill 资源路径无效")
    lower = raw.lower()
    if lower.startswith(SKILL_READ_PREFIXES):
        return raw
    if "/" not in raw and Path(raw).suffix.lower() in SKILL_READ_ROOT_EXTS:
        return raw
    raise AppError(
        422,
        "INVALID_ARGUMENT",
        "只能读取 references/、assets/ 或包根文档；脚本请用 builtin.skill_exec",
    )


def read_skill_resource(bundle: Path, rel: str, *, max_chars: int = SKILL_READ_MAX_CHARS) -> dict[str, Any]:
    """从包根安全读取白名单相对文件。"""
    norm = assert_skill_read_relpath(rel)
    root = bundle.resolve()
    target = (root / norm).resolve()
    if target != root and root not in target.parents:
        raise AppError(403, "PATH_NOT_ALLOWED", "该路径不被允许")
    if not target.is_file():
        raise AppError(404, "NOT_FOUND", f"Skill 资源不存在：{norm}")
    text = target.read_text(encoding="utf-8", errors="replace")
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return {"path": norm, "content": text, "truncated": truncated}


def resource_hint_for_pack(pack: SkillPackState) -> str:
    """加载结果中的资源指引（不枚举整包目录，对齐 DSH）。"""
    has_scripts = any(
        p.replace("\\", "/").startswith("scripts/") and p.lower().endswith((".py", ".js", ".mjs", ".cjs"))
        for p in (pack.files or [])
    )
    has_refs = any(
        p.replace("\\", "/").startswith("references/") or p.replace("\\", "/").startswith("assets/")
        for p in (pack.files or [])
    )
    parts = [
        f"Skill pack「{pack.name}」resource base is the pack bundle directory.",
        "Follow SKILL.md; use relative paths from the skill root (one level deep).",
    ]
    if has_scripts:
        parts.append("Scripts: call builtin.skill_exec with skill=" + pack.name + " and script=relative path under scripts/.")
    if has_refs:
        parts.append("References/assets: call builtin.skill_read with skill=" + pack.name + " and path=relative file.")
    return "\n".join(parts)


def ensure_system_skill_packs(db: Session, *, tenant_id: str, data_dir: Path) -> int:
    """幂等写入内置系统包；已存在则跳过，绝不覆盖 Anthropic skill-creator。"""
    seeds = {
        "oa-skill-persist": OA_SKILL_PERSIST_MD,
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
            display_name="OA Skill 落盘适配" if name == "oa-skill-persist" else parsed["name"],
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


def get_pack_by_name(db: Session, *, tenant_id: str, name: str) -> SkillPack | None:
    """按租户 + Skill 名取包。"""
    key = (name or "").strip().lower()
    if not key:
        return None
    return db.scalar(
        sa.select(SkillPack).where(SkillPack.tenant_id == tenant_id, SkillPack.name == key)
    )


def apply_skill_pack_payload(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    data_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """员工确认后执行 create/update；payload 来自确认任务 binding。"""
    action = str(payload.get("action") or "").strip()
    skill_md = payload.get("skill_md")
    if not isinstance(skill_md, str) or len(skill_md.strip()) < 10:
        raise AppError(422, "VALIDATION_ERROR", "确认载荷缺少有效 skill_md")
    if action == "create":
        pack = create_user_pack(db, tenant_id=tenant_id, oa=oa, data_dir=data_dir, skill_md=skill_md)
    elif action == "update":
        pack_id = payload.get("pack_id")
        if not isinstance(pack_id, int) or pack_id < 1:
            raise AppError(422, "VALIDATION_ERROR", "确认载荷缺少 pack_id")
        pack = update_user_pack(
            db, tenant_id=tenant_id, oa=oa, pack_id=pack_id, data_dir=data_dir, skill_md=skill_md,
        )
    else:
        raise AppError(422, "VALIDATION_ERROR", f"未知 Skill 确认动作：{action}")
    return {
        "ok": True,
        "action": action,
        "id": pack.id,
        "name": pack.name,
        "display_name": pack.display_name or pack.name,
    }


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
