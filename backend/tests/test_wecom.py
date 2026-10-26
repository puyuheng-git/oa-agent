"""企业微信智能机器人长连接渠道：身份经 OA 解析、单聊、去重、流式回复、订阅/心跳/被替换。"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse

import httpx
import sqlalchemy as sa
from websockets.sync.server import serve

from oa_agent.channels import wecom
from oa_agent.db.models import ChatThread, Run
from tests.conftest import login
from tests.test_chat import GATEWAY, LIST_URL, OFFICE, ROW, chat, office, runtime  # noqa: F401

BOT_ID, SECRET = "aib-test-bot", "ws-secret-123456"


def wework_mint(request: httpx.Request) -> httpx.Response:
    form = dict(urllib.parse.parse_qsl(request.content.decode()))
    assert form.get("gateway_secret") == GATEWAY and "oa" not in form
    bound = {"wx_zhangsan": "zhangsan"}
    oa = bound.get(form.get("wework_user_id", ""))
    if oa is None:
        return httpx.Response(200, json={"code": 1, "msg": "你的企业微信尚未绑定 OA 账号，请联系管理员"})
    return httpx.Response(200, json={"code": 0, "data": {"authorization": f"tok-{oa}", "uid": 7, "oa": oa,
                                                        "display_name": "张三", "expire": 1800}})


def text_msg(msgid: str, content: str, userid="wx_zhangsan", chattype="single") -> dict:
    return {"msgid": msgid, "aibotid": BOT_ID, "chattype": chattype, "from": {"userid": userid},
            "msgtype": "text", "text": {"content": content}}


def collect(rt, body):
    out: list[tuple[str, bool]] = []
    wecom.process_message(rt, body, lambda content, finish: out.append((content, finish)))
    return out


def test_message_flow_identity_from_oa(chat, office):
    office.post(f"{OFFICE}/agent/token/mint").mock(side_effect=wework_mint)
    route = office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {
        "list": [ROW], "total": 1}}))
    rt = runtime(chat)

    out = collect(rt, text_msg("m1", "查上周行程报销"))
    assert out[0] == (wecom.WORKING_TEXT, False)
    content, finish = out[-1]
    assert finish and "共查到 **1** 条" in content and "| 客户A |" in content
    assert route.calls.last.request.headers["Authorization"] == "tok-zhangsan"

    assert rt.engine.sink.flush(10)
    with rt.session() as db:
        run = db.scalar(sa.select(Run).order_by(Run.id.desc()))
    assert run.channel == "wecom" and run.oa == "zhangsan"

    with rt.session() as db:
        thread = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == run.thread_id))
    assert thread is not None and thread.oa == "zhangsan" and thread.created_channel == "wecom"

    assert collect(rt, text_msg("m1", "查上周行程报销")) == []          # 重复推送去重
    collect(rt, text_msg("m2", "查上周行程报销"))                        # 会话复用：不再重复 mint
    mints = [c for c in office.calls if c.request.url.path.endswith("/agent/token/mint")]
    assert len(mints) == 1


def test_group_unbound_and_unsupported(chat, office):
    office.post(f"{OFFICE}/agent/token/mint").mock(side_effect=wework_mint)
    rt = runtime(chat)
    assert collect(rt, text_msg("g1", "查行程", chattype="group")) == [(wecom.GROUP_TEXT, True)]
    assert collect(rt, text_msg("u1", "查行程", userid="wx_nobody")) == [
        ("你的企业微信尚未绑定 OA 账号，请联系管理员", True)]
    image = {"msgid": "i1", "chattype": "single", "from": {"userid": "wx_zhangsan"}, "msgtype": "image",
             "image": {"url": "https://x", "aeskey": "k"}}
    assert collect(rt, image) == [(wecom.UNSUPPORTED_TEXT, True)]
    assert wecom.reply_markdown({"type": "markdown", "content": "表" * 10000}).endswith(wecom.TRUNCATED_SUFFIX)


class FakeWeCom:
    """模拟企业微信长连接服务端。"""

    def __init__(self):
        self.frames: list[dict] = []
        self.subscribes: list[dict] = []
        self.conns = []
        self.server = serve(self._handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self, ws):
        sub = json.loads(ws.recv())
        self.subscribes.append(sub)
        ok = sub["body"] == {"bot_id": BOT_ID, "secret": SECRET}
        ws.send(json.dumps({"headers": sub["headers"], "errcode": 0 if ok else 40058,
                            "errmsg": "ok" if ok else "invalid secret"}))
        if not ok:
            return
        self.conns.append(ws)
        for raw in ws:
            frame = json.loads(raw)
            self.frames.append(frame)
            if frame["cmd"] == "ping":
                ws.send(json.dumps({"headers": frame["headers"], "errcode": 0, "errmsg": "ok"}))

    def push(self, frame: dict):
        self.conns[-1].send(json.dumps(frame))

    def close(self):
        self.server.shutdown()


def wait_for(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_long_connection_end_to_end(chat, office, monkeypatch):
    office.post(f"{OFFICE}/agent/token/mint").mock(side_effect=wework_mint)
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW], "total": 1}}))
    rt = runtime(chat)
    rt.wecom.stop()
    monkeypatch.setattr(wecom, "CONFIG_POLL", 0.2)
    monkeypatch.setattr(wecom.WeComChannel, "_ping_interval", lambda self: 0.5)
    fake = FakeWeCom()
    try:
        admin = login(chat)
        assert admin.put("/v1/admin/settings/wecom", json={"values": {
            "bot_id": BOT_ID, "secret": SECRET, "ws_url": fake.url}}).status_code == 200
        connect_kwargs: list[dict] = []

        def spy_connect(url, **kwargs):
            connect_kwargs.append(kwargs)
            return wecom.ws_connect(url, **kwargs)

        channel = wecom.WeComChannel(rt, connect=spy_connect)
        channel.start()
        try:
            assert wait_for(lambda: channel.status["status"] == "已连接"), channel.status
            assert connect_kwargs[0]["ping_interval"] is None   # 企业微信收到协议层 ping 会断开连接
            assert fake.subscribes[0]["cmd"] == "aibot_subscribe"
            assert SECRET not in json.dumps(admin.get("/v1/admin/settings").json(), ensure_ascii=False)

            fake.push({"cmd": "aibot_msg_callback", "headers": {"req_id": "REQ-1"},
                       "body": text_msg("ws-1", "查上周行程报销")})
            done = lambda: [f for f in fake.frames if f["cmd"] == "aibot_respond_msg"  # noqa: E731
                            and f["body"]["stream"]["finish"]]
            assert wait_for(lambda: done())
            replies = [f for f in fake.frames if f["cmd"] == "aibot_respond_msg"]
            assert all(f["headers"]["req_id"] == "REQ-1" for f in replies)
            assert len({f["body"]["stream"]["id"] for f in replies}) == 1
            assert replies[0]["body"]["stream"] == {"id": replies[0]["body"]["stream"]["id"], "finish": False,
                                                    "content": wecom.WORKING_TEXT}
            assert "客户A" in done()[0]["body"]["stream"]["content"]

            fake.push({"cmd": "aibot_event_callback", "headers": {"req_id": "REQ-2"},
                       "body": {"msgid": "e1", "msgtype": "event", "event": {"eventtype": "enter_chat"},
                                "from": {"userid": "wx_zhangsan"}}})
            assert wait_for(lambda: any(f["cmd"] == "aibot_respond_welcome_msg" for f in fake.frames))
            assert wait_for(lambda: any(f["cmd"] == "ping" for f in fake.frames))

            fake.push({"cmd": "aibot_event_callback", "headers": {"req_id": "REQ-3"},
                       "body": {"msgid": "e2", "msgtype": "event", "event": {"eventtype": "disconnected_event"}}})
            assert wait_for(lambda: channel.status["status"] == "已断开")
            assert "被替换" in channel.status["error"] and SECRET not in json.dumps(channel.status)
        finally:
            channel.stop()
    finally:
        fake.close()


def test_bad_secret_reports_error_without_leaking(chat, monkeypatch):
    rt = runtime(chat)
    rt.wecom.stop()
    fake = FakeWeCom()
    try:
        admin = login(chat)
        assert admin.put("/v1/admin/settings/wecom", json={"values": {
            "bot_id": BOT_ID, "secret": "wrong-secret-999", "ws_url": fake.url}}).status_code == 200
        channel = wecom.WeComChannel(rt)
        channel.start()
        try:
            assert wait_for(lambda: channel.status["status"] == "已断开")
            assert "40058" in channel.status["error"] and "wrong-secret-999" not in json.dumps(channel.status)
        finally:
            channel.stop()
    finally:
        fake.close()
