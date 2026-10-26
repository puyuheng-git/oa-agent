"""OA 标签加载（D16 预留）；默认空实现。"""

from __future__ import annotations

from typing import Protocol


class TagProvider(Protocol):
    def load_tags(self, oa: str, office_token: str) -> list[str]: ...


class EmptyTagProvider:
    def load_tags(self, oa: str, office_token: str) -> list[str]:
        return []
