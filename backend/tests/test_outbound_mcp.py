"""出站 MCP Noop 边界。""

"""

from __future__ import annotations

import pytest

from oa_agent.executor.executor import Identity, ToolError
from oa_agent.executor.outbound import NoopOutboundMcpClient


def test_noop_outbound_raises():
    with pytest.raises(ToolError) as e:
        NoopOutboundMcpClient().call_tool("x", {}, identity=Identity(oa="a", authorization=""))
    assert e.value.code == "TOOL_NOT_AVAILABLE"
