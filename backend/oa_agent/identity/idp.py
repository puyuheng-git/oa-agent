"""Identity Provider 插件协议与校验上下文。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from oa_agent.identity.claims import PrincipalClaims


@dataclass
class IdPContext:
    """IdP.verify 运行时上下文（配置、密钥、时钟）。"""

    kv: Any | None = None
    secrets: dict[str, str] | Callable[[str], str | None] | None = None
    now: int | None = None


@runtime_checkable
class IdP(Protocol):
    id: str

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims: ...
