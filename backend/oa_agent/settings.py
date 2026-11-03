"""启动参数（仅环境变量）。业务配置一律在管理后台，不放这里。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from oa_agent.config.service import normalize_origin

REPO_ROOT = Path(__file__).resolve().parents[2]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OA_AGENT_", extra="ignore")

    data_dir: Path = REPO_ROOT / "data"
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    master_key: str | None = None
    """base64 编码的 32 字节主密钥；设置后覆盖 data/master.key。"""
    cookie_secure: bool = True
    tenant_id: str = "dscpa"
    allow_sqlite: bool = False
    """仅测试使用：允许安装向导以 SQLite 代替 MySQL。"""
    require_redis: bool = False
    """生产多实例须为 True；为 True 时进程内 MemoryKV 会在启动校验中被拒绝。"""
    chat_cors_origins: str = ""
    """逗号分隔的员工对话静态站 Origin（如 https://chat.example.com）。环境变量 OA_AGENT_CHAT_CORS_ORIGINS。"""

    def chat_cors_allowlist(self) -> list[str]:
        out: list[str] = []
        for part in self.chat_cors_origins.split(","):
            origin = normalize_origin(part)
            if origin:
                out.append(origin)
        return out

    @property
    def bootstrap_path(self) -> Path:
        return self.data_dir / "bootstrap.json"

    @property
    def master_key_path(self) -> Path:
        return self.data_dir / "master.key"

    @property
    def setup_token_path(self) -> Path:
        return self.data_dir / "setup.token"
