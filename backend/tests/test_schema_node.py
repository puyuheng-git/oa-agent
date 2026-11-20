from oa_agent.executor.catalog import COMPATIBLE, compare, normalize_open_oa_catalog_item, normalize_operation


def _op(model_params, result=None):
    return {
        "operationId": "demo_tool",
        "summary": "d",
        "x-agent": {
            "enabled": True,
            "risk_level": "low",
            "timeout_seconds": 10,
            "upstream": "open_oa",
            "model_params": model_params,
            "result": result or {"kind": "object", "fields": ["id"], "labels": {"id": "ID"}, "list_columns": []},
        },
    }


def test_nested_object_and_array_items_preserved():
    spec, errors = normalize_operation("/x", "get", _op({
        "payload": {
            "type": "object",
            "label": "体",
            "properties": {
                "user": {"type": "object", "properties": {"name": {"type": "string", "required": True}}},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
    }))
    assert errors == []
    p = spec["model_params"]["payload"]
    assert p["properties"]["user"]["properties"]["name"]["type"] == "string"
    assert p["properties"]["tags"]["items"]["type"] == "string"


def test_file_multiple_normalizes_to_array_of_file():
    spec, errors = normalize_operation("/x", "get", _op({
        "attach": {"type": "file", "multiple": True, "accept": [".pdf"], "label": "附件"},
    }))
    assert errors == []
    a = spec["model_params"]["attach"]
    assert a["type"] == "array"
    assert a["items"]["type"] == "file"
    assert a["items"]["accept"] == [".pdf"]
    assert "multiple" not in a


def test_depth_over_8_errors():
    node = {"type": "object", "properties": {}}
    cur = node
    for i in range(9):
        child = {"type": "object", "properties": {}}
        cur["properties"][f"l{i}"] = child
        cur = child
    spec, errors = normalize_operation("/x", "get", _op({"deep": node}))
    assert any("深度" in e for e in errors)


def test_result_one_level_dotted_field_ok_two_level_rejected():
    spec, errors = normalize_operation("/x", "get", _op(
        {"q": {"type": "string"}},
        {"kind": "object", "fields": ["id", "user.name", "user.dept.title"], "labels": {"user.name": "姓名"},
         "list_columns": [], "schema": {"type": "object", "properties": {"user": {"type": "object"}}}},
    ))
    assert any("user.dept.title" in e for e in errors)
    # 非法两层路径被丢弃，合法一层点号保留
    assert spec["result"]["fields"] == ["id", "user.name"]
    assert spec["result"]["labels"] == {"user.name": "姓名"}
    assert spec["result"]["schema"]["properties"]["user"]["type"] == "object"


def test_compare_result_schema_only_change_is_compatible():
    base_result = {"kind": "object", "fields": ["id"], "labels": {"id": "ID"}, "list_columns": []}
    old_schema = {"type": "object", "properties": {"id": {"type": "string"}}}
    new_schema = {"type": "object", "properties": {"id": {"type": "integer"}, "n": {"type": "string"}}}
    old_spec, errors = normalize_operation("/x", "get", _op({"q": {"type": "string"}}, {**base_result, "schema": old_schema}))
    assert errors == []
    new_spec, errors = normalize_operation("/x", "get", _op({"q": {"type": "string"}}, {**base_result, "schema": new_schema}))
    assert errors == []
    level, diff = compare(old_spec, new_spec)
    assert level == COMPATIBLE
    entries = [d for d in diff if d["field"] == "result.schema"]
    assert len(entries) == 1
    assert entries[0]["change"] == "changed"
    assert entries[0]["breaking"] is False
    assert entries[0]["old"] == old_spec["result"]["schema"]
    assert entries[0]["new"] == new_spec["result"]["schema"]


def test_open_oa_catalog_item_preserves_nested_schema():
    # 向导保存路径：完整 SchemaNode 经 normalize_open_oa_catalog_item 后嵌套不得丢失
    item = {
        "service": "oa/demo", "method": "submit", "tool_name": "demo_submit", "summary": "d", "op": "write",
        "params": [
            {"name": "payload", "type": "object", "label": "体", "required": True, "properties": {
                "user": {"type": "object", "properties": {"name": {"type": "string", "required": True}}},
            }},
            {"name": "ids", "type": "array", "items": {"type": "integer"}},
            {"name": "doc", "type": "file", "accept": [".pdf"]},
            {"name": "attach", "type": "file", "multiple": True, "accept": [".png"]},
        ],
        "returns": {"kind": "object", "fields": ["id"]},
    }
    spec, errors = normalize_open_oa_catalog_item(item)
    assert errors == []
    mp = spec["model_params"]
    assert mp["payload"]["required"] is True
    assert mp["payload"]["properties"]["user"]["properties"]["name"] == {"type": "string", "required": True}
    assert mp["ids"]["type"] == "array" and mp["ids"]["items"]["type"] == "integer"
    assert mp["doc"]["type"] == "file" and mp["doc"]["accept"] == [".pdf"]
    assert mp["attach"]["type"] == "array"
    assert mp["attach"]["items"] == {"type": "file", "accept": [".png"]}
    assert "multiple" not in mp["attach"]
