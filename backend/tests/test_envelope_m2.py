"""M2 EnvelopeProfile — oa_office 与现网 _unwrap 对齐。"""

import pytest

from oa_agent.connectors.base import ConnectorError
from oa_agent.connectors.envelope import get_profile, parse_envelope


DEFAULT_SUCCESS = {"0", "200"}


def test_oa_office_success_takes_data():
    body = {"code": "0", "msg": "操作成功", "data": {"items": [1, 2]}}
    data, hint = parse_envelope(
        "oa_office",
        200,
        body,
        success_codes=DEFAULT_SUCCESS,
        hint_max=200,
    )
    assert data == {"items": [1, 2]}
    assert hint == ""


def test_oa_office_biz_error():
    body = {"code": "1001", "msg": "暂无权限查看该资源"}
    with pytest.raises(ConnectorError) as exc_info:
        parse_envelope(
            "oa_office",
            200,
            body,
            success_codes=DEFAULT_SUCCESS,
            hint_max=200,
        )
    err = exc_info.value
    assert err.code == "UPSTREAM_BIZ_ERROR"
    assert err.http_status == 200
    assert err.user_message == "暂无权限查看该资源"


def test_oa_office_401_maps_office_token_expired():
    with pytest.raises(ConnectorError) as exc_info:
        parse_envelope(
            "oa_office",
            401,
            None,
            success_codes=DEFAULT_SUCCESS,
            hint_max=200,
        )
    err = exc_info.value
    assert err.code == "OFFICE_TOKEN_EXPIRED"
    assert err.http_status == 401


def test_get_profile_oa_office():
    assert get_profile("oa_office") is get_profile("oa_office")


def test_get_profile_unknown():
    with pytest.raises(KeyError, match="未知 envelope profile"):
        get_profile("no_such_profile")


def test_raw_json_success_returns_body_unchanged():
    body = {"items": [1, 2], "total": 2}
    data, hint = parse_envelope(
        "raw_json",
        200,
        body,
        success_codes=DEFAULT_SUCCESS,
        hint_max=200,
    )
    assert data is body
    assert hint == ""


def test_raw_json_success_list():
    body = [{"id": "a"}, {"id": "b"}]
    data, hint = parse_envelope("raw_json", 201, body, success_codes=DEFAULT_SUCCESS, hint_max=200)
    assert data == body
    assert hint == ""


def test_raw_json_success_none_body_as_empty_dict():
    data, hint = parse_envelope(
        "raw_json",
        204,
        None,
        success_codes=DEFAULT_SUCCESS,
        hint_max=200,
    )
    assert data == {}
    assert hint == ""


def test_raw_json_non_json_raises_bad_response():
    with pytest.raises(ConnectorError) as exc_info:
        parse_envelope(
            "raw_json",
            200,
            None,
            success_codes=DEFAULT_SUCCESS,
            hint_max=200,
            json_decode_ok=False,
        )
    err = exc_info.value
    assert err.code == "UPSTREAM_BAD_RESPONSE"
    assert err.http_status == 200


def test_raw_json_401_upstream_http_error():
    with pytest.raises(ConnectorError) as exc_info:
        parse_envelope(
            "raw_json",
            401,
            {"message": "Unauthorized"},
            success_codes=DEFAULT_SUCCESS,
            hint_max=200,
        )
    err = exc_info.value
    assert err.code == "UPSTREAM_HTTP_ERROR"
    assert err.http_status == 401
    assert err.user_message == "Unauthorized"


def test_raw_json_404_user_message_from_body():
    body = {"error": "not_found", "message": "资源不存在"}
    with pytest.raises(ConnectorError) as exc_info:
        parse_envelope(
            "raw_json",
            404,
            body,
            success_codes=DEFAULT_SUCCESS,
            hint_max=200,
        )
    err = exc_info.value
    assert err.code == "UPSTREAM_HTTP_ERROR"
    assert err.http_status == 404
    assert err.user_message == "资源不存在"


def test_raw_json_500_no_user_message_snippet():
    with pytest.raises(ConnectorError) as exc_info:
        parse_envelope(
            "raw_json",
            500,
            {"message": "internal", "stack": "Traceback..."},
            success_codes=DEFAULT_SUCCESS,
            hint_max=200,
        )
    err = exc_info.value
    assert err.code == "UPSTREAM_HTTP_ERROR"
    assert err.http_status == 500
    assert err.user_message == ""


def test_get_profile_raw_json():
    assert get_profile("raw_json") is get_profile("raw_json")
