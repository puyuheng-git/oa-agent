"""/v1/admin/llm/*：LLM 提供方与模型。"""

from __future__ import annotations

import json
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, HttpUrl, field_validator

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.db.models import LlmDefaults, LlmModel, LlmProvider, LlmRoute
from oa_agent.errors import AppError
from oa_agent.integrations.llm_check import check_model, check_provider
from oa_agent.runtime.llm import CAPABILITIES

DEFAULT_MAX_FAILOVER = 3

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
    max_input_tokens: int | None = Field(default=None, ge=1, le=10_000_000,
                                         description="模型上下文窗口（输入侧）；留空=默认 100000")
    purpose_tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=lambda: ["text"])
    model_tier: Literal["large", "small"] = "large"
    enabled: bool = True

    @field_validator("capabilities")
    @classmethod
    def _check_capabilities(cls, v: list[str]) -> list[str]:
        # 去重保序；不得为空，且必须落在允许集合内
        out = list(dict.fromkeys(v))
        if not out:
            raise ValueError("capabilities 至少选择一项")
        bad = [c for c in out if c not in CAPABILITIES]
        if bad:
            raise ValueError(f"不支持的能力：{', '.join(bad)}")
        return out


class DefaultsIn(BaseModel):
    global_default_model_id: int | None = None
    max_failover: int = Field(default=DEFAULT_MAX_FAILOVER, ge=1, le=10)


class RouteIn(BaseModel):
    capability: Literal["text", "vision", "multimodal", "embedding"]
    model_tier: Literal["large", "small"]
    model_ids: list[int] = Field(default_factory=list)
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


def _model_view(m: LlmModel, default_id: int | None = None) -> dict:
    params = m.params_json or {}
    return {
        "id": m.id, "provider_id": m.provider_id, "model_name": m.model_name, "display_name": m.display_name,
        "temperature": params.get("temperature"), "max_tokens": params.get("max_tokens"),
        "max_input_tokens": params.get("max_input_tokens"),
        "purpose_tags": m.purpose_tags or [], "capabilities": m.capabilities or ["text"],
        "model_tier": m.model_tier or "large", "is_default": default_id is not None and m.id == default_id,
        "enabled": m.enabled, "updated_by": m.updated_by, "updated_at": m.updated_at,
    }


def _get_defaults(ctx: AdminCtx) -> LlmDefaults | None:
    return ctx.db.scalar(sa.select(LlmDefaults).where(LlmDefaults.tenant_id == ctx.runtime.tenant_id))


def _default_model_id(ctx: AdminCtx) -> int | None:
    row = _get_defaults(ctx)
    return row.global_default_model_id if row else None


def _defaults_view(row: LlmDefaults | None) -> dict:
    return {
        "global_default_model_id": row.global_default_model_id if row else None,
        "max_failover": row.max_failover if row else DEFAULT_MAX_FAILOVER,
        "updated_by": row.updated_by if row else "", "updated_at": row.updated_at if row else None,
    }


def _upsert_defaults(ctx: AdminCtx) -> LlmDefaults:
    # 安装/迁移可能已种下默认行：有则复用，无则新增
    row = _get_defaults(ctx)
    if row is None:
        row = LlmDefaults(tenant_id=ctx.runtime.tenant_id, max_failover=DEFAULT_MAX_FAILOVER)
        ctx.db.add(row)
    return row


def _defaults_summary(row: LlmDefaults | None) -> str:
    v = _defaults_view(row)
    return json.dumps({"global_default_model_id": v["global_default_model_id"], "max_failover": v["max_failover"]})


def _route_view(r: LlmRoute, warnings: list[str] | None = None) -> dict:
    v = {
        "id": r.id, "capability": r.capability, "model_tier": r.model_tier, "model_ids": r.model_ids or [],
        "enabled": r.enabled, "updated_by": r.updated_by, "updated_at": r.updated_at,
    }
    if warnings is not None:
        v["warnings"] = warnings
    return v


def _route_summary(r: LlmRoute) -> str:
    return json.dumps({"capability": r.capability, "model_tier": r.model_tier, "model_ids": r.model_ids or [],
                       "enabled": r.enabled}, ensure_ascii=False)


def _get_route(ctx: AdminCtx, capability: str, model_tier: str) -> LlmRoute | None:
    return ctx.db.scalar(sa.select(LlmRoute).where(
        LlmRoute.tenant_id == ctx.runtime.tenant_id, LlmRoute.capability == capability,
        LlmRoute.model_tier == model_tier))


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


@router.get("/providers/{provider_id}/remote-models")
def list_remote_models(provider_id: int, ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    p = _get_provider(ctx, provider_id)
    key = ctx.runtime.vault.reveal(ctx.db, p.secret_ref)
    if not key:
        return {"ok": False, "error": "未配置 API Key，无法获取模型列表"}
    return check_provider(p.base_url, key, p.timeout_seconds, limit=200)


# ---- models ----

@router.get("/models")
def list_models(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    rows = ctx.db.scalars(sa.select(LlmModel).where(LlmModel.tenant_id == ctx.runtime.tenant_id)
                          .order_by(LlmModel.id)).all()
    default_id = _default_model_id(ctx)
    return {"items": [_model_view(m, default_id) for m in rows]}


def _apply_model(m: LlmModel, body: ModelIn, actor: str) -> None:
    m.provider_id, m.model_name = body.provider_id, body.model_name
    m.display_name = body.display_name or body.model_name
    m.capabilities, m.model_tier = list(body.capabilities), body.model_tier
    # 只持久化显式传入的采样/窗口参数；未传的键不保留（与历史 temperature/max_tokens 行为一致）
    m.params_json = {k: v for k, v in {
        "temperature": body.temperature,
        "max_tokens": body.max_tokens,
        "max_input_tokens": body.max_input_tokens,
    }.items() if v is not None}
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
        default_id = _default_model_id(ctx)
        ctx.audit("llm.model.create", "llm_model", m.id,
                  after=json.dumps(_model_view(m, default_id), ensure_ascii=False, default=str))
    return _model_view(m, default_id)


@router.put("/models/{model_id}")
def update_model(model_id: int, body: ModelIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        m = _get_model(ctx, model_id)
        _get_provider(ctx, body.provider_id)
        if _model_dupe(ctx, body, exclude_id=m.id):
            raise AppError(409, "NAME_EXISTS", "该提供方下已有同名模型")
        default_id = _default_model_id(ctx)
        before = json.dumps(_model_view(m, default_id), ensure_ascii=False, default=str)
        _apply_model(m, body, ctx.user.username)
        ctx.db.flush()
        ctx.audit("llm.model.update", "llm_model", m.id, before=before,
                  after=json.dumps(_model_view(m, default_id), ensure_ascii=False, default=str))
    return _model_view(m, default_id)


@router.delete("/models/{model_id}")
def delete_model(model_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        m = _get_model(ctx, model_id)
        before = json.dumps(_model_view(m, _default_model_id(ctx)), ensure_ascii=False, default=str)
        ctx.db.delete(m)
        ctx.audit("llm.model.delete", "llm_model", model_id, before=before)
    return {"ok": True}


@router.post("/models/{model_id}/set-default")
def set_default_model(model_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        # 校验模型归属后，upsert 租户默认行
        m = _get_model(ctx, model_id)
        row = _upsert_defaults(ctx)
        before = _defaults_summary(row if row.id else None)
        row.global_default_model_id, row.updated_by = m.id, ctx.user.username
        ctx.db.flush()
        ctx.audit("llm.model.set_default", "llm_model", m.id, before=before, after=_defaults_summary(row))
    return _defaults_view(row)


# ---- defaults ----

@router.get("/defaults")
def get_defaults(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    return _defaults_view(_get_defaults(ctx))


@router.put("/defaults")
def put_defaults(body: DefaultsIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        # 指定默认模型时必须属于本租户；None = 清空
        if body.global_default_model_id is not None:
            _get_model(ctx, body.global_default_model_id)
        row = _upsert_defaults(ctx)
        before = _defaults_summary(row if row.id else None)
        row.global_default_model_id, row.max_failover = body.global_default_model_id, body.max_failover
        row.updated_by = ctx.user.username
        ctx.db.flush()
        ctx.audit("llm.defaults.update", "llm_defaults", row.id, before=before, after=_defaults_summary(row))
    return _defaults_view(row)


# ---- routes ----

@router.get("/routes")
def list_routes(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    rows = ctx.db.scalars(sa.select(LlmRoute).where(LlmRoute.tenant_id == ctx.runtime.tenant_id)
                          .order_by(LlmRoute.id)).all()
    return {"items": [_route_view(r) for r in rows]}


def _route_warnings(ctx: AdminCtx, body: RouteIn, model_ids: list[int]) -> list[str]:
    # 一次性取回池内模型，校验归属并收集能力/规模不符警告（仍允许保存）
    models = {m.id: m for m in ctx.db.scalars(sa.select(LlmModel).where(
        LlmModel.tenant_id == ctx.runtime.tenant_id, LlmModel.id.in_(model_ids))).all()}
    missing = [i for i in model_ids if i not in models]
    if missing:
        raise AppError(404, "NOT_FOUND", f"模型不存在：{', '.join(str(i) for i in missing)}")
    warnings = []
    for i in model_ids:
        m = models[i]
        if body.capability not in (m.capabilities or ["text"]):
            warnings.append(f"模型 {i} 的 capabilities 不含 {body.capability}")
        if (m.model_tier or "large") != body.model_tier:
            warnings.append(f"模型 {i} 的 model_tier 不是 {body.model_tier}")
    return warnings


@router.put("/routes")
def put_route(body: RouteIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        # 去重保序后校验模型；覆盖或新建 (capability, model_tier) 池
        model_ids = list(dict.fromkeys(body.model_ids))
        warnings = _route_warnings(ctx, body, model_ids)
        r = _get_route(ctx, body.capability, body.model_tier)
        before = _route_summary(r) if r else None
        if r is None:
            r = LlmRoute(tenant_id=ctx.runtime.tenant_id, capability=body.capability, model_tier=body.model_tier)
            ctx.db.add(r)
        r.model_ids, r.enabled, r.updated_by = model_ids, body.enabled, ctx.user.username
        ctx.db.flush()
        ctx.audit("llm.route.put", "llm_route", r.id, before=before, after=_route_summary(r))
    return _route_view(r, warnings)


@router.delete("/routes/{capability}/{model_tier}")
def delete_route(capability: str, model_tier: str, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    with ctx.db.begin():
        r = _get_route(ctx, capability, model_tier)
        if r is None:
            raise AppError(404, "NOT_FOUND", "路由不存在")
        before, route_id = _route_summary(r), r.id
        ctx.db.delete(r)
        ctx.audit("llm.route.delete", "llm_route", route_id, before=before)
    return {"ok": True}


@router.post("/models/{model_id}/test")
def test_model(model_id: int, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    m = _get_model(ctx, model_id)
    p = _get_provider(ctx, m.provider_id)
    key = ctx.runtime.vault.reveal(ctx.db, p.secret_ref)
    return check_model(p.base_url, key, p.timeout_seconds, m.model_name)
