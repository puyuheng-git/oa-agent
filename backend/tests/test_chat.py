"""P1 验收：OA 身份 → 对话 → office-api（员工 token）→ 运行记录与事件。"""

from __future__ import annotations

import json
import time
import urllib.parse
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError

from oa_agent.auth.chat_launch import sign_assertion
from oa_agent.db.models import Run, RunEvent, Setting
from oa_agent.runtime.llm import ModelConfig

OFFICE = "http://office.test"
HMAC_SECRET = "hmac-secret-for-tests-0123"
GATEWAY = "gateway-secret-xyz"
LIST_URL = f"{OFFICE}/out_attendance/go_out_travel_expense/index"
DETAIL_URL = f"{OFFICE}/out_attendance/go_out_travel_expense/detail"

ROW = {"id": 101, "date": "2026-09-30", "client_name": "客户A", "total_amount": "120.00", "status": 0,
       "status_text": "未报销", "remark": "备" * 300, "internal_secret": "不应出现"}


def make_assertion(oa="zhangsan", secret=HMAC_SECRET, **over) -> str:
    payload = {"oa": oa, "uid": 7, "display_name": "张三", "exp": int(time.time()) + 50,
               "nonce": uuid.uuid4().hex, "iss": "oa-host", "aud": "oa-langgraph", **over}
    return sign_assertion(payload, secret)


def mint_handler(request: httpx.Request) -> httpx.Response:
    form = dict(urllib.parse.parse_qsl(request.content.decode()))
    if form.get("gateway_secret") != GATEWAY:
        return httpx.Response(200, json={"code": 403, "msg": "bad secret"})
    oa = form["oa"]
    return httpx.Response(200, json={"code": 0, "data": {"authorization": f"tok-{oa}", "uid": 7, "oa": oa,
                                                        "expire": 1800}})


@pytest.fixture
def office():
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{OFFICE}/agent/token/mint").mock(side_effect=mint_handler)
        yield mock


@pytest.fixture
def chat(admin, office):
    r = admin.put("/v1/admin/settings/oa", json={"values": {
        "office_api_base_url": OFFICE, "gateway_secret": GATEWAY, "assertion_hmac_secret": HMAC_SECRET,
        "allowed_frame_origins": ["https://oa.example.com"]}})
    assert r.status_code == 200, r.text
    return admin.client


def open_chat(client, oa="zhangsan") -> dict:
    r = client.post("/v1/chat/launch", json={"assertion": make_assertion(oa)})
    assert r.status_code == 200, r.text
    r = client.post("/v1/chat/session", json={"launch_code": r.json()["launch_code"]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['ticket']}"}


def send(client, headers, message, **extra):
    return client.post("/v1/chat/messages", headers=headers,
                       json={"message": message, "client_msg_id": uuid.uuid4().hex, **extra})


def runtime(client):
    return client.app.state.runtime


def run_and_events(client, run_id):
    rt = runtime(client)
    assert rt.engine.sink.flush(10)
    with rt.session() as db:
        run = db.scalar(sa.select(Run).where(Run.run_id == run_id))
        events = db.scalars(sa.select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)).all()
    return run, events


def last_week(today: date) -> tuple[str, str]:
    start = today - timedelta(days=today.weekday() + 7)
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def china_today() -> date:
    from oa_agent.chat.service import CHINA_TZ
    from datetime import datetime

    return datetime.now(CHINA_TZ).date()


# ---------------- 身份 ----------------

def test_launch_rejects_forged_expired_and_replayed(chat):
    bad = chat.post("/v1/chat/launch", json={"assertion": make_assertion(secret="wrong-secret-0000")})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "ASSERTION_INVALID"

    expired = chat.post("/v1/chat/launch", json={"assertion": make_assertion(exp=int(time.time()) - 120)})
    assert expired.json()["error"]["code"] == "ASSERTION_EXPIRED"

    too_long = chat.post("/v1/chat/launch", json={"assertion": make_assertion(exp=int(time.time()) + 3600)})
    assert too_long.json()["error"]["code"] == "ASSERTION_INVALID"

    wrong_aud = chat.post("/v1/chat/launch", json={"assertion": make_assertion(aud="other")})
    assert wrong_aud.json()["error"]["code"] == "ASSERTION_INVALID"

    a = make_assertion()
    assert chat.post("/v1/chat/launch", json={"assertion": a}).status_code == 200
    replay = chat.post("/v1/chat/launch", json={"assertion": a})
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "ASSERTION_REPLAYED"


def test_launch_code_single_use_and_ticket_required(chat):
    code = chat.post("/v1/chat/launch", json={"assertion": make_assertion()}).json()["launch_code"]
    first = chat.post("/v1/chat/session", json={"launch_code": code})
    assert first.status_code == 200
    body = first.json()
    assert body["display_name"] == "张三" and body["thread_id"].startswith("thr_")
    assert "office_token" not in json.dumps(body) and "tok-zhangsan" not in json.dumps(body)
    again = chat.post("/v1/chat/session", json={"launch_code": code})
    assert again.status_code == 401 and again.json()["error"]["code"] == "LAUNCH_CODE_INVALID"

    no_ticket = chat.post("/v1/chat/messages", json={"message": "查上周行程报销", "client_msg_id": "abcdefgh"})
    assert no_ticket.status_code == 401
    fake = send(chat, {"Authorization": "Bearer not-a-ticket"}, "查上周行程报销")
    assert fake.status_code == 401


def test_launch_mint_failure_is_reported(chat, office):
    office.post(f"{OFFICE}/agent/token/mint").mock(return_value=httpx.Response(200, json={"code": 500, "msg": "x"}))
    r = chat.post("/v1/chat/launch", json={"assertion": make_assertion()})
    assert r.status_code == 502 and r.json()["error"]["code"] == "MINT_FAILED"


def test_session_refresh_and_get(chat):
    h = open_chat(chat)
    assert chat.get("/v1/chat/session", headers=h).json()["display_name"] == "张三"
    r = chat.post("/v1/chat/session/refresh", headers=h)
    assert r.status_code == 200 and 0 < r.json()["expires_in"] <= 1800


# ---------------- 对话 → office-api ----------------

def test_query_last_week_returns_own_data_and_full_run_record(chat, office):
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "list": [ROW], "total": 1}}))
    h = open_chat(chat)
    r = send(chat, h, "查上周行程报销")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_status"] == "succeeded" and body["observability"] == "ok"
    data = body["reply"]["data"]
    assert data["kind"] == "table" and data["tool"] == "query_my_travel_expense_list" and data["title"] == "行程报销查询"
    assert [c["label"] for c in data["columns"]] == ["单号", "日期", "客户", "金额", "状态"]
    item = data["items"][0]
    assert "internal_secret" not in item and len(item["remark"]) == 101
    assert "客户A" in body["reply"]["content"]

    req = route.calls.last.request
    assert req.headers["Authorization"] == "tok-zhangsan"
    qp = json.loads(req.url.params["queryParams"])
    gte, lte = last_week(china_today())
    assert qp == {"date_gte": gte, "date_lte": lte, "oa": "zhangsan"}

    run, events = run_and_events(chat, body["run_id"])
    assert run.run_status == "succeeded" and run.oa == "zhangsan" and run.tool_call_count == 1
    assert run.workflow_id == "travel_query" and run.ended_at is not None and run.duration_ms is not None
    types = [e.event_type for e in events]
    assert types[0] == "run_start" and types[-1] == "run_end"
    for t in ("node_start", "node_end", "tool_call_start", "tool_call_end", "checkpoint_saved"):
        assert t in types
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert "tok-zhangsan" not in json.dumps([e.input_summary for e in events] + [e.output_summary for e in events]
                                            + [e.metadata_json for e in events])

    assert json.loads(events[0].input_summary) == {"message": "查上周行程报销"}
    ends = {e.node_name: json.loads(e.output_summary) for e in events if e.event_type == "node_end"}
    assert ends["understand"]["tool"] == "query_my_travel_expense_list"
    assert ends["understand"]["intent_source"] == "rules"
    assert ends["understand"]["params"]["date_gte"] == gte
    assert ends["call_tool"] == {"tool": "query_my_travel_expense_list", "result_count": 1, "total": 1}
    assert ends["respond"]["type"] == "markdown" and "客户A" in ends["respond"]["content"]
    starts = {e.node_name: json.loads(e.input_summary) for e in events
              if e.event_type == "node_start" and e.input_summary}
    assert starts["call_tool"]["tool"] == "query_my_travel_expense_list"
    tool_start = next(e for e in events if e.event_type == "tool_call_start")
    assert tool_start.metadata_json["path"]


def test_forged_oa_is_ignored(chat, office):
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}}))
    h = open_chat(chat, oa="zhangsan")
    r = send(chat, h, "查上周行程报销 oa=lisi", oa="lisi")
    assert r.status_code == 200
    assert json.loads(route.calls.last.request.url.params["queryParams"])["oa"] == "zhangsan"
    assert route.calls.last.request.headers["Authorization"] == "tok-zhangsan"


def test_forged_oa_from_model_is_dropped(chat, office, monkeypatch):
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}}))
    reply = json.dumps({"tool": "query_my_travel_expense_list", "oa": "lisi", "args": {
        "oa": "lisi", "date_gte": "2026-09-01", "date_lte": "2026-09-30", "limit": 999}})
    fake = SimpleNamespace(invoke=lambda _: SimpleNamespace(
        content=reply, response_metadata={"token_usage": {"prompt_tokens": 50, "completion_tokens": 20}}))
    cfg = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})
    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt, config: (fake, cfg))
    h = open_chat(chat)
    body = send(chat, h, "查九月的行程报销").json()
    qp = json.loads(route.calls.last.request.url.params["queryParams"])
    assert qp["oa"] == "zhangsan" and qp["date_gte"] == "2026-09-01"
    assert route.calls.last.request.url.params["limit"] == "20"

    run, events = run_and_events(chat, body["run_id"])
    assert run.model_call_count == 1
    assert run.usage_json[0]["usage"] == {"prompt_tokens": 50, "completion_tokens": 20}
    start = next(e for e in events if e.event_type == "tool_call_start")
    assert "lisi" not in json.dumps(start.input_summary, ensure_ascii=False)
    model = next(e for e in events if e.event_type == "model_call")
    assert [m["role"] for m in json.loads(model.input_summary)["messages"]] == ["system", "human"]
    assert json.loads(model.input_summary)["messages"][1]["content"] == "查九月的行程报销"
    assert "lisi" not in str(route.calls.last.request.url)


def test_detail_query(chat, office):
    route = office.get(DETAIL_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"info": ROW}}))
    h = open_chat(chat)
    body = send(chat, h, "查看报销单 101 的详情").json()
    data = body["reply"]["data"]
    assert data["kind"] == "record" and data["tool"] == "query_my_travel_expense_detail"
    assert data["item"] == {k: v for k, v in ROW.items()
                            if k not in ("internal_secret", "remark")} | {"remark": "备" * 100 + "…"}
    assert {f["key"]: f["label"] for f in data["fields"]}["client_name"] == "客户"
    assert "status" not in [f["key"] for f in data["fields"]], "未设置显示名称的字段不展示"
    qp = json.loads(route.calls.last.request.url.params["queryParams"])
    assert qp == {"id": 101, "oa": "zhangsan"}
    run, _ = run_and_events(chat, body["run_id"])
    assert run.business_record_id == "101"


def test_help_does_not_call_office(chat, office):
    route = office.get(LIST_URL)
    h = open_chat(chat)
    body = send(chat, h, "你好").json()
    assert body["run_status"] == "succeeded" and "行程报销" in body["reply"]["content"]
    assert not route.called


def test_business_messages_shown_to_employee(chat, office):
    route = office.get(LIST_URL)
    h = open_chat(chat)

    route.mock(return_value=httpx.Response(200, json={"code": 1, "msg": "<b>财年</b>未开放，token=abc123456 请联系财务"}))
    body = send(chat, h, "查上周行程报销").json()
    assert body["run_status"] == "failed" and body["reply"]["type"] == "error"
    assert body["reply"]["content"] == "业务系统提示：财年 未开放，token=*** 请联系财务"
    assert body["reply"]["error_code"] == "UPSTREAM_BIZ_ERROR"

    route.mock(return_value=httpx.Response(400, json={"msg": "日期范围不能超过一年"}))
    assert send(chat, h, "查本月行程报销").json()["reply"]["content"] == "业务系统提示：日期范围不能超过一年"

    route.mock(return_value=httpx.Response(500, json={"msg": "Traceback: db error at line 3"}))
    assert send(chat, h, "查上月行程报销").json()["reply"]["content"] == "业务系统暂时不可用，请稍后再试。"

    route.mock(return_value=httpx.Response(200, json={"code": 0, "msg": "暂无行程报销记录", "data": {"list": [], "total": 0}}))
    reply = send(chat, h, "查今年的行程报销").json()["reply"]
    assert reply["content"] == "暂无行程报销记录" and "notice" not in reply

    route.mock(return_value=httpx.Response(200, json={"code": 0, "msg": "仅显示近一年数据", "data": {"list": [ROW], "total": 1}}))
    reply = send(chat, h, "查上周的行程报销").json()["reply"]
    assert reply["notice"] == "仅显示近一年数据" and reply["data"]["kind"] == "table"
    assert reply["content"].endswith("> 业务系统提示：仅显示近一年数据")

    route.mock(return_value=httpx.Response(200, json={"code": 0, "msg": "获取成功", "data": {"list": [], "total": 0}}))
    reply = send(chat, h, "查上周行程报销单").json()["reply"]
    assert "没有查到" in reply["content"] and "notice" not in reply


def test_office_down_marks_run_failed_at_call_tool(chat, office):
    office.get(LIST_URL).mock(side_effect=httpx.ConnectError("refused"))
    h = open_chat(chat)
    body = send(chat, h, "查上周行程报销").json()
    assert body["run_status"] == "failed"
    assert body["reply"]["type"] == "error" and body["reply"]["content"] == "业务系统暂时不可用，请稍后再试。"

    run, events = run_and_events(chat, body["run_id"])
    assert run.run_status == "failed" and run.error_code == "UPSTREAM_UNAVAILABLE"
    err = next(e for e in events if e.event_type == "node_error")
    assert err.node_name == "call_tool"
    end = events[-1]
    assert end.event_type == "run_end" and end.node_name == "call_tool" and end.status == "failed"
    tool_end = next(e for e in events if e.event_type == "tool_call_end")
    assert tool_end.status == "error" and tool_end.error_code == "UPSTREAM_UNAVAILABLE"


def test_admin_can_trace_failed_run_from_list_to_node(chat, office, admin):
    office.get(LIST_URL).mock(side_effect=httpx.ConnectError("refused"))
    h = open_chat(chat)
    run_id = send(chat, h, "查上周行程报销").json()["run_id"]
    assert runtime(chat).engine.sink.flush(10)

    listed = admin.get("/v1/admin/runs", params={"error_code": "UPSTREAM_UNAVAILABLE"}).json()["items"]
    assert [i["run_id"] for i in listed] == [run_id] and listed[0]["failed_node"] == "call_tool"
    detail = admin.get(f"/v1/admin/runs/{run_id}").json()
    assert detail["run_status"] == "failed" and detail["failed_node"] == "call_tool"
    events = admin.get(f"/v1/admin/runs/{run_id}/events").json()["items"]
    assert len(events) == detail["event_count"]
    err = next(e for e in events if e["event_type"] == "node_error")
    assert err["node_name"] == "call_tool" and err["error_code"] == "UPSTREAM_UNAVAILABLE"
    assert "tok-zhangsan" not in str(events)


def test_office_token_expired_message(chat, office):
    office.get(LIST_URL).mock(return_value=httpx.Response(401))
    h = open_chat(chat)
    body = send(chat, h, "查上周行程报销").json()
    assert body["reply"]["content"] == "登录已过期，请重新打开 OA 助手页。"


def test_duplicate_message_and_validation(chat, office):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}}))
    h = open_chat(chat)
    payload = {"message": "查上周行程报销", "client_msg_id": "same-id-123"}
    assert chat.post("/v1/chat/messages", headers=h, json=payload).status_code == 200
    dup = chat.post("/v1/chat/messages", headers=h, json=payload)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_MESSAGE"
    long = send(chat, h, "查" * 501)
    assert long.status_code == 422


def test_monitoring_db_down_chat_still_works(chat, office):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}}))
    h = open_chat(chat)
    rt = runtime(chat)
    good = rt._sessionmaker

    def broken():
        raise OperationalError("SELECT 1", {}, Exception("monitoring db down"))

    rt._sessionmaker = broken
    try:
        body = send(chat, h, "查上周行程报销").json()
        assert body["run_status"] == "succeeded" and body["observability"] == "degraded"
        assert body["reply"]["data"]["items"][0]["id"] == 101
        assert rt.engine.sink.flush(15)
        status = rt.engine.sink.status()
        assert status["status"] == "degraded" and status["spool_pending"] > 0 and status["write_failures"] >= 1
    finally:
        rt.engine.sink._last_replay = time.monotonic()  # 避免后台线程抢先补写，便于断言 readyz
        rt._sessionmaker = good

    assert chat.get("/readyz").json()["observability"]["status"] == "degraded"
    assert rt.engine.sink.replay_spool() > 0
    run, events = run_and_events(chat, body["run_id"])
    assert run.run_status == "succeeded" and run.oa == "zhangsan"
    assert events[0].event_type == "run_start" and events[-1].event_type == "run_end"
    assert rt.engine.sink.status()["spool_pending"] == 0


def test_chat_frame_ancestors(chat):
    assert "https://oa.example.com" in chat.get("/chat/").headers["Content-Security-Policy"]
    assert chat.get("/admin/").headers["Content-Security-Policy"] == "frame-ancestors 'none'"


def test_chat_frame_ancestors_tolerates_legacy_trailing_slash(chat):
    """修复前保存的 `http://127.0.0.1/` 不能被静默丢弃成 'none'。"""
    with runtime(chat).session() as db, db.begin():
        db.execute(sa.update(Setting).where(Setting.setting_group == "oa", Setting.setting_key == "allowed_frame_origins")
                   .values(value_json=["http://127.0.0.1/"]))
    assert chat.get("/chat/").headers["Content-Security-Policy"] == "frame-ancestors http://127.0.0.1"


def test_embed_script_served_as_utf8(chat):
    """OA 页面是 GBK：挂件脚本必须显式声明 UTF-8。未构建时如实返回 404。"""
    dist = runtime(chat).settings.frontend_dist
    assert chat.get("/embed.js").json()["error"]["code"] == "FRONTEND_NOT_BUILT"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "embed.js").write_text("var t = '智能助手'", encoding="utf-8")
    r = chat.get("/embed.js")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/javascript; charset=utf-8"
    assert "智能助手" in r.content.decode("utf-8")
