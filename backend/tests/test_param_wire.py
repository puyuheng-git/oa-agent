"""参数放置 / 编码与 build_wired_request。"""

from __future__ import annotations

import json

from oa_agent.executor.executor import Identity, build_request, build_wired_request
from oa_agent.executor.param_wire import (
    build_wired_parts,
    encode_flat_value,
    encode_param_value,
    recommend_encoding,
)
from oa_agent.executor.registry import ToolSpec


def _spec(**kwargs) -> ToolSpec:
    base = dict(
        name="t",
        method="GET",
        path="/x",
        version="1#v1",
        schema_hash="x",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=10.0,
        inject_identity_fields=("oa",),
        top_level_fields=(),
        query_params_field="queryParams",
        model_params={},
        result_kind="object",
        result_fields=(),
        identity_bindings=({"param": "oa", "from": "identity.oa"},),
    )
    base.update(kwargs)
    return ToolSpec(**base)


def test_recommend_and_flat_bool():
    assert recommend_encoding({"type": "array", "items": {"type": "integer"}}) == "repeat"
    assert encode_flat_value(True) == "1"
    assert encode_param_value("ok", False, "flat", json_body=False) == {"ok": "0"}


def test_repeat_and_json_body_native():
    assert encode_param_value("ids", [1, 2], "repeat", json_body=False) == {"ids[]": [1, 2]}
    assert encode_param_value("n", 3, "flat", json_body=True) == {"n": 3}


def test_build_wired_parts_get_bag_compat():
    query, body, ct = build_wired_parts(
        {
            "limit": {"type": "integer", "placement": "query"},
            "status": {"type": "integer"},
        },
        {"limit": 10, "status": 1},
        method="GET",
        content_type=None,
        bag_field="queryParams",
        top_level_fields=["limit"],
        identity_pairs=[("oa", "zhangsan")],
        identity_into_bag=True,
    )
    assert body is None and ct is None
    assert query["limit"] == "10"
    assert json.loads(query["queryParams"]) == {"status": 1, "oa": "zhangsan"}


def test_build_request_legacy_bag():
    spec = _spec(
        top_level_fields=("limit",),
        model_params={
            "limit": {"type": "integer"},
            "date_gte": {"type": "string", "format": "date"},
        },
    )
    req = build_request(spec, {"limit": 5, "date_gte": "2026-09-01"}, Identity(oa="zhangsan", authorization="t"))
    assert req["limit"] == "5"
    assert json.loads(req["queryParams"]) == {"date_gte": "2026-09-01", "oa": "zhangsan"}


def test_build_wired_request_post_form_array():
    spec = _spec(
        method="POST",
        content_type="application/x-www-form-urlencoded",
        query_params_field=None,
        inject_identity_fields=(),
        identity_bindings=(),
        top_level_fields=(),
        model_params={
            "ids": {"type": "array", "items": {"type": "integer"}, "placement": "body", "encoding": "auto"},
            "flag": {"type": "boolean", "placement": "body"},
        },
    )
    query, body, ct = build_wired_request(
        spec, {"ids": [1, 2], "flag": True}, Identity(oa="u", authorization="t"),
    )
    assert ct == "application/x-www-form-urlencoded"
    assert query == {}
    assert body["ids[]"] == [1, 2]
    assert body["flag"] == "1"


def test_build_wired_request_post_json():
    spec = _spec(
        method="POST",
        content_type="application/json",
        query_params_field=None,
        inject_identity_fields=(),
        identity_bindings=(),
        model_params={
            "flag": {"type": "boolean", "placement": "body"},
            "n": {"type": "integer", "placement": "body"},
        },
    )
    _q, body, ct = build_wired_request(
        spec, {"flag": True, "n": 3}, Identity(oa="u", authorization="t"),
    )
    assert ct == "application/json"
    assert body == {"flag": True, "n": 3}
