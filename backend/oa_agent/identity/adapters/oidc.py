"""OIDC IdP 骨架（M4：接口占位，完整授权码流程未实现）。"""

from __future__ import annotations

from oa_agent.errors import AppError
from oa_agent.identity.claims import PrincipalClaims
from oa_agent.identity.idp import IdPContext


class OidcIdP:
    id = "oidc"

    def verify(self, payload: dict, *, ctx: IdPContext) -> PrincipalClaims:
        raise AppError(501, "IDP_NOT_IMPLEMENTED", "OIDC 适配器尚未实现")
