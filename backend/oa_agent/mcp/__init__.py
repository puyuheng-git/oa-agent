"""兼容层：历史 import `oa_agent.mcp` 转发到 `oa_agent.executor`。

新代码请使用 `oa_agent.executor`。本包仅为短期别名，不新增实现。
"""

from __future__ import annotations

from oa_agent.executor import *  # noqa: F403
