"""出站 MCP 会话池（Task 6）。

- 官方 `mcp` SDK 做协议；本模块只管：配置校验（SSRF/命令白名单）、会话复用、空闲回收、并发上限、错误映射。
- 同步入口（Executor 是同步的）→ 内部一个专用 asyncio 事件循环线程；每个 server 一个常驻 task
  持有 `async with Client(...)`（anyio 要求进入/退出在同一 task）。
- 失败一律映射为 `ToolError`；用户文案不含内网 URL、也不出现「MCP」字样。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, TypeVar
from urllib.parse import urlsplit

from oa_agent.executor.executor import ToolError

log = logging.getLogger(__name__)

T = TypeVar("T")

MSG_NOT_AVAILABLE = "该功能未对你开放。"
MSG_UNAVAILABLE = "上游暂不可用，请稍后再试。"
MSG_TIMEOUT = "上游响应超时，请稍后再试。"
MSG_BIZ = "操作未能完成，请稍后重试。"

Opener = Callable[["ServerConfig"], AbstractAsyncContextManager[Any]]


@dataclass
class ServerConfig:
    """出站连接的运行时配置。env/headers 含密钥，repr 一律隐藏。"""

    id: int | None
    name: str
    transport: str  # stdio | http | sse
    url: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict, repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    timeout_seconds: int = 30
    enabled: bool = True

    def fingerprint(self) -> str:
        raw = json.dumps(
            [self.transport, self.url, self.command, self.args, sorted(self.env.items()),
             sorted(self.headers.items()), self.timeout_seconds],
            ensure_ascii=False, default=str,
        )
        return hashlib.sha256(raw.encode()).hexdigest()


def config_from_row(row: Any, *, env: dict[str, str] | None = None,
                    headers: dict[str, str] | None = None) -> ServerConfig:
    """`McpServer` ORM 行（或同形对象）+ 已从 Vault 解出的 env/headers → ServerConfig。"""
    return ServerConfig(
        id=getattr(row, "id", None),
        name=row.name,
        transport=row.transport,
        url=getattr(row, "url", None),
        command=getattr(row, "command", None),
        args=list(getattr(row, "args_json", None) or []),
        env=dict(env or {}),
        headers=dict(headers or {}),
        timeout_seconds=int(getattr(row, "timeout_seconds", None) or 30),
        enabled=bool(getattr(row, "enabled", True)),
    )


def _not_available(why: str) -> ToolError:
    return ToolError("TOOL_NOT_AVAILABLE", why, user_message=MSG_NOT_AVAILABLE)


def validate_config(cfg: ServerConfig, *, url_allowlist: Iterable[str] | None,
                    command_allowlist: Iterable[str]) -> None:
    if not cfg.enabled:
        raise _not_available("出站连接未启用")
    if cfg.transport == "sse":
        raise ToolError(
            "UPSTREAM_UNAVAILABLE", "不再支持旧版 SSE 传输，请改用 http（Streamable HTTP）",
            user_message=MSG_UNAVAILABLE,
        )
    if cfg.transport == "http":
        parts = urlsplit(cfg.url or "")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise _not_available("出站地址非法（仅允许 http/https）")
        if url_allowlist is not None:
            origin = f"{parts.scheme}://{parts.netloc}".lower()
            host_only = f"{parts.scheme}://{parts.hostname}".lower()
            allowed = {a.rstrip("/").lower() for a in url_allowlist}
            if origin not in allowed and host_only not in allowed:
                raise _not_available("出站地址未命中白名单")
        return
    if cfg.transport == "stdio":
        command = cfg.command or ""
        if not command:
            raise _not_available("缺少命令")
        if not (os.path.isabs(command) or command in set(command_allowlist)):
            raise _not_available("命令须为绝对路径或白名单内二进制")
        return
    raise _not_available(f"未知传输 {cfg.transport!r}")


def default_opener(stdio_cwd: str | None = None) -> Opener:
    """真实 SDK 连接：stdio / Streamable HTTP。懒导入，保证无 server 时零开销。"""

    def open_client(cfg: ServerConfig) -> AbstractAsyncContextManager[Any]:
        from mcp import Client, StdioServerParameters

        if cfg.transport == "stdio":
            server: Any = StdioServerParameters(
                command=cfg.command or "", args=list(cfg.args), env=dict(cfg.env) or None,
                cwd=stdio_cwd or tempfile.gettempdir(),
            )
        else:
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared._httpx_utils import create_mcp_http_client

            server = (
                streamable_http_client(cfg.url or "", http_client=create_mcp_http_client(headers=dict(cfg.headers)))
                if cfg.headers
                else cfg.url
            )
        # legacy：initialize 握手，对齐 2025-11-25；不做 2026 草案探测
        return Client(server, mode="legacy", read_timeout_seconds=float(cfg.timeout_seconds))

    return open_client


class _Entry:
    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint
        self.client: Any = None
        self.error: BaseException | None = None
        self.ready = asyncio.Event()
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.last_used = time.monotonic()
        self.busy = 0

    @property
    def alive(self) -> bool:
        return self.client is not None and self.task is not None and not self.task.done()


class SessionPool:
    def __init__(self, opener: Opener | None = None, *, idle_seconds: float = 300,
                 url_allowlist: Iterable[str] | None = None, command_allowlist: Iterable[str] = (),
                 stdio_cwd: str | None = None, max_concurrency: int = 8):
        self._opener = opener or default_opener(stdio_cwd)
        self._idle = idle_seconds
        self._url_allowlist = list(url_allowlist) if url_allowlist is not None else None
        self._command_allowlist = list(command_allowlist)
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._sem = asyncio.Semaphore(max_concurrency)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._closed = False

    # ---- 同步入口 ----------------------------------------------------

    def ensure(self, cfg: ServerConfig) -> Any:
        """返回该 server 的（复用）会话对象。"""
        validate_config(cfg, url_allowlist=self._url_allowlist, command_allowlist=self._command_allowlist)
        return self._submit(self._aensure(cfg), cfg.timeout_seconds + 5, cfg)

    def run(self, cfg: ServerConfig, fn: Callable[[Any], Awaitable[T]]) -> T:
        """在会话上执行 `fn(client)`；统一超时/并发/错误映射；失败即淘汰会话。"""
        validate_config(cfg, url_allowlist=self._url_allowlist, command_allowlist=self._command_allowlist)
        return self._submit(self._arun(cfg, fn), cfg.timeout_seconds * 2 + 10, cfg)

    def close(self) -> None:
        with self._start_lock:
            loop, thread = self._loop, self._thread
            self._closed = True
            self._loop = self._thread = None
        if loop is None or thread is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._aclose_all(), loop).result(15)
        except Exception:  # noqa: BLE001 — 关闭尽力而为
            log.warning("mcp pool close failed", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)

    # ---- 内部：事件循环线程 ------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._loop is None:
                self._closed = False
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=self._serve, args=(loop,), name="mcp-pool", daemon=True)
                thread.start()
                self._loop, self._thread = loop, thread
            return self._loop

    @staticmethod
    def _serve(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
        loop.close()

    def _submit(self, coro: Awaitable[T], timeout: float, cfg: ServerConfig) -> T:
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
        try:
            return fut.result(timeout)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            raise ToolError("UPSTREAM_TIMEOUT", f"{cfg.name} 调用超时", user_message=MSG_TIMEOUT) from None

    # ---- 内部：协程 --------------------------------------------------

    async def _arun(self, cfg: ServerConfig, fn: Callable[[Any], Awaitable[T]]) -> T:
        async with self._sem:
            client = await self._aensure(cfg)
            entry = self._entries.get(cfg.name)
            if entry is not None:
                entry.busy += 1
            try:
                return await asyncio.wait_for(fn(client), cfg.timeout_seconds)
            except ToolError:
                raise
            except (TimeoutError, asyncio.TimeoutError):
                await self._evict(cfg.name)
                raise ToolError("UPSTREAM_TIMEOUT", f"{cfg.name} 调用超时", user_message=MSG_TIMEOUT) from None
            except Exception as exc:  # noqa: BLE001
                if _is_protocol_error(exc):
                    raise ToolError(
                        "UPSTREAM_BIZ_ERROR", f"{cfg.name} 返回协议错误：{type(exc).__name__}", user_message=MSG_BIZ
                    ) from None
                await self._evict(cfg.name)
                raise ToolError(
                    "UPSTREAM_UNAVAILABLE", f"{cfg.name} 调用失败：{type(exc).__name__}", user_message=MSG_UNAVAILABLE
                ) from None
            finally:
                if entry is not None:
                    entry.busy -= 1
                    entry.last_used = time.monotonic()

    async def _aensure(self, cfg: ServerConfig) -> Any:
        await self._reap_idle(except_name=cfg.name)
        lock = self._locks.setdefault(cfg.name, asyncio.Lock())
        async with lock:
            entry = self._entries.get(cfg.name)
            fp = cfg.fingerprint()
            if entry is not None and entry.alive and entry.fingerprint == fp:
                if self._idle <= 0 and entry.busy == 0:
                    await self._evict(cfg.name)  # 立即回收语义：idle_seconds=0 不复用
                else:
                    entry.last_used = time.monotonic()
                    return entry.client
            elif entry is not None:
                await self._evict(cfg.name)
            entry = _Entry(fp)
            self._entries[cfg.name] = entry
            entry.task = asyncio.create_task(self._hold(entry, cfg), name=f"mcp:{cfg.name}")
            try:
                await asyncio.wait_for(entry.ready.wait(), cfg.timeout_seconds)
            except (TimeoutError, asyncio.TimeoutError):
                await self._evict(cfg.name)
                raise ToolError("UPSTREAM_TIMEOUT", f"{cfg.name} 连接超时", user_message=MSG_TIMEOUT) from None
            if entry.error is not None or entry.client is None:
                err = entry.error
                await self._evict(cfg.name)
                raise ToolError(
                    "UPSTREAM_UNAVAILABLE",
                    f"{cfg.name} 连接失败：{type(err).__name__ if err else 'unknown'}",
                    user_message=MSG_UNAVAILABLE,
                ) from None
            return entry.client

    async def _hold(self, entry: _Entry, cfg: ServerConfig) -> None:
        """常驻 task：进入 → 就绪 → 等待停止 → 退出（同一 task 内完成 anyio 上下文）。"""
        try:
            async with self._opener(cfg) as client:
                entry.client = client
                entry.ready.set()
                await entry.stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001
            entry.error = exc
        finally:
            entry.client = None
            entry.ready.set()

    async def _evict(self, name: str) -> None:
        entry = self._entries.pop(name, None)
        if entry is None or entry.task is None:
            return
        entry.stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(entry.task), 10)
        except (TimeoutError, asyncio.TimeoutError):
            entry.task.cancel()
            try:
                await entry.task
            except BaseException:  # noqa: BLE001
                pass
        except BaseException:  # noqa: BLE001
            pass

    async def _reap_idle(self, *, except_name: str) -> None:
        now = time.monotonic()
        stale = [n for n, e in self._entries.items()
                 if n != except_name and e.busy == 0 and now - e.last_used >= self._idle]
        for name in stale:
            await self._evict(name)

    async def _aclose_all(self) -> None:
        for name in list(self._entries):
            await self._evict(name)


def _is_protocol_error(exc: BaseException) -> bool:
    try:
        from mcp.shared.exceptions import MCPError
    except Exception:  # noqa: BLE001
        return False
    return isinstance(exc, MCPError)
