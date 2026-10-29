"""/v1/admin/settings/*：配置中心。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import AdminCtx, admin_read, admin_write
from oa_agent.bootstrap import installer
from oa_agent.bootstrap.files import DbParams, db_public_view, write_bootstrap
from oa_agent.config.schema import GROUPS
from oa_agent.errors import AppError
from oa_agent.kv import check_redis

router = APIRouter(prefix="/v1/admin/settings", tags=["admin-settings"])


class GroupUpdateIn(BaseModel):
    values: dict = Field(default_factory=dict)
    clear_secrets: list[str] = Field(default_factory=list)


class DatabaseIn(BaseModel):
    host: str = Field(max_length=255)
    port: int = Field(ge=1, le=65535)
    user: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=256, description="留空 = 沿用当前密码")
    database: str = Field(min_length=1, max_length=64)


def _run_test(group: str, cfg: dict) -> dict:
    if group == "redis":
        if not cfg.get("url"):
            raise AppError(422, "VALIDATION_ERROR", "请先填写 Redis 地址")
        return check_redis(cfg["url"], int(cfg.get("db") or 0), cfg.get("password"))
    raise AppError(400, "NOT_TESTABLE", "该配置组暂不支持测试连接")


def _guard_upstreams_in_use(ctx: AdminCtx, values: dict) -> None:
    """用完整提交值合并（须含 default_upstream_key，否则会误报默认上游不在列表中）。"""
    try:
        candidate = ctx.runtime.settings_svc.merged_candidate(ctx.db, "oa", values)
        keep = {u["key"] for u in (candidate.get("upstreams") or [])}
        catalog = getattr(ctx.runtime.engine, "catalog", None)
        used = catalog.tools_using_upstreams(ctx.db, keep) if catalog else []
    finally:
        ctx.db.rollback()
    if used:
        raise AppError(409, "UPSTREAM_IN_USE", f"以下 Tool 仍在使用要删除的地址，请先修改这些 Tool：{'、'.join(used)}")


@router.get("")
def list_groups(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    groups = [ctx.runtime.settings_svc.view(ctx.db, g) for g in GROUPS]
    wecom = ctx.runtime.wecom.status if ctx.runtime.wecom else {"status": "未启动"}
    return {"groups": groups, "redis_status": ctx.runtime.kv.status(), "wecom_status": wecom}


@router.get("/database")
def get_database(ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    db = ctx.runtime.bootstrap.database
    return {"values": db_public_view(db), "password": {"is_set": bool(db.password), "display": "已设置" if db.password else "未设置"},
            "apply_mode": "测试通过后写入 bootstrap.json，重启生效"}


@router.post("/database/test")
def test_database(body: DatabaseIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    params = _db_candidate(ctx, body)
    return installer.check_db(params)


@router.put("/database")
def update_database(body: DatabaseIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    params = _db_candidate(ctx, body)
    probe = installer.check_db(params)
    if not probe["ok"]:
        raise AppError(400, "DB_CONNECT_FAILED", f"测试连接失败，未保存：{probe['error']}")
    if not probe.get("database_exists"):
        raise AppError(400, "DB_NOT_FOUND", "目标库不存在，请先建库并执行迁移")
    before = json.dumps(db_public_view(ctx.runtime.bootstrap.database), ensure_ascii=False)
    after = json.dumps(db_public_view(params), ensure_ascii=False)
    with ctx.db.begin():
        ctx.audit("setting.database.update", "setting", "database", before=before,
                  after=after + (" 密码：已变更" if body.password else ""))
    write_bootstrap(ctx.runtime.settings, ctx.runtime.cipher, params, ctx.runtime.bootstrap.installed_at)
    return {"ok": True, "restart_required": True}


def _db_candidate(ctx: AdminCtx, body: DatabaseIn) -> DbParams:
    current = ctx.runtime.bootstrap.database
    if current.driver != "mysql":
        raise AppError(400, "NOT_SUPPORTED",
                       "当前实例使用 SQLite（仅测试用），不能在线切换到 MySQL（数据与管理员账号不会迁移）。"
                       "请停服务、删除该 data 目录下的 bootstrap.json 后重启，在安装向导中填写 MySQL")
    params = DbParams(body.host, body.port, body.user, body.password or current.password, body.database)
    installer.validate_params(params, allow_sqlite=False)
    return params


@router.get("/{group}")
def get_group(group: str, ctx: AdminCtx = Depends(admin_read("sys.setting.view"))):
    return ctx.runtime.settings_svc.view(ctx.db, group)


@router.post("/{group}/test")
def test_group(group: str, body: GroupUpdateIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    svc = ctx.runtime.settings_svc
    return _run_test(group, svc.merged_candidate(ctx.db, group, body.values))


@router.put("/{group}")
def update_group(group: str, body: GroupUpdateIn, ctx: AdminCtx = Depends(admin_write("sys.setting.edit"))):
    svc = ctx.runtime.settings_svc
    if GROUPS.get(group) and GROUPS[group].testable:
        candidate = svc.merged_candidate(ctx.db, group, body.values)
        for key in body.clear_secrets:
            candidate[key] = None
        if candidate.get("url"):
            result = _run_test(group, candidate)
            if not result["ok"]:
                raise AppError(400, "CONNECTION_TEST_FAILED", f"测试连接失败，未保存：{result['error']}")
        ctx.db.rollback()
    if group == "oa" and "upstreams" in body.values:
        _guard_upstreams_in_use(ctx, body.values)
    with ctx.db.begin():
        before = svc.summary(ctx.db, group)
        changed = svc.update(ctx.db, group, body.values, body.clear_secrets, ctx.user.username)
        if changed:
            secret_keys = {f.key for f in GROUPS[group].fields if f.kind == "secret"}
            after = svc.summary(ctx.db, group)
            notes = [f"{k}：已变更" for k in changed if k in secret_keys]
            ctx.audit("setting.update", "setting", group, before=before,
                      after=after + (" | " + "；".join(notes) if notes else ""))
    if changed and group == "redis":
        ctx.runtime.reload_redis()
    return {"changed": changed, "group": svc.view(ctx.db, group), "redis_status": ctx.runtime.kv.status()}
