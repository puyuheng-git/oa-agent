"""O1：workflow_id 别名 travel_query → oa_assistant。"""

from oa_agent.runtime.graphs import oa_assistant
from oa_agent.runtime.graphs.travel_query import LEGACY_WORKFLOW_IDS, resolve_workflow_id


def test_resolve_travel_query_alias():
    assert resolve_workflow_id("travel_query") == "oa_assistant"


def test_legacy_contains_both_ids():
    assert "travel_query" in LEGACY_WORKFLOW_IDS
    assert oa_assistant.WORKFLOW_ID in LEGACY_WORKFLOW_IDS
