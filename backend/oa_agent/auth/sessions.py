"""管理后台会话：KV 存储，绝对时长 + 空闲超时（设计 §6.3；时长来自配置中心「后台安全」组，默认 8 小时 / 30 分钟）。"""

from __future__ import annotations

import json
import secrets
import time

from oa_agent.kv import KVManager

COOKIE_NAME = "oa_admin_sid"
ABSOLUTE_TTL = 8 * 3600
IDLE_TTL = 30 * 60
_PREFIX = "adm:sess:"


class AdminSessionStore:
    def __init__(self, kv: KVManager, absolute_ttl: int = ABSOLUTE_TTL, idle_ttl: int = IDLE_TTL):
        self._kv = kv
        self.absolute_ttl, self.idle_ttl = absolute_ttl, idle_ttl

    @classmethod
    def for_runtime(cls, rt) -> "AdminSessionStore":
        cfg = rt.group_settings("security") if hasattr(rt, "group_settings") else {}
        hours = int(cfg.get("session_absolute_hours") or ABSOLUTE_TTL // 3600)
        minutes = int(cfg.get("session_idle_minutes") or IDLE_TTL // 60)
        return cls(rt.kv, hours * 3600, minutes * 60)

    def create(self, user_id: int) -> tuple[str, str]:
        sid = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        data = {"user_id": user_id, "csrf": csrf, "created_at": time.time()}
        self._kv.current.set(_PREFIX + sid, json.dumps(data), self.idle_ttl)
        return sid, csrf

    def get(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        raw = self._kv.current.get(_PREFIX + sid)
        if raw is None:
            return None
        data = json.loads(raw)
        remaining = self.absolute_ttl - (time.time() - data["created_at"])
        if remaining <= 0:
            self.delete(sid)
            return None
        self._kv.current.set(_PREFIX + sid, raw, int(min(self.idle_ttl, remaining)) or 1)
        return data

    def delete(self, sid: str) -> None:
        self._kv.current.delete(_PREFIX + sid)
