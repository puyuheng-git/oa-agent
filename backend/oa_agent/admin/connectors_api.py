"""连接器只读总览：HTTP 业务上游与 MCP 服务配置。"""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends

from oa_agent.auth.rbac import AdminCtx, admin_read_any
from oa_agent.db.models import McpServer

router = APIRouter(prefix="/v1/admin/connectors", tags=["admin-connectors"])

VIEW_PERMS = ("sys.setting.view", "ops.tool.manage")


def _http_items(ctx: AdminCtx) -> list[dict]:
    # 总览只需要公开配置视图，避免无谓解密任何 OA 密钥。
    settings = ctx.runtime.settings_svc.view(ctx.db, "oa")["values"]
    items = []
    for upstream in settings.get("upstreams") or []:
        if not isinstance(upstream, dict) or not upstream.get("key"):
            continue
        connector_id = str(upstream["key"])
        items.append({
            "id": connector_id,
            "kind": "http",
            "label": str(upstream.get("label") or connector_id),
            "envelope_profile": "oa_office",
            "health": "configured" if upstream.get("base_url") else "missing",
        })
    return items


def _has_target(row: McpServer) -> bool:
    target = row.command if row.transport == "stdio" else row.url
    return bool(target and target.strip())


def _mcp_items(ctx: AdminCtx) -> list[dict]:
    rows = ctx.db.scalars(
        sa.select(McpServer)
        .where(McpServer.tenant_id == ctx.runtime.tenant_id)
        .order_by(McpServer.name)
    ).all()
    return [{
        "id": row.name,
        "kind": "mcp",
        "label": row.display_name or row.name,
        "health": "configured" if row.enabled and _has_target(row) else "missing",
    } for row in rows]


def _builtin_item() -> dict:
    # 进程内 BuiltinRuntime 固定项，非 HTTP 连接器；无 envelope_profile。
    return {
        "id": "builtin",
        "kind": "builtin",
        "label": "内置运行时",
        "health": "configured",
    }


@router.get("")
def list_connectors(ctx: AdminCtx = Depends(admin_read_any(*VIEW_PERMS))):
    # 顺序：http → mcp → builtin（builtin 恒为最后一项）。
    return {"items": [*_http_items(ctx), *_mcp_items(ctx), _builtin_item()]}
