"""/v1/admin/llm/*：LLM 提供方与模型。"""

from __future__ import annotations

import json
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, HttpUrl

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import LlmModel, LlmProvider
from oa_agent.errors import AppError
from oa_agent.integrations.llm_check import check_model, check_provider

router = APIRouter(prefix="/v1/admin/llm", tags=["admin-llm"])


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    provider_type: Literal["openai_compatible"] = "openai_compatible"
    base_url: HttpUrl
    api_key: str | None = Field(default=None, max_length=512, description="留空 = 不修改")
    clear_api_key: bool = False
    timeout_seconds: int = Field(default=60, ge=1, le=600)
    enabled: bool = True


class ModelIn(BaseModel):
    provider_id: int
    model_name: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    purpose_tags: list[str] = Field(default_factory=list)
    enabled: bool = True


def _secret_name(provider_id: int) -> str:
    return f"llm.provider.{provider_id}.api_key"


def _provider_view(ctx: AdminCtx, p: LlmProvider) -> dict:
    return {
        "id": p.id, "name": p.name, "provider_type": p.provider_type, "base_url": p.base_url,
        "api_key": ctx.runtime.vault.describe(ctx.db, p.secret_ref).as_dict(),
        "timeout_seconds": p.timeout_seconds, "enabled": p.enabled,
        "updated_by": p.updated_by, "updated_at": p.updated_at,
    }


def _provider_summary(ctx: AdminCtx, p: LlmProvider) -> str:
    v = _provider_view(ctx, p)
    v["api_key"] = v["api_key"]["display"].split(" · ")[0]
    v.pop("updated_at")
    return json.dumps(v, ensure_ascii=False)


def _model_view(m: LlmModel) -> dict:
    return {
        "id": m.id, "provider_id": m.provider_id, "model_name": m.model_name, "display_name": m.display_name,
        "temperature": (m.params_json or {}).get("temperature"), "max_tokens": (m.params_json or {}).get("max_tokens"),
        "purpose_tags": m.purpose_tags or [], "enabled": m.enabled, "updated_by": m.updated_by, "updated_at": m.updated_at,
    }


def _get_provider(ctx: AdminCtx, provider_id: int) -> LlmProvider:
    p = ctx.db.get(LlmProvider, provider_id)
    if p is None or p.tenant_id != ctx.runtime.tenant_id:
        raise AppError(404, "NOT_FOUND", "提供方不存在")
    return p


def _get_model(ctx: AdminCtx, model_id: int) -> LlmModel:
    m = ctx.db.get(LlmModel, model_id)
    if m is None or m.tenant_id != ctx.runtime.tenant_id:
        raise AppError(404, "NOT_FOUND", "模型不存在")
    return m


def _name_taken(ctx: AdminCtx, name: str, exclude_id: int | None = None) -> bool:
    q = sa.select(LlmProvider.id).where(LlmProvider.tenant_id == ctx.runtime.tenant_id, LlmProvider.name == name)
    if exclude_id:
        q = q.where(LlmProvider.id != exclude_id)
    return ctx.db.scalar(q) is not None


# ---- providers ----

@router.get("/providers")
def list_providers(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    rows = ctx.db.scalars(sa.select(LlmProvider).where(LlmProvider.tenant_id == ctx.runtime.tenant_id)
                          .order_by(LlmProvider.id)).all()
    return {"items": [_provider_view(ctx, p) for p in rows]}


@router.post("/providers")
def create_provider(body: ProviderIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        if _name_taken(ctx, body.name):
            raise AppError(409, "NAME_EXISTS", "提供方名称已存在")
        p = LlmProvider(tenant_id=ctx.runtime.tenant_id, name=body.name, provider_type=body.provider_type,
                        base_url=str(body.base_url).rstrip("/"), timeout_seconds=body.timeout_seconds,
                        enabled=body.enabled, updated_by=ctx.user.username)
        ctx.db.add(p)
        ctx.db.flush()
        if body.api_key:
            p.secret_ref = _secret_name(p.id)
            ctx.runtime.vault.set(ctx.db, p.secret_ref, body.api_key, ctx.user.username)
        ctx.audit("llm.provider.create", "llm_provider", p.id, after=_provider_summary(ctx, p))
    return _provider_view(ctx, p)


@router.put("/providers/{provider_id}")
def update_provider(provider_id: int, body: ProviderIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        p = _get_provider(ctx, provider_id)
        if _name_taken(ctx, body.name, exclude_id=p.id):
            raise AppError(409, "NAME_EXISTS", "提供方名称已存在")
        before = _provider_summary(ctx, p)
        p.name, p.provider_type = body.name, body.provider_type
        p.base_url = str(body.base_url).rstrip("/")
        p.timeout_seconds, p.enabled, p.updated_by = body.timeout_seconds, body.enabled, ctx.user.username
        key_note = ""
        if body.clear_api_key and p.secret_ref:
            ctx.runtime.vault.delete(ctx.db, p.secret_ref)
            p.secret_ref = None
            key_note = " | api_key：已清除"
        elif body.api_key:
            p.secret_ref = _secret_name(p.id)
            ctx.runtime.vault.set(ctx.db, p.secret_ref, body.api_key, ctx.user.username)
            key_note = " | api_key：已变更"
        ctx.audit("llm.provider.update", "llm_provider", p.id, before=before, after=_provider_summary(ctx, p) + key_note)
    return _provider_view(ctx, p)


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        p = _get_provider(ctx, provider_id)
        if ctx.db.scalar(sa.select(sa.func.count()).where(LlmModel.provider_id == p.id)):
            raise AppError(409, "PROVIDER_IN_USE", "该提供方下仍有模型，请先删除模型")
        before = _provider_summary(ctx, p)
        if p.secret_ref:
            ctx.runtime.vault.delete(ctx.db, p.secret_ref)
        ctx.db.delete(p)
        ctx.audit("llm.provider.delete", "llm_provider", provider_id, before=before)
    return {"ok": True}


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    p = _get_provider(ctx, provider_id)
    key = ctx.runtime.vault.reveal(ctx.db, p.secret_ref)
    return check_provider(p.base_url, key, p.timeout_seconds)


# ---- models ----

@router.get("/models")
def list_models(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    rows = ctx.db.scalars(sa.select(LlmModel).where(LlmModel.tenant_id == ctx.runtime.tenant_id)
                          .order_by(LlmModel.id)).all()
    return {"items": [_model_view(m) for m in rows]}


def _apply_model(m: LlmModel, body: ModelIn, actor: str) -> None:
    m.provider_id, m.model_name = body.provider_id, body.model_name
    m.display_name = body.display_name or body.model_name
    m.params_json = {k: v for k, v in {"temperature": body.temperature, "max_tokens": body.max_tokens}.items()
                     if v is not None}
    m.purpose_tags = [t.strip() for t in body.purpose_tags if t.strip()]
    m.enabled, m.updated_by = body.enabled, actor


def _model_dupe(ctx: AdminCtx, body: ModelIn, exclude_id: int | None = None) -> bool:
    q = sa.select(LlmModel.id).where(LlmModel.provider_id == body.provider_id, LlmModel.model_name == body.model_name)
    if exclude_id:
        q = q.where(LlmModel.id != exclude_id)
    return ctx.db.scalar(q) is not None


@router.post("/models")
def create_model(body: ModelIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        _get_provider(ctx, body.provider_id)
        if _model_dupe(ctx, body):
            raise AppError(409, "NAME_EXISTS", "该提供方下已有同名模型")
        m = LlmModel(tenant_id=ctx.runtime.tenant_id)
        _apply_model(m, body, ctx.user.username)
        ctx.db.add(m)
        ctx.db.flush()
        ctx.audit("llm.model.create", "llm_model", m.id, after=json.dumps(_model_view(m), ensure_ascii=False, default=str))
    return _model_view(m)


@router.put("/models/{model_id}")
def update_model(model_id: int, body: ModelIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        m = _get_model(ctx, model_id)
        _get_provider(ctx, body.provider_id)
        if _model_dupe(ctx, body, exclude_id=m.id):
            raise AppError(409, "NAME_EXISTS", "该提供方下已有同名模型")
        before = json.dumps(_model_view(m), ensure_ascii=False, default=str)
        _apply_model(m, body, ctx.user.username)
        ctx.db.flush()
        ctx.audit("llm.model.update", "llm_model", m.id, before=before,
                  after=json.dumps(_model_view(m), ensure_ascii=False, default=str))
    return _model_view(m)


@router.delete("/models/{model_id}")
def delete_model(model_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        m = _get_model(ctx, model_id)
        before = json.dumps(_model_view(m), ensure_ascii=False, default=str)
        ctx.db.delete(m)
        ctx.audit("llm.model.delete", "llm_model", model_id, before=before)
    return {"ok": True}


@router.post("/models/{model_id}/test")
def test_model(model_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    m = _get_model(ctx, model_id)
    p = _get_provider(ctx, m.provider_id)
    key = ctx.runtime.vault.reveal(ctx.db, p.secret_ref)
    return check_model(p.base_url, key, p.timeout_seconds, m.model_name)
