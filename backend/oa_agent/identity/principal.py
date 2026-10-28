"""平台对话主体（Principal）数据模型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """平台认定的对话主体；现网 principal_id 通常与 oa 相同。"""

    principal_id: str
    display_name: str = ""
    external_keys: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.external_keys is None:
            object.__setattr__(self, "external_keys", {})
