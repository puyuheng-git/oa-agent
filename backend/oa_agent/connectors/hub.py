"""ConnectorHub：由 upstream_clients 目录装配 HttpJsonConnector。"""

from __future__ import annotations

from oa_agent.connectors.base import Connector
from oa_agent.connectors.http_json import HttpJsonConnector
from oa_agent.integrations.office_api import upstream_clients


class ConnectorHub:
    def __init__(self, connectors: dict[str, Connector]) -> None:
        self._connectors = dict(connectors)

    def get(self, connector_id: str) -> Connector | None:
        return self._connectors.get(connector_id)

    def names(self) -> frozenset[str]:
        return frozenset(self._connectors)

    def __contains__(self, connector_id: str) -> bool:
        return connector_id in self._connectors

    @classmethod
    def from_office_settings(cls, oa_settings: dict) -> ConnectorHub:
        clients = upstream_clients(oa_settings)
        connectors = {key: HttpJsonConnector(key, client) for key, client in clients.items()}
        return cls(connectors)
