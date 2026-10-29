"""/v1/admin/packs：领域包列表与启停。

M3 权限复用 ``ops.tool.manage``（避免新增 ``ops.pack.manage`` 迁移噪音）；
写操作走 CSRF + Idempotency-Key + 审计（``pack.enable`` / ``pack.disable``）。
启停持久化到 settings 组 ``packs.disabled_ids``，并刷新 ``rt.pack_registry``。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.chat.service import get_pack_registry
from oa_agent.errors import AppError
from oa_agent.packs.loader import validate_pack_files
from oa_agent.packs.registry import PackRegistry
from oa_agent.packs.state import PACKS_GROUP, load_disabled_ids, save_disabled_ids

router = APIRouter(prefix="/v1/admin/packs", tags=["admin-packs"])

# M3：复用 Tool 管理权限，交付说明中写明；后续可迁到 ops.pack.manage
PERM = "ops.tool.manage"


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


def _registry(ctx: AdminCtx) -> PackRegistry:
    return get_pack_registry(ctx.runtime)


def _pack_view(registry: PackRegistry, pack_id: str) -> dict:
    manifests = {m.id: m for m in registry.all_manifests()}
    manifest = manifests.get(pack_id)
    if manifest is None:
        raise AppError(404, "NOT_FOUND", "领域包不存在")
    pack_dir = registry.pack_dir(pack_id)
    validation_errors = validate_pack_files(manifest, pack_dir) if pack_dir is not None else []
    return {
        "id": manifest.id,
        "display_name": manifest.display_name,
        "version": manifest.version,
        "enabled": registry.is_enabled(manifest.id),
        "default_enabled": bool(manifest.default_enabled),
        "connectors": list(manifest.connectors),
        "validation_errors": validation_errors,
    }


def _toggle(ctx: AdminCtx, pack_id: str, *, enabled: bool, reason: str | None) -> dict:
    registry = _registry(ctx)
    if pack_id not in {m.id for m in registry.all_manifests()}:
        raise AppError(404, "NOT_FOUND", "领域包不存在")

    svc = ctx.runtime.settings_svc
    with ctx.db.begin():
        current = load_disabled_ids(db=ctx.db, settings_service=svc)
        before_enabled = registry.is_enabled(pack_id)

        disabled = list(current)
        if enabled:
            disabled = [x for x in disabled if x != pack_id]
        elif pack_id not in disabled:
            disabled.append(pack_id)

        save_disabled_ids(
            disabled,
            db=ctx.db,
            settings_service=svc,
            actor=ctx.user.username,
        )
        # 事务内先按目标 disabled 列表更新内存，便于审计 after 与返回值一致
        registry.set_disabled_ids(disabled)
        after_enabled = registry.is_enabled(pack_id)
        ctx.audit(
            "pack.enable" if enabled else "pack.disable",
            "pack",
            pack_id,
            before={"enabled": before_enabled},
            after={"enabled": after_enabled},
            reason=reason or "",
        )

    packs_values = svc.effective(ctx.db, PACKS_GROUP)
    registry.reload(settings=packs_values)
    return _pack_view(registry, pack_id)


@router.get("")
def list_packs(ctx: AdminCtx = Depends(admin_read(PERM))):
    registry = _registry(ctx)
    items = [_pack_view(registry, m.id) for m in registry.all_manifests()]
    items.sort(key=lambda x: x["id"])
    return {"items": items}


@router.post("/{pack_id}/enable")
def enable_pack(pack_id: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    return _toggle(ctx, pack_id, enabled=True, reason=body.reason)


@router.post("/{pack_id}/disable")
def disable_pack(pack_id: str, body: ReasonIn, ctx: AdminCtx = Depends(admin_write(PERM))):
    return _toggle(ctx, pack_id, enabled=False, reason=body.reason)
