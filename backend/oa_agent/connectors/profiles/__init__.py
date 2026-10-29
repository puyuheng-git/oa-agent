"""可插拔响应信封 profile 实现。"""

from oa_agent.connectors.profiles.oa_office import parse_oa_office
from oa_agent.connectors.profiles.raw_json import parse_raw_json

__all__ = ["parse_oa_office", "parse_raw_json"]
