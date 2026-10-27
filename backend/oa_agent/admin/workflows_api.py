"""/v1/admin/workflows：草稿、校验、diff、发布、回滚（设计 §9 ops.config.edit / publish / rollback）。

已发布版本不可改；未校验不能发布；所有变更与审计同事务。
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import AgentDefinition, ConfigRelease, LlmModel, Skill, WorkflowVersion
from oa_agent.errors import AppError
from oa_agent.runtime.graphs import travel_query
from oa_agent.runtime.graphs.travel_query import resolve_workflow_id
from oa_agent.runtime.releases import FIELDS, GROUPS, PUBLISHED, ReleaseError, ReleaseService, diff_content

router = APIRouter(prefix="/v1/admin/workflows", tags=["admin-workflows"])

EDIT, PUBLISH, ROLLBACK = "ops.config.edit", "ops.config.publish", "ops.config.rollback"
VIEW_ANY = EDIT  # 查看配置版本需要编辑权限之一；只读角色可通过运行详情看到 config_release_id


class DraftIn(BaseModel):
    content: dict[str, Any]


class PublishIn(BaseModel):
    content_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=2, max_length=200)


class RollbackIn(BaseModel):
    version_no: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=200)


def _svc(ctx: AdminCtx, workflow_id: str) -> ReleaseService:
    svc: ReleaseService = ctx.runtime.engine.release_provider
    if resolve_workflow_id(workflow_id) != svc.workflow_id:
        raise AppError(404, "NOT_FOUND", "Workflow 不存在")
    return svc


def _guard(fn, *args):
    try:
        return fn(*args)
    except ReleaseError as exc:
        raise AppError(exc.status, exc.code, exc.message) from None


def _version_view(v: WorkflowVersion | None) -> dict | None:
    if v is None:
        return None
    return {"version_id": v.version_id, "version_no": v.version_no, "status": v.status, "content": v.content_json,
            "content_hash": v.content_hash, "validation": v.validation_json, "validated_hash": v.validated_hash,
            "created_by": v.created_by, "created_at": v.created_at, "updated_by": v.updated_by,
            "updated_at": v.updated_at, "published_at": v.published_at}


def _release_view(r: ConfigRelease) -> dict:
    return {"release_id": r.release_id, "version_no": r.version_no, "release_type": r.release_type,
            "reason": r.reason, "previous_release_id": r.previous_release_id, "released_by": r.released_by,
            "released_at": r.released_at}


@router.get("")
def list_workflows(ctx: AdminCtx = Depends(admin_read(VIEW_ANY))):
    svc: ReleaseService = ctx.runtime.engine.release_provider
    items = []
    for d in ctx.db.scalars(sa.select(AgentDefinition).where(AgentDefinition.tenant_id == ctx.runtime.tenant_id)):
        current = svc.current_row(ctx.db) if d.workflow_id == svc.workflow_id else None
        draft = svc.draft(ctx.db) if d.workflow_id == svc.workflow_id else None
        items.append({"agent_id": d.agent_id, "name": d.name, "workflow_id": d.workflow_id,
                      "current_release": _release_view(current[0]) if current else None,
                      "draft_status": draft.status if draft else None})
    return {"items": items}


@router.get("/{workflow_id}")
def workflow_detail(workflow_id: str, ctx: AdminCtx = Depends(admin_read(VIEW_ANY))):
    svc = _svc(ctx, workflow_id)
    current = svc.current_row(ctx.db)
    versions = ctx.db.scalars(sa.select(WorkflowVersion).where(
        WorkflowVersion.tenant_id == ctx.runtime.tenant_id, WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.status == PUBLISHED).order_by(WorkflowVersion.version_no.desc())).all()
    releases = ctx.db.scalars(sa.select(ConfigRelease).where(
        ConfigRelease.tenant_id == ctx.runtime.tenant_id, ConfigRelease.workflow_id == workflow_id)
        .order_by(ConfigRelease.id.desc()).limit(100)).all()
    return {
        "workflow_id": workflow_id,
        "current_release": _release_view(current[0]) if current else None,
        "current_version": _version_view(current[1]) if current else None,
        "draft": _version_view(svc.draft(ctx.db)),
        "versions": [_version_view(v) for v in versions],
        "releases": [_release_view(r) for r in releases],
    }


@router.get("/{workflow_id}/schema")
def workflow_schema(workflow_id: str, ctx: AdminCtx = Depends(admin_read(VIEW_ANY))):
    _svc(ctx, workflow_id)
    models = ctx.db.scalars(sa.select(LlmModel).where(LlmModel.tenant_id == ctx.runtime.tenant_id)
                            .order_by(LlmModel.id)).all()
    skills = ctx.db.scalars(sa.select(Skill).where(Skill.tenant_id == ctx.runtime.tenant_id)).all()
    return {"fields": FIELDS, "groups": GROUPS, "defaults": travel_query.DEFAULT_CONFIG,
            "models": [{"id": m.id, "label": m.display_name or m.model_name, "enabled": m.enabled} for m in models],
            "skills": [{"name": s.name, "label": s.display_name, "status": s.validation_status} for s in skills]}


@router.get("/{workflow_id}/diff")
def workflow_diff(workflow_id: str, from_no: int | None = None, to: str = "draft",
                  ctx: AdminCtx = Depends(admin_read(VIEW_ANY))):
    """from_no 省略 = 当前生效版本；to = 版本号或 draft。"""
    svc = _svc(ctx, workflow_id)

    def published(no: int) -> WorkflowVersion:
        v = ctx.db.scalar(sa.select(WorkflowVersion).where(
            WorkflowVersion.tenant_id == ctx.runtime.tenant_id, WorkflowVersion.workflow_id == workflow_id,
            WorkflowVersion.version_no == no))
        if v is None:
            raise AppError(404, "NOT_FOUND", f"版本 v{no} 不存在")
        return v

    if from_no is None:
        current = svc.current_row(ctx.db)
        base = current[1] if current else None
    else:
        base = published(from_no)
    if to == "draft":
        target = svc.draft(ctx.db)
        if target is None:
            raise AppError(404, "DRAFT_NOT_FOUND", "没有草稿")
    else:
        try:
            target = published(int(to))
        except ValueError:
            raise AppError(422, "VALIDATION_ERROR", "to 必须是版本号或 draft") from None
    return {"from": base.version_no if base else None, "to": to,
            "changes": diff_content(base.content_json if base else None, target.content_json)}


@router.put("/{workflow_id}/draft")
def save_draft(workflow_id: str, body: DraftIn, ctx: AdminCtx = Depends(admin_write(EDIT))):
    svc = _svc(ctx, workflow_id)
    with ctx.db.begin():
        before = svc.draft(ctx.db)
        before_hash = before.content_hash if before else None
        draft = svc.save_draft(ctx.db, body.content, ctx.user.username)
        ctx.audit("workflow.draft.save", "workflow", workflow_id, before={"content_hash": before_hash},
                  after={"content_hash": draft.content_hash, "status": draft.status})
    return _version_view(draft)


@router.delete("/{workflow_id}/draft")
def discard_draft(workflow_id: str, ctx: AdminCtx = Depends(admin_write(EDIT))):
    svc = _svc(ctx, workflow_id)
    with ctx.db.begin():
        _guard(svc.discard_draft, ctx.db)
        ctx.audit("workflow.draft.discard", "workflow", workflow_id)
    return {"ok": True}


@router.post("/{workflow_id}/draft/validate")
def validate_draft(workflow_id: str, ctx: AdminCtx = Depends(admin_write(EDIT))):
    svc = _svc(ctx, workflow_id)
    with ctx.db.begin():
        draft = _guard(svc.validate_draft, ctx.db, ctx.user.username)
        ctx.audit("workflow.draft.validate", "workflow", workflow_id, after={
            "content_hash": draft.content_hash, "ok": draft.validation_json["ok"],
            "errors": draft.validation_json["errors"]}, result="success" if draft.validation_json["ok"] else "failed")
    return _version_view(draft)


@router.post("/{workflow_id}/publish")
def publish(workflow_id: str, body: PublishIn, ctx: AdminCtx = Depends(admin_write(PUBLISH))):
    svc = _svc(ctx, workflow_id)
    with ctx.db.begin():
        current = svc.current_row(ctx.db)
        release = _guard(svc.publish, ctx.db, body.content_hash, body.reason, ctx.user.username)
        ctx.audit("workflow.publish", "workflow", workflow_id,
                  before={"version_no": current[1].version_no if current else None},
                  after={"version_no": release.version_no, "release_id": release.release_id}, reason=body.reason)
    svc.current()
    return _release_view(release)


@router.post("/{workflow_id}/rollback")
def rollback(workflow_id: str, body: RollbackIn, ctx: AdminCtx = Depends(admin_write(ROLLBACK))):
    svc = _svc(ctx, workflow_id)
    with ctx.db.begin():
        current = svc.current_row(ctx.db)
        release = _guard(svc.rollback, ctx.db, body.version_no, body.reason, ctx.user.username)
        ctx.audit("workflow.rollback", "workflow", workflow_id,
                  before={"version_no": current[1].version_no if current else None},
                  after={"version_no": release.version_no, "release_id": release.release_id}, reason=body.reason)
    svc.current()
    return _release_view(release)
