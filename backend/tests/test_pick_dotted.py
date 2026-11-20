import pytest

from oa_agent.executor.executor import ToolError, _pick, validate_args
from oa_agent.executor.registry import ToolSpec


def _spec(model_params: dict) -> ToolSpec:
    return ToolSpec(
        name="t", method="GET", path="/", version="1", schema_hash="x",
        risk_level="low", requires_confirmation=False, timeout_seconds=10.0,
        inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params=model_params,
        result_kind="object", result_fields=("id",),
    )


def test_pick_top_level_and_one_dot():
    row = {"id": 1, "user": {"name": "张三", "dept": {"title": "审计"}}, "items": [{"sku": "A"}]}
    out = _pick(row, ("id", "user.name", "items"))
    assert out == {"id": 1, "user.name": "张三", "items": [{"sku": "A"}]}


def test_pick_missing_dot_skipped():
    assert _pick({"user": "x"}, ("user.name",)) == {}


def test_validate_nested_object_properties():
    spec = _spec({
        "payload": {
            "type": "object",
            "required": True,
            "properties": {"n": {"type": "integer", "required": True}},
        }
    })
    clean, _ = validate_args(spec, {"payload": {"n": "3", "extra": 1}})
    assert clean["payload"]["n"] == 3
    assert clean["payload"]["extra"] == 1  # 未声明键保留


def test_validate_nested_required_missing():
    spec = _spec({
        "payload": {
            "type": "object",
            "properties": {"n": {"type": "integer", "required": True}},
        }
    })
    with pytest.raises(ToolError):
        validate_args(spec, {"payload": {}})


def test_validate_array_items():
    spec = _spec({"ids": {"type": "array", "items": {"type": "integer"}}})
    clean, _ = validate_args(spec, {"ids": ["1", 2]})
    assert clean["ids"] == [1, 2]
    with pytest.raises(ToolError):
        validate_args(spec, {"ids": ["x"]})


def test_check_node_none_is_missing_not_stringified():
    """数组元素 / 嵌套标量为 None 时视为缺失，不能被 str() 成 'None'。"""
    spec = _spec({"tags": {"type": "array", "items": {"type": "string"}}})
    with pytest.raises(ToolError):
        validate_args(spec, {"tags": ["a", None]})
    spec2 = _spec({"o": {"type": "object", "properties": {"n": {"type": "string", "required": True}}}})
    with pytest.raises(ToolError):
        validate_args(spec2, {"o": {"n": None}})
