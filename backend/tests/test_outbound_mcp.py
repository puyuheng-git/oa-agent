"""出站 MCP：Noop 默认边界 + SDK Client / 会话池（mock，不依赖外网 MCP 服务）。"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from oa_agent.executor.executor import Identity, ToolError
from oa_agent.executor.mcp_pool import ServerConfig, SessionPool, config_from_row
from oa_agent.executor.outbound import (
    MAX_RESULT_BYTES,
    NoopOutboundMcpClient,
    SdkOutboundMcpClient,
)

IDENTITY = Identity(oa="a", authorization="Bearer secret-token")


def test_noop_outbound_raises():
    with pytest.raises(ToolError) as e:
        NoopOutboundMcpClient().call_tool("x", {}, identity=IDENTITY)
    assert e.value.code == "TOOL_NOT_AVAILABLE"
    assert e.value.user_message == "该功能未对你开放。"


# ---------------------------------------------------------------- fakes


class FakeClient:
    """模拟 mcp.client.Client 的最小面。"""

    def __init__(self, *, text="ok", is_error=False, pages=None, call_exc=None, delay=0.0):
        self.text = text
        self.is_error = is_error
        self.pages = pages or [[{"name": "t1"}]]
        self.call_exc = call_exc
        self.delay = delay
        self.calls: list[tuple[str, dict]] = []

    async def call_tool(self, name, arguments=None, **_):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.call_exc:
            raise self.call_exc
        self.calls.append((name, arguments))
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text), SimpleNamespace(type="image", data="AAAA")],
            structured_content=None,
            is_error=self.is_error,
        )

    async def list_tools(self, *, cursor=None, **_):
        idx = 0 if cursor is None else int(cursor)
        tools = [
            SimpleNamespace(name=t["name"], description="d", input_schema={"type": "object"})
            for t in self.pages[idx]
        ]
        nxt = str(idx + 1) if idx + 1 < len(self.pages) else None
        return SimpleNamespace(tools=tools, next_cursor=nxt)


class Opener:
    def __init__(self, client=None, *, fail=None):
        self.client = client or FakeClient()
        self.fail = fail
        self.opened: list[ServerConfig] = []
        self.closed = 0

    def __call__(self, cfg):
        @asynccontextmanager
        async def cm():
            if self.fail:
                raise self.fail
            self.opened.append(cfg)
            try:
                yield self.client
            finally:
                self.closed += 1

        return cm()


def make_cfg(**kw) -> ServerConfig:
    base = dict(id=1, name="s1", transport="http", url="https://mcp.example.com/mcp", timeout_seconds=5)
    base.update(kw)
    return ServerConfig(**base)


def make_client(opener, cfg=None, **kw):
    pool = SessionPool(opener=opener, idle_seconds=kw.pop("idle_seconds", 300))
    cfgs = {1: cfg or make_cfg()}
    c = SdkOutboundMcpClient(resolver=cfgs.get, pool=pool, **kw)
    return c, pool


# ---------------------------------------------------------------- call_tool


def test_call_tool_returns_text_and_omits_binary():
    opener = Opener(FakeClient(text="hello"))
    c, pool = make_client(opener)
    try:
        out = c.call_tool("echo", {"q": 1}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert out["text"].startswith("hello")
    assert "图片" in out["text"] or "省略" in out["text"]
    assert out["truncated"] is False
    assert opener.client.calls == [("echo", {"q": 1})]


def test_call_tool_truncates_to_32kb():
    opener = Opener(FakeClient(text="啊" * 40000))  # 3 字节/字 => 120KB
    c, pool = make_client(opener)
    try:
        out = c.call_tool("big", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert out["truncated"] is True
    assert len(out["text"].encode("utf-8")) <= MAX_RESULT_BYTES + 64  # 允许截断提示后缀
    assert MAX_RESULT_BYTES == 32 * 1024


def test_identity_never_forwarded():
    opener = Opener()
    c, pool = make_client(opener)
    try:
        c.call_tool("echo", {"q": 1}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert "secret-token" not in repr(opener.client.calls)
    assert "secret-token" not in repr(opener.opened)


def test_tool_is_error_maps_to_tool_error():
    c, pool = make_client(Opener(FakeClient(text="boom", is_error=True)))
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "UPSTREAM_BIZ_ERROR"
    assert "MCP" not in e.value.user_message


def test_unknown_server_not_available():
    c, pool = make_client(Opener())
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=99)
        with pytest.raises(ToolError) as e2:
            c.call_tool("x", {}, identity=IDENTITY, server_id=None)
    finally:
        pool.close()
    assert e.value.code == "TOOL_NOT_AVAILABLE"
    assert e.value.user_message == "该功能未对你开放。"
    assert e2.value.code == "TOOL_NOT_AVAILABLE"


def test_disabled_server_not_available():
    c, pool = make_client(Opener(), cfg=make_cfg(enabled=False))
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "TOOL_NOT_AVAILABLE"


def test_connect_failure_hides_url():
    opener = Opener(fail=ConnectionError("cannot reach http://10.0.0.8:9000/mcp"))
    c, pool = make_client(opener)
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "UPSTREAM_UNAVAILABLE"
    assert e.value.retryable
    assert "10.0.0.8" not in e.value.user_message
    assert "10.0.0.8" not in e.value.message
    assert "MCP" not in e.value.user_message


def test_call_timeout_maps_to_upstream_timeout():
    c, pool = make_client(Opener(FakeClient(delay=2.0)), cfg=make_cfg(timeout_seconds=1))
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("slow", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "UPSTREAM_TIMEOUT"


def test_call_exception_evicts_session_and_reconnects():
    opener = Opener(FakeClient(call_exc=RuntimeError("dead 10.1.1.1")))
    c, pool = make_client(opener)
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
        assert e.value.code == "UPSTREAM_UNAVAILABLE"
        assert "10.1.1.1" not in e.value.message
        opener.client.call_exc = None
        c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert len(opener.opened) == 2


# ---------------------------------------------------------------- list_tools


def test_list_tools_paginates():
    opener = Opener(FakeClient(pages=[[{"name": "a"}, {"name": "b"}], [{"name": "c"}]]))
    c, pool = make_client(opener)
    try:
        tools = c.list_tools(make_cfg())
    finally:
        pool.close()
    assert [t["name"] for t in tools] == ["a", "b", "c"]
    assert tools[0]["input_schema"] == {"type": "object"}


def test_list_tools_accepts_orm_row():
    row = SimpleNamespace(
        id=1, name="s1", enabled=True, transport="http", url="https://mcp.example.com/mcp",
        command=None, args_json=None, env_json=None, timeout_seconds=5,
    )
    c, pool = make_client(Opener())
    try:
        assert [t["name"] for t in c.list_tools(row)] == ["t1"]
    finally:
        pool.close()


# ---------------------------------------------------------------- pool


def test_pool_reuses_session():
    opener = Opener()
    c, pool = make_client(opener)
    try:
        c.call_tool("x", {}, identity=IDENTITY, server_id=1)
        c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert len(opener.opened) == 1
    assert opener.closed == 1  # close() 后释放


def test_pool_idle_reclaim():
    opener = Opener()
    c, pool = make_client(opener, idle_seconds=0)
    try:
        c.call_tool("x", {}, identity=IDENTITY, server_id=1)
        c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert len(opener.opened) == 2


def test_pool_ensure_returns_session():
    opener = Opener()
    pool = SessionPool(opener=opener)
    try:
        assert pool.ensure(make_cfg()) is opener.client
        assert pool.ensure(make_cfg()) is opener.client
    finally:
        pool.close()


# ---------------------------------------------------------------- 安全边界


def test_sse_gives_upgrade_error():
    c, pool = make_client(Opener(), cfg=make_cfg(transport="sse"))
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "UPSTREAM_UNAVAILABLE"
    assert "http" in e.value.message
    assert "请改用 http" in e.value.message


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x/y", "", None])
def test_bad_url_scheme_rejected(url):
    c, pool = make_client(Opener(), cfg=make_cfg(url=url))
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "TOOL_NOT_AVAILABLE"


def test_url_allowlist_enforced():
    opener = Opener()
    pool = SessionPool(opener=opener, url_allowlist=["https://mcp.example.com"])
    try:
        pool.ensure(make_cfg())
        with pytest.raises(ToolError):
            pool.ensure(make_cfg(id=2, name="evil", url="https://evil.example.org/mcp"))
    finally:
        pool.close()


def test_stdio_requires_absolute_command():
    c, pool = make_client(Opener(), cfg=make_cfg(transport="stdio", url=None, command="npx"))
    try:
        with pytest.raises(ToolError) as e:
            c.call_tool("x", {}, identity=IDENTITY, server_id=1)
    finally:
        pool.close()
    assert e.value.code == "TOOL_NOT_AVAILABLE"


def test_config_from_row_merges_secrets():
    row = SimpleNamespace(
        id=3, name="s", enabled=True, transport="stdio", command=sys.executable, args_json=["a"],
        env_json=None, url=None, timeout_seconds=7,
    )
    cfg = config_from_row(row, env={"K": "v"}, headers={"H": "1"})
    assert cfg.env == {"K": "v"} and cfg.headers == {"H": "1"} and cfg.args == ["a"]
    assert "'K'" not in repr(cfg) and "'H'" not in repr(cfg)  # repr 不泄露密钥字段


# ---------------------------------------------------------------- 真 stdio（本地子进程，无外网）


STDIO_SERVER = textwrap.dedent(
    """
    from mcp.server.mcpserver import MCPServer
    app = MCPServer("fixture")

    @app.tool()
    def echo(text: str) -> str:
        return "echo:" + text

    @app.tool()
    def big() -> str:
        return "x" * 100000

    if __name__ == "__main__":
        app.run("stdio")
    """
)


def test_real_stdio_roundtrip(tmp_path):
    script = tmp_path / "srv.py"
    script.write_text(STDIO_SERVER, encoding="utf-8")
    cfg = make_cfg(transport="stdio", url=None, command=sys.executable, args=[str(script)], timeout_seconds=30)
    pool = SessionPool()
    c = SdkOutboundMcpClient(resolver={1: cfg}.get, pool=pool)
    try:
        names = {t["name"] for t in c.list_tools(cfg)}
        assert {"echo", "big"} <= names
        assert "echo:hi" in c.call_tool("echo", {"text": "hi"}, identity=IDENTITY, server_id=1)["text"]
        big = c.call_tool("big", {}, identity=IDENTITY, server_id=1)
        assert big["truncated"] is True
    finally:
        pool.close()
