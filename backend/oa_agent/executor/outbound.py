"""出站 MCP Client 契约（D18=A）；默认 Noop 占位。

安全边界（真实实现须遵守，本期仅有 Noop）：

- 地址：仅配置白名单，禁止任意 URL / SSRF。
- 身份：不得泄露 master.key、管理会话、保险箱明文；员工身份按约定注入且可关闭。
- 结果：进模型前须白名单/截断（与 Executor 纪律一致）。
- 员工面：不出现「MCP」字样。

本期无任何生产路径实例化非 Noop 实现；可不挂路由。
"""

from __future__ import annotations

from typing import Protocol

from oa_agent.executor.executor import Identity, ToolError


class OutboundMcpClient(Protocol):
    def call_tool(self, name: str, arguments: dict, *, identity: Identity) -> dict: ...


class NoopOutboundMcpClient:
    """未配置出站连接器时的占位实现；不发起网络请求。"""

    def call_tool(self, name: str, arguments: dict, *, identity: Identity) -> dict:
        raise ToolError(
            "TOOL_NOT_AVAILABLE",
            "出站连接器未配置",
            user_message="该功能未对你开放。",
        )
