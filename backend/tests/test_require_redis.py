import pytest

from oa_agent.kv import MemoryKV, ProductionKVError, assert_production_kv
from oa_agent.settings import AppSettings


def test_assert_production_kv_allows_memory_by_default():
    assert_production_kv(MemoryKV(), AppSettings(require_redis=False))


def test_assert_production_kv_rejects_memory_when_required():
    with pytest.raises(ProductionKVError):
        assert_production_kv(MemoryKV(), AppSettings(require_redis=True))
