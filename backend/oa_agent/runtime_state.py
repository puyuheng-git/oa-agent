"""进程级运行时容器：安装模式 / 正常模式切换、数据库、密钥、KV。"""

from __future__ import annotations

import logging
import threading

from fastapi import Request
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from oa_agent.bootstrap.files import (
    Bootstrap,
    ensure_setup_token,
    is_installed,
    load_or_create_master_key,
    read_bootstrap,
)
from oa_agent.config.crypto import Cipher
from oa_agent.config.schema import GROUPS
from oa_agent.config.schema import default as default_setting
from oa_agent.config.service import SettingsService
from oa_agent.config.vault import SecretVault
from oa_agent.db.engine import make_engine, make_sessionmaker
from oa_agent.db.migrate import revision_status, upgrade_head
from oa_agent.kv import KVManager, assert_production_kv
from oa_agent.observability.audit import AuditService
from oa_agent.observability.redact import redact
from oa_agent.runtime.engine import AgentEngine
from oa_agent.settings import AppSettings

log = logging.getLogger(__name__)

SETUP = "setup"
NORMAL = "normal"


class AppRuntime:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.tenant_id = settings.tenant_id
        self.mode = SETUP
        self.cipher: Cipher | None = None
        self.bootstrap: Bootstrap | None = None
        self.db_engine: Engine | None = None
        self._sessionmaker: sessionmaker[Session] | None = None
        self.kv = KVManager()
        self.vault: SecretVault | None = None
        self.settings_svc: SettingsService | None = None
        self.audit = AuditService(self.tenant_id)
        self.install_lock = threading.Lock()
        self.engine: AgentEngine | None = None
        self.wecom = None   # 企业微信长连接渠道（正常模式启动）
        self.pack_registry = None  # PackRegistry | None；正常模式 boot 后挂载
        self.last_good_settings: dict[str, dict] = {}
        self.stats_cache: dict[tuple, tuple[float, dict]] = {}

    def boot(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.cipher = Cipher(load_or_create_master_key(self.settings))
        self.vault = SecretVault(self.cipher, self.tenant_id)
        self.settings_svc = SettingsService(self.vault, self.tenant_id)
        if is_installed(self.settings):
            self.enter_normal_mode()
        else:
            ensure_setup_token(self.settings)

    def enter_normal_mode(self) -> None:
        self.bootstrap = read_bootstrap(self.settings, self.cipher)
        self.db_engine = make_engine(self.bootstrap.database)
        self._sessionmaker = make_sessionmaker(self.db_engine)
        self.mode = NORMAL
        self._ensure_migrated()
        self.reload_redis()
        assert_production_kv(self.kv.current, self.settings)
        self.engine = AgentEngine(self.settings, self.session, self.tenant_id, self._run_timeout,
                                  self._retention_days, self.setting)
        self.engine.start()
        self._load_pack_registry()
        from oa_agent.channels.wecom import WeComChannel  # 依赖 chat.service，延迟导入避免循环

        self.wecom = WeComChannel(self)
        self.wecom.start()

    def _load_pack_registry(self) -> None:
        """扫描 packs 目录并挂载 PackRegistry；启停覆盖来自 settings.packs。"""
        from oa_agent.packs.registry import PackRegistry
        from oa_agent.packs.state import load_disabled_ids, load_enabled_ids

        try:
            packs_settings = self.group_settings("packs")
            disabled = load_disabled_ids(packs_settings)
            enabled = load_enabled_ids(packs_settings)
        except Exception:  # noqa: BLE001 — 配置暂不可用时按全部默认启用
            log.exception("读取 packs 启停配置失败，按默认启用加载 PackRegistry")
            disabled = []
            enabled = []
        try:
            self.pack_registry = PackRegistry.from_disk(
                disabled_ids=disabled,
                enabled_ids=enabled,
            )
        except Exception:  # noqa: BLE001
            log.exception("加载 PackRegistry 失败")
            self.pack_registry = None

    def _ensure_migrated(self) -> None:
        """升级代码后直接启动 uvicorn（未走启动脚本）时补跑迁移；迁移只新增表/列。失败时 readyz 报告 migration_pending。"""
        try:
            status = revision_status(self.db_engine)
            if status["up_to_date"]:
                return
            log.warning("数据库迁移版本落后（%s → %s），自动执行迁移", status["current"], status["head"])
            upgrade_head(self.db_engine)
        except Exception as exc:  # noqa: BLE001
            log.error("数据库迁移失败，请手动执行 `cd backend && uv run alembic upgrade head`：%s",
                      redact(f"{type(exc).__name__}: {exc}"))

    def group_settings(self, group: str) -> dict:
        """每次读库以保证热生效；库不可用时用最近一次成功读取的值，再没有则用默认值（安装模式同样用默认值）。"""
        try:
            with self.session() as db:
                values = self.settings_svc.effective(db, group)
        except Exception:  # noqa: BLE001
            if group in self.last_good_settings:
                log.error("读取配置 %s 失败，沿用最近一次成功读取的值", group)
                return self.last_good_settings[group]
            if self.mode == NORMAL:
                log.exception("读取配置 %s 失败且无缓存，使用默认值", group)
            return GROUPS[group].defaults()
        self.last_good_settings[group] = values
        return values

    def setting(self, group: str, key: str):
        value = self.group_settings(group).get(key)
        return default_setting(group, key) if value is None or value == "" else value

    def _run_timeout(self) -> int:
        return int(self.setting("runtime", "run_timeout_seconds"))

    def _retention_days(self) -> int:
        return int(self.setting("runtime", "event_retention_days"))

    def reload_redis(self) -> None:
        try:
            with self.session() as db:
                cfg = self.settings_svc.effective(db, "redis")
        except Exception:  # noqa: BLE001 —— 数据库暂不可用时保持内存兜底，由 readyz 如实报告
            log.exception("读取 Redis 配置失败")
            cfg = None
        self.kv.configure(cfg)

    def session(self) -> Session:
        if self._sessionmaker is None:
            raise RuntimeError("系统未安装")
        return self._sessionmaker()

    def shutdown(self) -> None:
        mcp_client = getattr(self, "mcp_client", None)  # 出站 MCP 会话池（惰性创建，见 executor.mcp_runtime）
        if mcp_client is not None and hasattr(mcp_client, "close"):
            try:
                mcp_client.close()
            except Exception:  # noqa: BLE001 — 关闭尽力而为
                log.warning("关闭出站 MCP 会话池失败", exc_info=True)
        if self.wecom is not None:
            self.wecom.stop()
        if self.engine is not None:
            self.engine.stop()
        if self.db_engine is not None:
            self.db_engine.dispose()


def get_runtime(request: Request) -> AppRuntime:
    return request.app.state.runtime
