"""/v1/admin/export-files：导出文件列表与下载（ops.file.view；访问即审计）。"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from oa_agent.auth.rbac import AdminCtx, admin_read
from oa_agent.db.models import ExportFile
from oa_agent.errors import AppError
from oa_agent.executor.builtin_runtime import build_export_store
from oa_agent.executor.executor import ToolError

router = APIRouter(prefix="/v1/admin/export-files", tags=["admin-export-files"])

VIEW = "ops.file.view"
MSG_NOT_FOUND = "文件不存在"


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


def _item(row: ExportFile) -> dict:
    return {
        "file_id": row.file_id,
        "oa": row.oa,
        "thread_id": row.thread_id,
        "run_id": row.run_id,
        "filename": row.filename,
        "size_bytes": row.size_bytes,
        "storage": row.storage,
        "created_at": _iso(row.created_at),
    }


def _audit(ctx: AdminCtx, action: str, resource_id: str = "", **after) -> None:
    """查询已自动开启事务，审计随之提交；提交失败抛错，请求整体失败。"""
    detail = {k: v for k, v in after.items() if v is not None}
    ctx.audit(action, "export_file", resource_id,
              after=json.dumps(detail, ensure_ascii=False) if detail else None)
    ctx.db.commit()


@router.get("")
def list_export_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    oa: str | None = None,
    thread_id: str | None = None,
    filename: str | None = Query(None, max_length=255),
    start: datetime | None = None,
    end: datetime | None = None,
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    F = ExportFile
    cond = [F.tenant_id == ctx.runtime.tenant_id]
    if oa:
        cond.append(F.oa == oa.strip())
    if thread_id:
        cond.append(F.thread_id == thread_id.strip())
    if filename and filename.strip():
        cond.append(F.filename.contains(filename.strip(), autoescape=True))
    if start:
        cond.append(F.created_at >= _aware(start))
    if end:
        cond.append(F.created_at < _aware(end))
    total = ctx.db.scalar(sa.select(sa.func.count()).select_from(F).where(*cond)) or 0
    rows = ctx.db.scalars(
        sa.select(F).where(*cond).order_by(F.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    _audit(ctx, "export_file.list", oa=oa, thread_id=thread_id, filename=filename, page=page, count=len(rows))
    return {"items": [_item(r) for r in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/{file_id}/download")
def download_export_file(file_id: str, ctx: AdminCtx = Depends(admin_read(VIEW))):
    row = ctx.db.scalar(
        sa.select(ExportFile).where(ExportFile.tenant_id == ctx.runtime.tenant_id, ExportFile.file_id == file_id)
    )
    if row is None:
        raise AppError(404, "NOT_FOUND", MSG_NOT_FOUND)
    store = build_export_store(ctx.runtime, ctx.db)
    try:
        data = store.get(row.storage, row.object_key)
    except ToolError:
        raise AppError(404, "NOT_FOUND", MSG_NOT_FOUND) from None
    _audit(ctx, "export_file.download", row.file_id, oa=row.oa, filename=row.filename)
    media = row.content_type or "application/octet-stream"
    return StreamingResponse(
        io.BytesIO(data),
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename)}"},
    )
