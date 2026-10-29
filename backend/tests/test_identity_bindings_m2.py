"""M2 Task 4：identity_bindings 兼容 inject_identity_fields；模型不得覆盖绑定参数。"""

from __future__ import annotations

import json

from oa_agent.executor.catalog import normalize_operation, synthesize_identity_bindings, to_tool_spec
from oa_agent.executor.executor import Identity, build_request, validate_args
from oa_agent.executor.registry import ToolSpec


def _base_spec(**kwargs) -> ToolSpec:
    defaults = dict(
        name="query_demo",
        method="GET",
        path="/demo",
        version="1",
        schema_hash="h",
        risk_level="low",
        requires_confirmation=False,
        timeout_seconds=10.0,
        inject_identity_fields=(),
        top_level_fields=(),
        query_params_field="queryParams",
        model_params={"limit": {"type": "integer", "default": 10, "maximum": 20}},
        result_kind="list",
        result_fields=("id",),
    )
    defaults.update(kwargs)
    return ToolSpec(**defaults)


def test_synthesize_inject_oa_to_identity_oa_binding():
    assert synthesize_identity_bindings(["oa"]) == [{"param": "oa", "from": "identity.oa"}]


def test_old_inject_identity_fields_build_request_unchanged():
    """旧 inject_identity_fields=[oa] 注入结果与改前一致。"""
    spec = _base_spec(inject_identity_fields=("oa",))
    identity = Identity(oa="zhangsan", authorization="t")
    clean, dropped = validate_args(spec, {"oa": "lisi", "limit": 5})
    assert "oa" not in clean and "oa" in dropped
    req = build_request(spec, clean, identity)
    assert json.loads(req["queryParams"]) == {"limit": 5, "oa": "zhangsan"}


def test_explicit_bindings_inject_principal_id():
    """显式 bindings 把 principal_id 写入目标 param。"""
    spec = _base_spec(
        inject_identity_fields=(),
        identity_bindings=({"param": "user_id", "from": "principal_id"},),
        model_params={"q": {"type": "string", "required": False}},
    )
    identity = Identity(oa="oa1", authorization="t", principal_id="p-99")
    clean, _ = validate_args(spec, {"q": "x"})
    req = build_request(spec, clean, identity)
    assert json.loads(req["queryParams"]) == {"q": "x", "user_id": "p-99"}


def test_model_supplied_bound_param_is_dropped():
    """模型传入绑定目标参数名 → 丢弃，最终仍用服务端身份。"""
    spec = _base_spec(
        identity_bindings=({"param": "user_id", "from": "principal_id"},),
        model_params={"q": {"type": "string", "required": False}},
    )
    identity = Identity(oa="oa1", authorization="t", principal_id="server-pid")
    clean, dropped = validate_args(spec, {"q": "ok", "user_id": "attacker"})
    assert "user_id" not in clean and "user_id" in dropped
    req = build_request(spec, clean, identity)
    assert json.loads(req["queryParams"])["user_id"] == "server-pid"


def test_catalog_synthesizes_bindings_at_runtime_without_hash_field():
    """仅 inject 时规范化 schema 不写 identity_bindings（保哈希）；to_tool_spec 合成。"""
    op = {
        "operationId": "query_bind_demo",
        "summary": "demo",
        "x-agent": {
            "enabled": True,
            "inject_identity_fields": ["oa"],
            "query_params_field": "queryParams",
            "model_params": {"limit": {"type": "integer", "default": 10}},
            "result": {"kind": "list", "fields": ["id"]},
        },
    }
    schema, errors = normalize_operation("/x", "get", op)
    assert not errors
    assert "identity_bindings" not in schema
    assert schema["inject_identity_fields"] == ["oa"]
    spec = to_tool_spec(schema, "1", 1, "abcd" * 8)
    assert spec.identity_bindings == ({"param": "oa", "from": "identity.oa"},)


def test_catalog_stores_explicit_identity_bindings():
    op = {
        "operationId": "query_bind_explicit",
        "summary": "demo",
        "x-agent": {
            "enabled": True,
            "identity_bindings": [{"param": "uid", "from": "principal_id"}],
            "query_params_field": "queryParams",
            "model_params": {"q": {"type": "string"}},
            "result": {"kind": "object", "fields": ["id"]},
        },
    }
    schema, errors = normalize_operation("/y", "get", op)
    assert not errors
    assert schema["identity_bindings"] == [{"param": "uid", "from": "principal_id"}]
    # 绑定参数不得出现在 model_params
    bad = {
        "operationId": "query_bind_leak",
        "summary": "demo",
        "x-agent": {
            "enabled": True,
            "identity_bindings": [{"param": "uid", "from": "principal_id"}],
            "query_params_field": "queryParams",
            "model_params": {"uid": {"type": "string"}},
            "result": {"kind": "object", "fields": ["id"]},
        },
    }
    _, errs = normalize_operation("/z", "get", bad)
    assert any("身份绑定" in e for e in errs)


def test_external_keys_oa_falls_back_to_identity_oa():
    spec = _base_spec(
        identity_bindings=({"param": "oa", "from": "principal.external_keys.oa"},),
    )
    req = build_request(spec, {"limit": 1}, Identity(oa="u42", authorization="t"))
    assert json.loads(req["queryParams"])["oa"] == "u42"
