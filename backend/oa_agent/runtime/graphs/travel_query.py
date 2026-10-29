"""Compatibility alias — use oa_agent.runtime.graphs.oa_assistant.

Historical run/release workflow_id=travel_query remains readable; new publishes use oa_assistant.
"""
from __future__ import annotations

from oa_agent.runtime.graphs import oa_assistant as _impl

# Re-export public and private symbols (tests import _text_as_chat etc. from travel_query).
globals().update({name: getattr(_impl, name) for name in dir(_impl) if not name.startswith("__")})

WORKFLOW_ID_ALIAS = "travel_query"
WORKFLOW_ID = _impl.WORKFLOW_ID
LEGACY_WORKFLOW_IDS = frozenset({WORKFLOW_ID_ALIAS, _impl.WORKFLOW_ID})


def resolve_workflow_id(workflow_id: str) -> str:
    if workflow_id == WORKFLOW_ID_ALIAS:
        return _impl.WORKFLOW_ID
    return workflow_id
