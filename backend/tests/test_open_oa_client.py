"""open-oa 客户端：POST invoke 与默认上游标识。"""

from __future__ import annotations

import httpx
import pytest

from oa_agent.integrations.open_oa import (
    DEFAULT_UPSTREAM, INVOKE_PATH, OpenOaClient, OpenOaError, _extract_html_error,
)


def test_default_upstream_is_open_oa():
    assert DEFAULT_UPSTREAM == "open_oa"


def test_extract_html_error_from_thinkphp_page():
    html = (
        "<html><head><title>500 页面错误</title></head><body>"
        "think\\db\\exception\\PDOException: SQLSTATE[23000]: "
        "Column 'id' in where clause is ambiguous"
        "</body></html>"
    )
    out = _extract_html_error(html)
    assert "SQLSTATE[23000]" in out
    assert "ambiguous" in out


def test_unwrap_html_200_surfaces_extracted_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            "<html><head><title>500 页面错误</title></head><body>"
            "PDOException: SQLSTATE[23000]: Column 'id' in where clause is ambiguous"
            "</body></html>"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/html; charset=utf-8"})

    transport = httpx.MockTransport(handler)
    client = OpenOaClient("http://open-oa.test", transport=transport)
    with pytest.raises(OpenOaError) as ei:
        client.get("/x", {}, "Bearer t")
    assert "SQLSTATE[23000]" in ei.value.message
    assert "mint_base_url" not in ei.value.message


def test_post_json_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith(INVOKE_PATH)
        assert request.headers.get("authorization") == "Bearer t"
        assert b'"service"' in request.content
        return httpx.Response(200, json={"code": 0, "message": "ok", "data": {"list": [], "total": 0}})

    transport = httpx.MockTransport(handler)
    client = OpenOaClient("http://open-oa.test", transport=transport)
    resp = client.post(INVOKE_PATH, {"service": "a", "method": "b", "args": {}}, "Bearer t")
    assert resp.data == {"list": [], "total": 0}
    assert resp.http_status == 200
