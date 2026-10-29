"""Identity Provider 适配器（OA、企微、demo 等）。"""

from oa_agent.identity.adapters.demo import DemoIdP
from oa_agent.identity.adapters.oa_assertion import OaAssertionIdP
from oa_agent.identity.adapters.oidc import OidcIdP
from oa_agent.identity.adapters.wecom import WeComIdP

__all__ = ["DemoIdP", "OaAssertionIdP", "OidcIdP", "WeComIdP"]
