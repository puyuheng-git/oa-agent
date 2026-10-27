from oa_agent.executor.contract_test import contract_check, is_activatable


def test_contract_check_passes_with_samples():
    schema = {"method": "GET", "sample_request": {"q": 1}, "sample_response": {"ok": True}}
    result = contract_check(schema)
    assert result.passed and not result.warnings


def test_contract_check_warns_without_samples():
    result = contract_check({"method": "GET"})
    assert not result.passed and result.warnings


def test_is_activatable_get_only():
    assert is_activatable({"method": "GET"})
    assert not is_activatable({"method": "POST"})
