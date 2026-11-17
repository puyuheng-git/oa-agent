"""管理端 Agent Skill 包：列表、GitHub 导入、系统包默认启停。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import SkillPack
from oa_agent.errors import AppError
from oa_agent.skills import service as packs

router = APIRouter(prefix="/v1/admin/skill-packs", tags=["admin-skill-packs"])
SKILL = "ops.skill.manage"


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


class GithubImportIn(ReasonIn):
    url: str = Field(min_length=12, max_length=512)
    paths: list[str] = Field(default_factory=list, max_length=40)


class EnableDefaultIn(ReasonIn):
    enabled_default: bool


@router.get("")
def list_packs(ctx: AdminCtx = Depends(admin_read(SKILL))):
    return {"items": packs.admin_list_packs(ctx.db, tenant_id=ctx.runtime.tenant_id)}


class MarketDecisionIn(ReasonIn):
    note: str = Field(default="", max_length=512)


@router.get("/market")
def list_market_submissions(status: str = "pending_admin", ctx: AdminCtx = Depends(admin_read(SKILL))):
    """员工推送的 Skill 市场投稿（含模型审查结果）。"""
    return {
        "items": packs.admin_list_market_submissions(
            ctx.db, tenant_id=ctx.runtime.tenant_id, status=status or "pending_admin",
        )
    }


@router.post("/market/{listing_id}/approve")
def approve_market(listing_id: int, body: MarketDecisionIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    with ctx.db.begin():
        listing = packs.admin_approve_market(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            listing_id=listing_id,
            reviewer=ctx.user.username,
            note=body.note or body.reason,
        )
        ctx.audit(
            "skill_market.approve",
            "skill_market_listing",
            str(listing.id),
            after={"pack_id": listing.pack_id, "status": listing.status},
            reason=body.reason,
        )
    return {"id": listing.id, "pack_id": listing.pack_id, "status": listing.status}


@router.post("/market/{listing_id}/reject")
def reject_market(listing_id: int, body: MarketDecisionIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    note = (body.note or body.reason or "").strip()
    with ctx.db.begin():
        listing = packs.admin_reject_market(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            listing_id=listing_id,
            reviewer=ctx.user.username,
            note=note,
        )
        ctx.audit(
            "skill_market.reject",
            "skill_market_listing",
            str(listing.id),
            after={"pack_id": listing.pack_id, "status": listing.status, "note": note},
            reason=body.reason,
        )
    return {"id": listing.id, "pack_id": listing.pack_id, "status": listing.status}


@router.post("/import/github")
def import_github(body: GithubImportIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    data_dir = ctx.runtime.settings.data_dir
    try:
        with ctx.db.begin():
            results = packs.import_github_packs(
                ctx.db,
                tenant_id=ctx.runtime.tenant_id,
                data_dir=data_dir,
                url=body.url.strip(),
                paths=[p.strip() for p in body.paths if p and p.strip()] or None,
                operator=ctx.user.username,
                kind="system",
            )
            ctx.audit(
                "skill_pack.import_github",
                "skill_pack",
                "*",
                after={"url": body.url, "paths": body.paths, "results": results},
                reason=body.reason,
            )
    except AppError as exc:
        # 网络类失败给出可操作提示（import_github_packs 已映射为 IMPORT_FAILED）
        if exc.code == "IMPORT_FAILED":
            raise AppError(
                422,
                "IMPORT_FAILED",
                f"{exc.message}。若因网络原因，请检查服务器出网/代理后重试。",
            ) from None
        raise
    ok = [r for r in results if r.get("ok")]
    return {"imported": ok, "files": results, "ok_count": len(ok), "fail_count": len(results) - len(ok)}


@router.post("/{pack_id}/enable-default")
def set_default(pack_id: int, body: EnableDefaultIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    with ctx.db.begin():
        pack = packs.admin_set_system_default(
            ctx.db, tenant_id=ctx.runtime.tenant_id, pack_id=pack_id, enabled_default=body.enabled_default,
        )
        ctx.audit(
            "skill_pack.enable_default",
            "skill_pack",
            pack.name,
            after={"enabled_default": body.enabled_default},
            reason=body.reason,
        )
    return {"id": pack.id, "name": pack.name, "enabled_default": pack.enabled_default}


class PackUpdateIn(ReasonIn):
    skill_md: str = Field(min_length=10, max_length=200_000)


@router.get("/{pack_id}")
def pack_detail(pack_id: int, ctx: AdminCtx = Depends(admin_read(SKILL))):
    pack = ctx.db.get(SkillPack, pack_id)
    if pack is None or pack.tenant_id != ctx.runtime.tenant_id:
        raise AppError(404, "NOT_FOUND", "Skill 包不存在")
    body = packs.load_skill_body(ctx.db, ctx.runtime.settings.data_dir, pack_id)
    items = packs.admin_list_packs(ctx.db, tenant_id=ctx.runtime.tenant_id)
    view = next((i for i in items if i["id"] == pack_id), None) or {"id": pack_id, "name": pack.name}
    return {**view, "skill_md": body}


@router.put("/{pack_id}")
def update_pack(pack_id: int, body: PackUpdateIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    with ctx.db.begin():
        pack = packs.admin_update_pack(
            ctx.db,
            tenant_id=ctx.runtime.tenant_id,
            pack_id=pack_id,
            data_dir=ctx.runtime.settings.data_dir,
            skill_md=body.skill_md,
            operator=ctx.user.username,
        )
        ctx.audit(
            "skill_pack.update", "skill_pack", pack.name,
            after={"pack_id": pack.id}, reason=body.reason,
        )
    detail = packs.load_skill_body(ctx.db, ctx.runtime.settings.data_dir, pack_id)
    return {"id": pack_id, "name": pack.name, "skill_md": detail}


@router.delete("/{pack_id}")
def delete_pack(pack_id: int, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(SKILL))):
    with ctx.db.begin():
        pack = ctx.db.get(SkillPack, pack_id)
        if pack is None or pack.tenant_id != ctx.runtime.tenant_id:
            raise AppError(404, "NOT_FOUND", "Skill 包不存在")
        name = pack.name
        packs.admin_delete_pack(
            ctx.db, tenant_id=ctx.runtime.tenant_id, pack_id=pack_id,
            data_dir=ctx.runtime.settings.data_dir,
        )
        ctx.audit("skill_pack.delete", "skill_pack", name, before={"pack_id": pack_id}, reason=body.reason)
    return {"ok": True, "id": pack_id}
