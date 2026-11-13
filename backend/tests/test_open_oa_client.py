"""open-oa 客户端：POST invoke 与默认上游标识。"""

from __future__ import annotations

import httpx

from oa_agent.integrations.open_oa import DEFAULT_UPSTREAM, INVOKE_PATH, OpenOaClient


def test_default_upstream_is_open_oa():
    assert DEFAULT_UPSTREAM == "open_oa"


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
