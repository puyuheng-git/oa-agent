"""FastAPI 装配：安装模式 / 正常模式切换（设计 §5.1）。

启动：cd backend && uv run uvicorn oa_agent.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from oa_agent.admin import (
    accounts_api, audit_api, catalog_api, conversations_api, employees_api, interventions_api, llm_api, routing_api,
    runs_api, settings_api, workflows_api, mcp_servers_api, packs_api, connectors_api,
)
from oa_agent.auth import admin as admin_auth
from oa_agent.bootstrap import setup_api
from oa_agent.chat import router as chat_router
from oa_agent.config.service import normalize_origin
from oa_agent.db.migrate import revision_status
from oa_agent.db.models import LlmModel, LlmProvider
from oa_agent.errors import error_body, install_error_handlers
from oa_agent.ids import new_request_id
from oa_agent.runtime_state import NORMAL, SETUP, AppRuntime
from oa_agent.settings import AppSettings

log = logging.getLogger("oa_agent")

SETUP_PREFIXES = ("/setup", "/v1/setup")
ALWAYS_OPEN = ("/healthz", "/readyz", "/assets", "/favicon.ico")
SPA_ENTRIES = ("setup", "admin", "chat")
FRAME_CACHE_SECONDS = 30


def create_app(settings: AppSettings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    runtime = AppRuntime(settings or AppSettings())
    runtime.boot()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        runtime.shutdown()

    app = FastAPI(title="OA LangGraph Agent", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    install_error_handlers(app)
    frame_cache: dict = {"at": float("-inf"), "value": "'none'"}

    def frame_ancestors() -> str:
        """/chat 只允许被配置的 OA 域名嵌入；未配置时禁止嵌入。缓存 30 秒。"""
        if runtime.mode != NORMAL:
            return "'none'"
        now = time.monotonic()
        if now - frame_cache["at"] > FRAME_CACHE_SECONDS:
            frame_cache["at"] = now
            try:
                with runtime.session() as db:
                    origins = runtime.settings_svc.effective(db, "oa").get("allowed_frame_origins") or []
                origins = [o for o in map(normalize_origin, origins) if o]
                frame_cache["value"] = " ".join(origins) or "'none'"
            except Exception:  # noqa: BLE001 —— 读不到配置时沿用上次结果
                log.exception("读取 allowed_frame_origins 失败")
        return frame_cache["value"]

    @app.middleware("http")
    async def gate_and_headers(request: Request, call_next):
        rid = request.headers.get("X-Request-Id", "")[:64] or new_request_id()
        request.state.request_id = rid
        path = request.url.path
        is_setup_path = path.startswith(SETUP_PREFIXES)
        if runtime.mode == SETUP and not is_setup_path and not path.startswith(ALWAYS_OPEN) and path != "/":
            response = JSONResponse(error_body("NOT_INSTALLED", "系统未安装"), status_code=503)
        elif runtime.mode == NORMAL and is_setup_path:
            response = JSONResponse(error_body("NOT_FOUND", "安装向导已关闭"), status_code=404)
        else:
            response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if path.startswith("/chat"):
            response.headers.setdefault("Content-Security-Policy", f"frame-ancestors {frame_ancestors()}")
        else:
            response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
            response.headers.setdefault("X-Frame-Options", "DENY")
        if path.startswith("/v1/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for router in (setup_api.router, admin_auth.router, settings_api.router, llm_api.router,
                   accounts_api.router, audit_api.router, employees_api.router, runs_api.router,
                   routing_api.router, interventions_api.router,
                   catalog_api.tools_router, catalog_api.skills_router, catalog_api.visibility_router,
                   workflows_api.router, mcp_servers_api.router, packs_api.router, connectors_api.router,
                   conversations_api.router, chat_router.router):
        app.include_router(router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "mode": runtime.mode}

    @app.get("/readyz")
    def readyz():
        return _readiness(runtime)

    _mount_frontend(app, runtime)
    return app


def _readiness(rt: AppRuntime):
    if rt.mode == SETUP:
        return JSONResponse({"ready": False, "mode": SETUP, "database": {"status": "未配置"}}, status_code=503)
    checks: dict = {"mode": NORMAL}
    try:
        checks["database"] = {"status": "ok", "migration": revision_status(rt.db_engine)}
        if not checks["database"]["migration"]["up_to_date"]:
            checks["database"]["status"] = "migration_pending"
    except Exception as exc:  # noqa: BLE001
        from oa_agent.observability.redact import redact

        checks["database"] = {"status": "error", "error": redact(f"{type(exc).__name__}: {exc}")}
    checks["redis"] = rt.kv.status()
    if checks["database"]["status"] == "ok":
        with rt.session() as db:
            providers = db.scalar(sa.select(sa.func.count()).where(LlmProvider.enabled.is_(True)))
            models = db.scalar(sa.select(sa.func.count()).where(LlmModel.enabled.is_(True)))
        checks["llm"] = {
            "status": "已配置（未检测）" if providers and models else "未配置",
            "enabled_providers": providers,
            "enabled_models": models,
        }
    else:
        checks["llm"] = {"status": "未检测"}
    checks["observability"] = rt.engine.sink.status() if rt.engine else {"status": "未启动"}
    checks["wecom"] = rt.wecom.status if rt.wecom else {"status": "未启动"}
    if rt.engine:
        current = rt.engine.release_provider._current
        checks["agent"] = {
            "registered_tools": rt.engine.registry.names(),
            "skills": {name: ("ok" if s.enabled and s.valid else "不可用")
                       for name, s in rt.engine.skill_states.items()},
            "workflow_release": {"release_id": current.release_id, "version_no": current.version_no}
            if current else "未加载",
        }
    ready = checks["database"]["status"] == "ok"
    checks["ready"] = ready
    return JSONResponse(checks, status_code=200 if ready else 503)


def _mount_frontend(app: FastAPI, rt: AppRuntime) -> None:
    dist = rt.settings.frontend_dist
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/setup/" if rt.mode == SETUP else "/admin/")

    @app.get("/embed.js", include_in_schema=False)
    def embed_js():
        script = dist / "embed.js"
        if not script.exists():
            return JSONResponse(error_body("FRONTEND_NOT_BUILT", "前端未构建：cd frontend && npm run build"),
                                status_code=404)
        # 显式 charset：OA 页面是 GBK，脚本里的中文必须按 UTF-8 解码
        return FileResponse(script, media_type="application/javascript; charset=utf-8",
                            headers={"Cache-Control": "no-cache"})

    def spa_handlers(entry: str):
        index = dist / entry / "index.html"

        def serve():
            if not index.exists():
                return JSONResponse(error_body("FRONTEND_NOT_BUILT", f"前端未构建：cd frontend && npm run build（{entry}）"),
                                    status_code=404)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        def redirect():
            return RedirectResponse(f"/{entry}/")

        return serve, redirect

    for entry in SPA_ENTRIES:
        serve, redirect = spa_handlers(entry)
        app.add_api_route(f"/{entry}/", serve, include_in_schema=False)
        app.add_api_route(f"/{entry}", redirect, include_in_schema=False)


def __getattr__(name: str):
    """`uvicorn oa_agent.main:app` 时才构建应用，避免 import 即触发 boot。"""
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
