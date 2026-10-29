"""出站 MCP 运行时装配（Task 7）：Vault 密钥 → ServerConfig → SdkOutboundMcpClient。

- 客户端挂在 `AppRuntime.mcp_client`（进程级，惰性创建；测试可直接替换为替身）。
- 运行期解析（`make_resolver`）比管理端探测更严：连接须已启用、曾同步成功，远程地址每次都按**当前**白名单复核。
- headers / env 明文只在服务端内存里流转，不进日志、事件或响应。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any
from urllib.parse import urlsplit

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import McpServer
from oa_agent.executor.mcp_pool import ServerConfig, config_from_row

log = logging.getLogger(__name__)

SYNC_OK = "ok"
SYNC_ERROR = "error"
_DEFAULT_PORTS = {"http": 80, "https": 443}
_lock = threading.Lock()


def secret_name(server_name: str, kind: str) -> str:
    return f"mcp.{server_name}.{kind}"


def _origin_key(url: str) -> tuple[str, str, int] | None:
    parts = urlsplit((url or "").strip())
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    try:
        port = parts.port or _DEFAULT_PORTS[parts.scheme]
    except ValueError:
        return None
    return parts.scheme, parts.hostname.lower(), port


def origin_allowed(allowed: list[str] | None, url: str | None) -> bool:
    key = _origin_key(url or "")
    if key is None:
        return False
    return key in {k for k in (_origin_key(o) for o in (allowed or [])) if k}


def _load_json_secret(rt: Any, db: Session, server_name: str, kind: str) -> dict[str, str]:
    raw = rt.vault.reveal(db, secret_name(server_name, kind))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        log.error("MCP 连接 %s 的 %s 密文无法解析", server_name, kind)
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def build_config(rt: Any, db: Session, row: McpServer) -> ServerConfig:
    """McpServer 行 + Vault 里的 headers/env → ServerConfig（含明文，仅限服务端内部）。"""
    return config_from_row(
        row,
        env=_load_json_secret(rt, db, row.name, "env"),
        headers=_load_json_secret(rt, db, row.name, "headers"),
    )


def make_resolver(rt: Any):
    """`server_id → ServerConfig | None`；不满足运行条件一律返回 None（调用方映射为「未对你开放」）。"""

    def resolve(server_id: int) -> ServerConfig | None:
        with rt.session() as db:
            row = db.scalar(sa.select(McpServer).where(McpServer.tenant_id == rt.tenant_id,
                                                       McpServer.id == server_id))
            if row is None or not row.enabled or row.last_sync_result != SYNC_OK:
                return None
            if row.transport != "stdio":
                allowed = rt.settings_svc.effective(db, "mcp").get("allowed_origins") or []
                if not origin_allowed(allowed, row.url):
                    log.warning("MCP 连接 %s 的地址已不在白名单内，拒绝调用", row.name)
                    return None
            return build_config(rt, db, row)

    return resolve


def get_mcp_client(rt: Any):
    """进程级出站客户端；未启用任何连接时不会建立会话（池按需连接）。"""
    client = getattr(rt, "mcp_client", None)
    if client is None:
        with _lock:
            client = getattr(rt, "mcp_client", None)
            if client is None:
                from oa_agent.executor.outbound import SdkOutboundMcpClient

                client = SdkOutboundMcpClient(resolver=make_resolver(rt))
                rt.mcp_client = client
    return client
