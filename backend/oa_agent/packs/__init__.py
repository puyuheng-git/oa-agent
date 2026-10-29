"""Domain Pack 加载与注册（M3）。"""

from oa_agent.packs.loader import discover_pack_entries, discover_packs, validate_pack_files
from oa_agent.packs.registry import PackRegistry
from oa_agent.packs.rules_load import load_intent_rules
from oa_agent.packs.schema import PackManifest, load_manifest
from oa_agent.packs.state import load_disabled_ids, normalize_disabled_ids, save_disabled_ids

__all__ = [
    "PackManifest",
    "PackRegistry",
    "discover_pack_entries",
    "discover_packs",
    "load_disabled_ids",
    "load_intent_rules",
    "load_manifest",
    "normalize_disabled_ids",
    "save_disabled_ids",
    "validate_pack_files",
]
