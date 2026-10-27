"""出站 MCP Client 契约（D18=A）。

默认仍是 `NoopOutboundMcpClient`（未配置任何 server 时不发网络请求）；
配置了 server 后由调用方显式构造 `SdkOutboundMcpClient`（官方 `mcp` SDK + `SessionPool`）。

安全边界：

- 地址：仅配置白名单，禁止任意 URL / SSRF（见 `mcp_pool.validate_config`）。
- 身份：不得泄露 master.key、管理会话、保险箱明文；员工 `Identity` 默认**不**外传。
- 结果：`content` 转文本后截断 32KB 再进模型；二进制/图片一期占位省略。
- 员工面：不出现「MCP」字样；错误文案不含内网 URL。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

from oa_agent.executor.executor import Identity, ToolError
from oa_agent.executor.mcp_pool import MSG_BIZ, ServerConfig, SessionPool, config_from_row

MAX_RESULT_BYTES = 32 * 1024
TRUNCATED_SUFFIX = "\n…（内容过长，已截断）"
OMITTED_BINARY = "[二进制/图片内容已省略]"
MAX_LIST_PAGES = 100


class OutboundMcpClient(Protocol):
    def call_tool(
        self, name: str, arguments: dict, *, identity: Identity, server_id: int | None = None
    ) -> dict: ...


class NoopOutboundMcpClient:
    """未配置出站连接器时的占位实现；不发起网络请求。"""

    def call_tool(
        self, name: str, arguments: dict, *, identity: Identity, server_id: int | None = None
    ) -> dict:
        raise ToolError(
            "TOOL_NOT_AVAILABLE",
            "出站连接器未配置",
            user_message="该功能未对你开放。",
        )


def truncate_text(text: str, limit: int = MAX_RESULT_BYTES) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    cut = raw[:limit].decode("utf-8", errors="ignore")
    return cut + TRUNCATED_SUFFIX, True


def _block_text(block: Any) -> str:
    kind = getattr(block, "type", "")
    if kind == "text":
        return str(getattr(block, "text", ""))
    if kind == "resource":
        inner = getattr(block, "resource", None)
        text = getattr(inner, "text", None)
        return str(text) if text is not None else OMITTED_BINARY
    return OMITTED_BINARY  # image / audio / resource_link / 其它


def _coerce(server: Any) -> ServerConfig:
    return server if isinstance(server, ServerConfig) else config_from_row(server)


class SdkOutboundMcpClient:
    """真出站 MCP Client：stdio / Streamable HTTP；sse 明确要求改用 http。"""

    def __init__(
        self,
        resolver: Callable[[int], Any | None],
        pool: SessionPool | None = None,
        *,
        max_result_bytes: int = MAX_RESULT_BYTES,
    ):
        self._resolver = resolver
        self._pool = pool or SessionPool()
        self._limit = max_result_bytes

    @property
    def pool(self) -> SessionPool:
        return self._pool

    def close(self) -> None:
        self._pool.close()

    def list_tools(self, server: Any) -> list[dict]:
        cfg = _coerce(server)

        async def fetch(client: Any) -> list[dict]:
            tools: list[dict] = []
            cursor: str | None = None
            for _ in range(MAX_LIST_PAGES):
                page = await client.list_tools(cursor=cursor, cache_mode="refresh")
                for t in page.tools:
                    tools.append({
                        "name": t.name,
                        "description": getattr(t, "description", None) or "",
                        "input_schema": getattr(t, "input_schema", None) or {"type": "object"},
                        "output_schema": getattr(t, "output_schema", None),
                    })
                cursor = getattr(page, "next_cursor", None)
                if not cursor:
                    break
            return tools

        return self._pool.run(cfg, fetch)

    def call_tool(
        self, name: str, arguments: dict, *, identity: Identity, server_id: int | None = None
    ) -> dict:
        # identity 刻意不外传：默认不向 MCP 外传员工 oa / token
        server = self._resolver(server_id) if server_id is not None else None
        if server is None:
            raise ToolError("TOOL_NOT_AVAILABLE", "出站连接未配置", user_message="该功能未对你开放。")
        cfg = _coerce(server)
        result = self._pool.run(cfg, lambda client: client.call_tool(name, dict(arguments or {})))
        return self._shape(result, cfg)

    def _shape(self, result: Any, cfg: ServerConfig) -> dict:
        text = "\n".join(t for t in (_block_text(b) for b in (result.content or [])) if t)
        text, truncated = truncate_text(text, self._limit)
        if getattr(result, "is_error", False):
            raise ToolError("UPSTREAM_BIZ_ERROR", f"{cfg.name} 工具返回错误：{text[:200]}", user_message=MSG_BIZ)
        out: dict[str, Any] = {"text": text, "truncated": truncated}
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            try:
                blob = json.dumps(structured, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                blob = ""
            if blob and len(blob.encode("utf-8")) <= self._limit:
                out["structured"] = structured
        return out
