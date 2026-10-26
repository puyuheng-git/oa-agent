"""/v1/setup/*：仅安装模式开放（模式拦截见 main.py）。"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from oa_agent.auth.rbac import request_meta
from oa_agent.bootstrap import installer
from oa_agent.bootstrap.files import DbParams, delete_setup_token, read_setup_token, write_bootstrap
from oa_agent.errors import AppError
from oa_agent.runtime_state import SETUP, get_runtime

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/setup", tags=["setup"])

TOKEN_FAIL_LIMIT = 10
TOKEN_FAIL_WINDOW = 15 * 60


class DbIn(BaseModel):
    host: str = Field(default="127.0.0.1", max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=256)
    database: str = Field(default="agent_ops", min_length=1, max_length=255)
    driver: str = "mysql"

    def params(self) -> DbParams:
        return DbParams(self.host, self.port, self.user, self.password, self.database, self.driver)


class AdminIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(default="", max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=128)


class TestDbIn(TokenIn):
    db: DbIn


class InstallIn(TokenIn):
    db: DbIn
    admin: AdminIn


def _check_token(request: Request, token: str) -> None:
    rt = get_runtime(request)
    ip = request.client.host if request.client else ""
    key = f"setup:tokenfail:{ip}"
    if int(rt.kv.current.get(key) or 0) >= TOKEN_FAIL_LIMIT:
        raise AppError(429, "TOO_MANY_ATTEMPTS", "安装令牌错误次数过多，请稍后再试")
    expected = read_setup_token(rt.settings)
    if not expected or not hmac.compare_digest(token.strip(), expected):
        rt.kv.current.incr(key, TOKEN_FAIL_WINDOW)
        raise AppError(401, "BAD_SETUP_TOKEN", "安装令牌无效（见服务启动日志或 data/setup.token）")


@router.get("/status")
def status(request: Request):
    return {"mode": get_runtime(request).mode}


@router.post("/verify-token")
def verify_token(body: TokenIn, request: Request):
    _check_token(request, body.token)
    return {"ok": True}


@router.post("/test-db")
def test_db(body: TestDbIn, request: Request):
    _check_token(request, body.token)
    params = body.db.params()
    installer.validate_params(params, get_runtime(request).settings.allow_sqlite)
    return installer.check_db(params)


@router.post("/install")
def install(body: InstallIn, request: Request):
    rt = get_runtime(request)
    _check_token(request, body.token)
    params = body.db.params()
    installer.validate_params(params, rt.settings.allow_sqlite)
    if not rt.install_lock.acquire(blocking=False):
        raise AppError(409, "INSTALL_IN_PROGRESS", "安装正在进行中")
    try:
        if rt.mode != SETUP:
            raise AppError(409, "ALREADY_INSTALLED", "系统已安装")
        probe = installer.check_db(params)
        if not probe["ok"]:
            raise AppError(400, "DB_CONNECT_FAILED", f"数据库连接失败：{probe['error']}")
        try:
            installer.install(params, rt.tenant_id, body.admin.username, body.admin.display_name,
                              body.admin.password, request_meta(request))
        except AppError:
            raise
        except Exception as exc:
            log.exception("安装失败")
            raise AppError(500, "INSTALL_FAILED", f"安装失败：{type(exc).__name__}: {exc}") from exc
        write_bootstrap(rt.settings, rt.cipher, params)
        delete_setup_token(rt.settings)
        rt.enter_normal_mode()
        log.warning("安装完成，已退出安装模式")
        return {"ok": True, "mode": rt.mode, "admin_url": "/admin/"}
    finally:
        rt.install_lock.release()
