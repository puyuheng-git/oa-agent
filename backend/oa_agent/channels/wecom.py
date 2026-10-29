"""企业微信智能机器人渠道：长连接（WebSocket）模式（设计 §6.2）。

协议（企业微信开发者中心「智能机器人长连接」）：连接 wss://openws.work.weixin.qq.com → aibot_subscribe(bot_id, secret)
→ 每 30 秒 ping → 收 aibot_msg_callback / aibot_event_callback → 用回调的 req_id 回 aibot_respond_msg（流式，finish=true 结束）。
同一机器人只能有一个有效连接，新连接会踢掉旧连接（旧连接收到 disconnected_event）。

身份：消息里只有企业微信 userid（来自企业微信服务端，可信）。经 WeComIdP（委托 office-api `/agent/token/mint`）
按企微绑定解析 OA 主账号并签发员工 token，员工身份以 OA 返回的 oa 为准（Agent 不做映射、不读 td_oa）。只支持单聊。
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from websockets.sync.client import connect as ws_connect

from oa_agent.auth import chat_launch
from oa_agent.auth.chat_launch import ChatSession
from oa_agent.chat import service
from oa_agent.chat.threads import ensure_thread
from oa_agent.config.schema import default as default_setting
from oa_agent.errors import AppError
from oa_agent.ids import new_request_id, new_thread_id
from oa_agent.identity.adapters.wecom import WeComIdP
from oa_agent.identity.idp import IdPContext
from oa_agent.integrations.office_api import OfficeApiError
from oa_agent.observability.redact import redact

log = logging.getLogger(__name__)

DEFAULT_WS_URL = "wss://openws.work.weixin.qq.com"
CHANNEL = "wecom"
CONFIG_POLL = 10            # 检测配置变更的间隔（内部机制，不开放配置）
SUBSCRIBE_TIMEOUT = 10      # 订阅应答等待（协议握手，不开放配置）
MAX_CONTENT_BYTES = 20000   # 企业微信平台限制：markdown/stream content 上限 20480 字节，留余量

# 以下为配置中心「企业微信」「提示文案」组的默认值；运行时以配置为准
PING_INTERVAL = default_setting("wecom", "ping_interval_seconds")
WORKERS = default_setting("wecom", "workers")
GROUP_TEXT = default_setting("messages", "wecom_group")
UNSUPPORTED_TEXT = default_setting("messages", "wecom_unsupported")
IDENTITY_FAILED_TEXT = default_setting("messages", "wecom_identity_failed")
WORKING_TEXT = default_setting("messages", "wecom_working")
PENDING_SUFFIX = "\n\n" + default_setting("messages", "wecom_pending_suffix")
TRUNCATED_SUFFIX = "\n\n" + default_setting("messages", "wecom_truncated_suffix")


def _int(rt, key: str) -> int:
    return int(service.setting(rt, "wecom", key))


class Kicked(Exception):
    """同一机器人在别处建立了新连接，本连接被替换。"""


class SubscribeFailed(Exception):
    pass


Respond = Callable[[str, bool], None]


# ---- 消息处理（与连接无关，便于测试） ----

def process_message(rt, body: dict, respond: Respond) -> None:
    msgid = str(body.get("msgid") or "")
    if msgid and not rt.kv.current.set_nx(f"wecom:msgid:{msgid}", "1", _int(rt, "message_dedupe_seconds")):
        return  # 企业微信可能重复推送同一条消息
    if body.get("chattype") == "group":
        respond(service.text(rt, "wecom_group"), True)
        return
    text = message_text(body)
    if not text:
        respond(service.text(rt, "wecom_unsupported"), True)
        return
    userid = str((body.get("from") or {}).get("userid") or "")
    if not userid:
        return
    try:
        session, key = wecom_session(rt, userid)
    except (AppError, OfficeApiError) as exc:
        log.warning("企业微信用户身份解析失败：%s %s", getattr(exc, "code", ""), redact(getattr(exc, "message", "")))
        respond(getattr(exc, "user_message", "") or service.text(rt, "wecom_identity_failed"), True)
        return
    respond(service.text(rt, "wecom_working"), False)
    streamer = _Streamer(respond, _int(rt, "stream_flush_ms") / 1000)
    try:
        service.guard_message(rt, session, text, f"wecom:{msgid or uuid.uuid4().hex}")
        reply = service.handle_message(rt, session, text, new_request_id(), session_key=key,
                                       on_delta=streamer.delta)["reply"]
    except AppError as exc:
        reply = {"type": "error", "content": exc.message}
    except Exception:  # noqa: BLE001 —— 已发出「正在查询」，必须结束这条流式消息
        log.exception("企业微信消息处理失败")
        reply = {"type": "error", "content": service.text(rt, "generic_failure")}
    respond(reply_markdown(reply, "\n\n" + service.text(rt, "wecom_pending_suffix"),
                           "\n\n" + service.text(rt, "wecom_truncated_suffix")), True)


class _Streamer:
    """模型逐字输出时按间隔把已生成的内容推给企业微信（同一条流式消息不断覆盖），避免触发频率限制。"""

    def __init__(self, respond: Respond, interval: float):
        self._respond, self._interval = respond, interval
        self._text, self._last = "", 0.0

    def delta(self, piece: str) -> None:
        self._text += piece
        now = time.monotonic()
        if now - self._last >= self._interval and len(self._text.encode("utf-8")) <= MAX_CONTENT_BYTES:
            self._last = now
            self._respond(self._text, False)


def message_text(body: dict) -> str:
    kind = body.get("msgtype")
    if kind == "text":
        return str((body.get("text") or {}).get("content") or "").strip()
    if kind == "voice":
        return str((body.get("voice") or {}).get("content") or "").strip()
    if kind == "mixed":
        items = (body.get("mixed") or {}).get("msg_item") or []
        return " ".join(str((i.get("text") or {}).get("content") or "") for i in items
                        if isinstance(i, dict) and i.get("msgtype") == "text").strip()
    return ""


def reply_markdown(reply: dict, pending_suffix: str = PENDING_SUFFIX, truncated_suffix: str = TRUNCATED_SUFFIX) -> str:
    content = str(reply.get("content") or "")
    if reply.get("type") == "pending":
        content += pending_suffix
    raw = content.encode("utf-8")
    if len(raw) <= MAX_CONTENT_BYTES:
        return content
    limit = MAX_CONTENT_BYTES - len(truncated_suffix.encode("utf-8"))
    return raw[:limit].decode("utf-8", "ignore") + truncated_suffix


def welcome_text(rt, *, oa: str | None = None, office_token: str = "") -> str:
    skills = service.skill_menu(rt, oa=oa, office_token=office_token)
    if not skills:
        return "你好，我是 OA 助手。" + service.text(rt, "no_skill")
    lines = [service.text(rt, "wecom_welcome")]
    for s in skills:
        lines.append(f"· {s['display_name']}" + (f"，例如「{s['examples'][0]}」" if s.get("examples") else ""))
    return "\n".join(lines)


def _user_key(userid: str) -> str:
    return "wecom:user:" + hashlib.sha256(userid.encode()).hexdigest()


def wecom_session(rt, userid: str) -> tuple[ChatSession, str]:
    """企业微信用户的服务端会话：ticket 随机生成、只存在服务端；token 临近过期时按 userid 经 WeComIdP 重新解析并签发。"""
    kv = rt.kv.current
    ticket = kv.get(_user_key(userid))
    session = chat_launch.load_session(kv, ticket) if ticket else None
    policy = service.launch_policy(rt)
    if session is None or session.token_expires_at - int(time.time()) < policy.remint_before:
        gateway_secret = service.load_settings(rt, "oa").get("gateway_secret")
        client = service.office_client(rt)
        claims = WeComIdP(client_factory=lambda: client).verify(
            {"wework_user_id": userid},
            ctx=IdPContext(secrets={"gateway_secret": gateway_secret}),
        )
        raw = claims.raw or {}
        ttl_seconds = int(raw.get("ttl_seconds") or 0)
        if ttl_seconds <= 60:
            raise AppError(502, "MINT_FAILED", "签发的员工令牌有效期过短")
        authorization = str(raw.get("authorization") or "")
        oa = claims.principal_id
        display_name = claims.display_name or oa
        uid_raw = raw.get("uid")
        try:
            uid = int(uid_raw) if uid_raw is not None else None
        except (TypeError, ValueError):
            uid = None
        expires_at = int(time.time()) + ttl_seconds
        if session is None or session.oa != oa:
            ticket = secrets.token_urlsafe(32)
            session = ChatSession(
                oa=oa,
                uid=uid,
                display_name=display_name,
                thread_id=new_thread_id(),
                office_token=authorization,
                token_expires_at=expires_at,
                created_at=int(time.time()),
                channel=CHANNEL,
            )
            with rt.session() as db, db.begin():
                ensure_thread(db, thread_id=session.thread_id, oa=session.oa, channel=CHANNEL)
        else:
            session.office_token, session.token_expires_at = authorization, expires_at
    ttl = chat_launch.store_session(kv, ticket, session, policy)
    kv.set(_user_key(userid), ticket, ttl)
    return session, chat_launch.session_key(ticket)


# ---- 长连接 ----

class WeComChannel:
    def __init__(self, rt, connect=ws_connect):
        self.rt = rt
        self._connect = connect
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self._send_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(self._number("workers", WORKERS), thread_name_prefix="wecom")
        self._status: dict = {"status": "未配置"}

    @property
    def status(self) -> dict:
        return dict(self._status)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="wecom-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _number(self, key: str, fallback: float) -> float:
        try:
            return _int(self.rt, key)
        except Exception:  # noqa: BLE001 —— 配置读不到时用默认值，连接不能停
            return fallback

    def _ping_interval(self) -> float:
        return self._number("ping_interval_seconds", PING_INTERVAL)

    def _set(self, status: str, error: str = "", **extra) -> None:
        self._status = {"status": status, **({"error": error} if error else {}), **extra}

    def _config(self) -> tuple[str, str, str] | None:
        try:
            values = service.load_settings(self.rt, "wecom")
        except Exception:  # noqa: BLE001 —— 配置读不到时按未配置处理，稍后重试
            log.exception("读取企业微信配置失败")
            return None
        bot_id, secret = str(values.get("bot_id") or "").strip(), str(values.get("secret") or "")
        if not bot_id or not secret:
            return None
        return bot_id, secret, str(values.get("ws_url") or DEFAULT_WS_URL).strip()

    def _run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            cfg = self._config()
            if cfg is None:
                self._set("未配置")
                self._stop.wait(CONFIG_POLL)
                continue
            try:
                self._session(cfg)
                backoff = 1
            except Kicked:
                wait = self._number("kicked_backoff_seconds", 300)
                self._set("已断开", f"同一机器人在别处建立了新连接，本连接已被替换；{int(wait)} 秒后重试"
                                    "（请确认只部署了一个实例）")
                log.warning("企业微信长连接被新连接替换")
                self._stop.wait(wait)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                error = redact(f"{type(exc).__name__}: {exc}".replace(cfg[1], "***"), 300)
                self._set("已断开", error, retry_in_seconds=backoff)
                log.warning("企业微信长连接断开，%s 秒后重连：%s", backoff, error)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, self._number("backoff_max_seconds", 60))
        self._set("已停止")

    def _session(self, cfg: tuple[str, str, str]) -> None:
        bot_id, secret, url = cfg
        self._set("连接中")
        # 企业微信服务端不支持 WebSocket 协议层 ping（收到即断开），保活只能靠应用层 cmd=ping
        with self._connect(url, open_timeout=10, close_timeout=2, ping_interval=None, compression=None) as ws:
            self._ws = ws
            try:
                self._send({"cmd": "aibot_subscribe", "headers": {"req_id": _req_id()},
                            "body": {"bot_id": bot_id, "secret": secret}})
                ack = json.loads(ws.recv(timeout=SUBSCRIBE_TIMEOUT))
                if ack.get("errcode") != 0:
                    raise SubscribeFailed(f"订阅失败 errcode={ack.get('errcode')} errmsg={ack.get('errmsg')}")
                self._set("已连接", bot_id=bot_id, connected_at=int(time.time()))
                log.info("企业微信长连接已建立：bot_id=%s", bot_id)
                self._loop(ws, cfg)
            finally:
                self._ws = None

    def _loop(self, ws, cfg) -> None:
        last_ping = last_recv = last_cfg = time.monotonic()
        ping_interval = self._ping_interval()
        while not self._stop.is_set():
            now = time.monotonic()
            if now - last_ping >= ping_interval:
                self._send({"cmd": "ping", "headers": {"req_id": _req_id()}})
                last_ping = now
            if now - last_cfg >= CONFIG_POLL:
                last_cfg = now
                if self._config() != cfg:
                    log.info("企业微信配置已变更，重新连接")
                    return
                ping_interval = self._ping_interval()
            if now - last_recv > 2 * ping_interval + 15:   # 这么久没有任何下行帧（含 ping 应答）视为连接已死
                raise ConnectionError("长时间未收到企业微信下行数据（心跳超时）")
            try:
                raw = ws.recv(timeout=1)
            except TimeoutError:
                continue
            last_recv = time.monotonic()
            try:
                frame = json.loads(raw)
            except ValueError:
                log.warning("企业微信下行帧不是 JSON，已忽略")
                continue
            self._dispatch(frame)

    def _dispatch(self, frame: dict) -> None:
        cmd = frame.get("cmd")
        req_id = (frame.get("headers") or {}).get("req_id") or ""
        body = frame.get("body") or {}
        if cmd == "aibot_msg_callback":
            self._pool.submit(self._safe, process_message, self.rt, body, self._responder(req_id))
        elif cmd == "aibot_event_callback":
            event = (body.get("event") or {}).get("eventtype")
            if event == "disconnected_event":
                raise Kicked()
            if event == "enter_chat":
                self._pool.submit(self._safe, self._welcome, req_id, body)
        elif frame.get("errcode") not in (None, 0):
            log.warning("企业微信返回错误：errcode=%s errmsg=%s", frame.get("errcode"), frame.get("errmsg"))

    def _responder(self, req_id: str) -> Respond:
        stream_id = uuid.uuid4().hex

        def respond(content: str, finish: bool) -> None:
            self._send({"cmd": "aibot_respond_msg", "headers": {"req_id": req_id},
                        "body": {"msgtype": "stream",
                                 "stream": {"id": stream_id, "finish": finish, "content": content}}})
        return respond

    def _welcome(self, req_id: str, body: dict | None = None) -> None:
        body = body or {}
        content = welcome_text(self.rt)
        userid = str((body.get("from") or {}).get("userid") or "")
        if userid:
            try:
                session, _ = wecom_session(self.rt, userid)
                content = welcome_text(self.rt, oa=session.oa, office_token=session.office_token)
            except (AppError, OfficeApiError) as exc:
                log.warning(
                    "企业微信欢迎语身份解析失败：%s %s",
                    getattr(exc, "code", ""),
                    redact(getattr(exc, "message", "")),
                )
                content = getattr(exc, "user_message", "") or service.text(self.rt, "wecom_identity_failed")
        self._send({"cmd": "aibot_respond_welcome_msg", "headers": {"req_id": req_id},
                    "body": {"msgtype": "text", "text": {"content": content}}})

    def _send(self, frame: dict) -> None:
        ws = self._ws
        if ws is None:
            raise ConnectionError("企业微信长连接未建立")
        with self._send_lock:
            ws.send(json.dumps(frame, ensure_ascii=False))

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001 —— 单条消息失败不影响连接
            log.exception("处理企业微信消息失败")


def _req_id() -> str:
    return uuid.uuid4().hex
