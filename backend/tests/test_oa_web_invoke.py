"""OA Web invoke：确认断言签发与 Tool 表单规范化。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from oa_agent.executor.catalog import normalize_tool_form
from oa_agent.integrations.open_oa import (
    CONFIRM_AUD,
    CONFIRM_ISS,
    OA_WEB_INVOKE_PATH,
    sign_confirm_assertion,
)


def test_sign_confirm_assertion_roundtrip():
    secret = "test-assertion-secret"
    token = sign_confirm_assertion(oa="zhangsan", action="demo_tool", secret=secret, ttl_seconds=60)
    body, sig = token.split(".", 1)
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    assert sig == expected
    pad = "=" * (-len(body) % 4)
    payload = json.loads(base64.urlsafe_b64decode(body + pad))
    assert payload["oa"] == "zhangsan"
    assert payload["action"] == "demo_tool"
    assert payload["iss"] == CONFIRM_ISS
    assert payload["aud"] == CONFIRM_AUD
    assert payload["exp"] > time.time()
    assert len(payload["nonce"]) >= 8


def test_normalize_tool_form_oa_web_read():
    form = {
        "name": "oa_web_echo",
        "summary": "echo stub",
        "method": "GET",
        "upstream": "oa_web",
        "path": "/ignored",
        "invoke_target": "general/ds/agent/invoke_stub_echo_api.php",
        "model_params": {},
        "result": {"kind": "object", "fields": ["oa"], "labels": {}, "list_columns": []},
    }
    spec, errors = normalize_tool_form(form)
    assert errors == []
    assert spec["path"] == OA_WEB_INVOKE_PATH
    assert spec["invoke_target"] == "general/ds/agent/invoke_stub_echo_api.php"
    assert spec["method"] == "GET"
    assert spec["requires_confirmation"] is False


def test_normalize_tool_form_oa_web_write_forces_confirm():
    form = {
        "name": "oa_web_write",
        "summary": "write stub",
        "method": "POST",
        "upstream": "oa_web",
        "invoke_target": "general/ds/xxx/save_api.php",
        "model_params": {},
        "result": {"kind": "object", "fields": ["ok"], "labels": {}, "list_columns": []},
    }
    spec, errors = normalize_tool_form(form)
    assert errors == []
    assert spec["path"] == OA_WEB_INVOKE_PATH
    assert spec["requires_confirmation"] is True
    assert spec["risk_level"] == "high"


def test_normalize_rejects_model_param_named_target():
    form = {
        "name": "bad_tool",
        "summary": "bad",
        "method": "GET",
        "invoke_target": "general/ds/a.php",
        "model_params": {"invoke_target": {"type": "string"}},
        "result": {"kind": "object", "fields": [], "labels": {}, "list_columns": []},
    }
    _, errors = normalize_tool_form(form)
    assert any("invoke_target" in e for e in errors)
