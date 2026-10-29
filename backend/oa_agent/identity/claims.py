"""IdP 校验后的主体声明（PrincipalClaims）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrincipalClaims:
    """Identity Provider 校验入站凭证后产出的平台主体声明。"""

    principal_id: str
    display_name: str = ""
    external_keys: dict[str, str] | None = None
    channel: str = ""
    raw: dict | None = None

    def __post_init__(self) -> None:
        if self.external_keys is None:
            object.__setattr__(self, "external_keys", {})
