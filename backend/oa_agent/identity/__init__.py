"""身份与主体抽象（M1 / M4）。"""

from oa_agent.identity.broker import (
    IdentityBroker,
    claims_from_oa_assertion,
    register_default_idps,
)
from oa_agent.identity.claims import PrincipalClaims
from oa_agent.identity.idp import IdP, IdPContext
from oa_agent.identity.principal import Principal

__all__ = [
    "IdP",
    "IdPContext",
    "IdentityBroker",
    "Principal",
    "PrincipalClaims",
    "claims_from_oa_assertion",
    "register_default_idps",
]
