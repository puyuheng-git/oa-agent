# backend/tests/test_model_payload.py
import json
from oa_agent.runtime.model_payload import build_model_payload, is_sensitive_field_name, scrub_value


def test_sensitive_field_names():
    assert is_sensitive_field_name("id_card")
    assert is_sensitive_field_name("员工身份证")
    assert is_sensitive_field_name("bank_card_no")
    assert is_sensitive_field_name("mobile")
    assert is_sensitive_field_name("salary")
    assert is_sensitive_field_name("工资")
    assert not is_sensitive_field_name("amount")
    assert not is_sensitive_field_name("reason")
    assert not is_sensitive_field_name("department")


def test_scrub_value_field_and_pattern():
    assert scrub_value("id_card", "110101199001011234") == "[已脱敏]"
    assert scrub_value("amount", 1200) == 1200
    assert "[身份证]" in str(scrub_value("note", "证件 110101199001011234 完毕")) or "[已脱敏]" in str(
        scrub_value("note", "证件 110101199001011234 完毕")
    )


def test_list_payload_prefers_columns_and_caps_rows():
    rows = [{"id": i, "amount": i * 10, "id_card": "110101199001011234", "reason": f"r{i}"} for i in range(1, 30)]
    text = build_model_payload(
        tool="t.list",
        kind="list",
        data={"list": rows, "total": 29},
        columns=["id", "amount", "id_card", "reason"],
        max_rows=20,
        max_chars=6000,
    )
    payload = json.loads(text)
    assert payload["kind"] in ("list", "table")
    assert payload["total"] == 29
    assert payload["shown"] == 20
    assert len(payload["items"]) == 20
    assert payload["items"][0]["amount"] == 10
    assert payload["items"][0]["id_card"] == "[已脱敏]"
    assert "id_card" not in payload["items"][0] or payload["items"][0]["id_card"] == "[已脱敏]"
    assert set(payload["columns"]) == {"id", "amount", "id_card", "reason"}


def test_record_payload_all_columns():
    text = build_model_payload(
        tool="t.one",
        kind="record",
        data={"item": {"id": "9", "amount": 50, "mobile": "13800138000"}},
        columns=["id", "amount", "mobile"],
        max_rows=20,
        max_chars=6000,
    )
    payload = json.loads(text)
    assert payload["kind"] == "record"
    assert payload["item"]["amount"] == 50
    assert payload["item"]["mobile"] == "[已脱敏]"


def test_text_payload_redacts_and_fences():
    from oa_agent.security.prompt_guard import wrap_untrusted, FENCE_OPEN

    raw = wrap_untrusted("电话 13912345678 可联系", source="builtin", name="sys.time")
    text = build_model_payload(
        tool="builtin.time",
        kind="text",
        data={"text": raw},
        max_chars=6000,
    )
    assert FENCE_OPEN in text or "UNTRUSTED_DATA" in text
    assert "13912345678" not in text
    assert "builtin.time" in text


def test_empty_list_is_not_replaced_by_items():
    text = build_model_payload(
        tool="t.list",
        kind="list",
        data={"list": [], "items": [{"id": 1, "amount": 10}], "total": 0},
        columns=["id", "amount"],
        max_chars=6000,
    )
    payload = json.loads(text)
    assert payload["items"] == []
    assert payload["shown"] == 0
    assert payload["total"] == 0


def test_long_text_stays_valid_json_within_max_chars():
    phone = "13912345678"
    raw = "电话 " + phone + " " + ("正文" * 2000)
    text = build_model_payload(
        tool="builtin.time",
        kind="text",
        data={"text": raw},
        max_chars=400,
    )
    payload = json.loads(text)
    assert len(text) <= 400
    assert "<<<UNTRUSTED_DATA" in text
    assert "<<<END_UNTRUSTED_DATA>>>" in text
    assert phone not in text
    assert "[手机号]" in payload["text"]
