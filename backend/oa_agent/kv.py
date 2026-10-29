"""会话/限流/幂等用的 KV。

Redis 连接在管理后台配置；安装后到配置 Redis 之前，用进程内存储兜底（单实例约束，设计 §15）。
切换到 Redis 时把内存中未过期的键迁移过去，已登录会话不丢失。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Protocol

import redis

from oa_agent.observability.redact import redact
from oa_agent.settings import AppSettings

log = logging.getLogger(__name__)


class ProductionKVError(RuntimeError):
    """生产环境未使用 Redis KV。"""


def assert_production_kv(kv: KV, settings: AppSettings | None = None) -> None:
    """require_redis 为真时，当前后端不得为 memory。"""
    require = settings.require_redis if settings is not None else AppSettings().require_redis
    if not require:
        return
    backend = getattr(kv, "backend", None)
    if backend == "memory":
        raise ProductionKVError(
            "OA_AGENT_REQUIRE_REDIS 已启用，但当前 KV 仍为进程内 MemoryKV；请在管理后台配置 Redis"
        )


class KV(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl: int) -> None: ...
    def set_nx(self, key: str, value: str, ttl: int) -> bool: ...
    def delete(self, key: str) -> None: ...
    def incr(self, key: str, ttl: int) -> int: ...
    def pop(self, key: str) -> str | None: ...
    def ttl(self, key: str) -> int: ...


class MemoryKV:
    backend = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def _alive(self, key: str) -> tuple[str, float] | None:
        item = self._data.get(key)
        if item and item[1] <= time.monotonic():
            self._data.pop(key, None)
            return None
        return item

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._alive(key)
            return item[0] if item else None

    def set(self, key: str, value: str, ttl: int) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + ttl)

    def set_nx(self, key: str, value: str, ttl: int) -> bool:
        with self._lock:
            if self._alive(key):
                return False
            self._data[key] = (value, time.monotonic() + ttl)
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def incr(self, key: str, ttl: int) -> int:
        with self._lock:
            item = self._alive(key)
            if item:
                n = int(item[0]) + 1
                self._data[key] = (str(n), item[1])
            else:
                n = 1
                self._data[key] = ("1", time.monotonic() + ttl)
            return n

    def pop(self, key: str) -> str | None:
        with self._lock:
            item = self._alive(key)
            self._data.pop(key, None)
            return item[0] if item else None

    def ttl(self, key: str) -> int:
        with self._lock:
            item = self._alive(key)
            return max(0, int(item[1] - time.monotonic())) if item else 0

    def export(self) -> list[tuple[str, str, int]]:
        now = time.monotonic()
        with self._lock:
            return [(k, v, max(1, int(exp - now))) for k, (v, exp) in self._data.items() if exp > now]


class RedisKV:
    backend = "redis"

    def __init__(self, client: redis.Redis):
        self.client = client

    def get(self, key: str) -> str | None:
        return self.client.get(key)

    def set(self, key: str, value: str, ttl: int) -> None:
        self.client.set(key, value, ex=ttl)

    def set_nx(self, key: str, value: str, ttl: int) -> bool:
        return bool(self.client.set(key, value, ex=ttl, nx=True))

    def delete(self, key: str) -> None:
        self.client.delete(key)

    def incr(self, key: str, ttl: int) -> int:
        pipe = self.client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl, nx=True)
        n, _ = pipe.execute()
        return int(n)

    def pop(self, key: str) -> str | None:
        return self.client.getdel(key)

    def ttl(self, key: str) -> int:
        return max(0, int(self.client.ttl(key)))


def redis_client(url: str, db: int = 0, password: str | None = None, timeout: float = 3.0) -> redis.Redis:
    return redis.Redis.from_url(
        url,
        db=db,
        password=password or None,
        decode_responses=True,
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
    )


def check_redis(url: str, db: int = 0, password: str | None = None) -> dict:
    started = time.perf_counter()
    try:
        client = redis_client(url, db, password)
        client.ping()
        latency = int((time.perf_counter() - started) * 1000)
        try:
            version = client.info("server").get("redis_version")
        except redis.ResponseError:  # INFO 可能被 rename-command 禁用
            version = None
        client.close()
        return {"ok": True, "latency_ms": latency, "server_version": version}
    except Exception as exc:  # noqa: BLE001 —— 测试连接需如实返回任意失败原因
        return {"ok": False, "error": redact(f"{type(exc).__name__}: {exc}")}


class KVManager:
    """持有当前 KV，支持热切换。status() 只报告真实检测结果。"""

    def __init__(self) -> None:
        self._memory = MemoryKV()
        self._current: KV = self._memory
        self._status: dict = {"status": "未配置", "backend": "memory"}

    @property
    def current(self) -> KV:
        return self._current

    def status(self) -> dict:
        return dict(self._status)

    def use_redis(self, client: redis.Redis) -> None:
        target = RedisKV(client)
        if self._current is self._memory:
            for key, value, ttl in self._memory.export():
                target.set(key, value, ttl)
        self._current = target
        self._status = {"status": "ok", "backend": "redis"}

    def configure(self, cfg: dict | None) -> None:
        """cfg 为 redis 配置组的有效值（含解密后的密码）；None/无 url 表示未配置。"""
        if not cfg or not cfg.get("url"):
            self._current = self._memory
            self._status = {"status": "未配置", "backend": "memory"}
            return
        result = check_redis(cfg["url"], int(cfg.get("db") or 0), cfg.get("password"))
        if not result["ok"]:
            log.warning("Redis 不可用，暂用进程内存储：%s", result["error"])
            self._current = self._memory
            self._status = {"status": "error", "backend": "memory", "error": result["error"]}
            return
        self.use_redis(redis_client(cfg["url"], int(cfg.get("db") or 0), cfg.get("password")))
