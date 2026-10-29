"""上游 Connector 抽象（M1）。"""

from oa_agent.connectors.base import Connector, ConnectorError, ConnectorResult
from oa_agent.connectors.hub import ConnectorHub
from oa_agent.connectors.http_json import HttpJsonConnector

__all__ = ["Connector", "ConnectorError", "ConnectorResult", "ConnectorHub", "HttpJsonConnector"]
