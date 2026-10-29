"""O6：写路径不注入自报 oa；写规格无身份 query 注入（Agent 侧探针）。"""

from __future__ import annotations

from oa_agent.executor.write_tools import WriteToolExecutor, _as_read_spec, _parse_write_openapi
from oa_agent.runtime import confirmation


def test_write_specs_never_inject_identity_fields():
    specs = _parse_write_openapi()
    assert specs
    for spec in specs.values():
        read = _as_read_spec(spec)
        assert read.inject_identity_fields == ()
        assert read.query_params_field is None
        assert read.method == "POST"


def test_confirmation_payload_hash_order_independent():
    a = confirmation.payload_hash({"draft_id": "1", "x": 2})
    b = confirmation.payload_hash({"x": 2, "draft_id": "1"})
    assert a == b


def test_write_executor_rejects_non_whitelist():
    ex = WriteToolExecutor(clients={})
    assert ex.get("not_a_real_write_tool") is None
