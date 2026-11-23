"""开发登录：后台开关 + 共享口令 → mint → ticket（channel=dev_login）。"""

from __future__ import annotations

import json

import httpx
import pytest
import sqlalchemy as sa

from oa_agent.auth import chat_launch
from oa_agent.db.models import AuditLog
from tests.test_chat import OFFICE, chat, make_assertion, office, open_chat, runtime  # noqa: F401

PASS = "dev-pass-for-tests"


def _enable_dev(admin, passphrase=PASS, enabled=True):
    values = {"dev_login_enabled": enabled}
    if passphrase is not None:
        values["dev_login_passphrase"] = passphrase
    r = admin.put("/v1/admin/settings/chat", json={"values": values})
    assert r.status_code == 200, r.text


def test_dev_status_off_by_default(chat):
    r = chat.get("/v1/chat/dev/status")
    assert r.status_code == 200 and r.json() == {"enabled": False}


def test_dev_status_requires_passphrase(admin, chat):
    _enable_dev(admin, passphrase=None, enabled=True)
    # 未设置口令时不可用（开关开但 secret 空）
    assert chat.get("/v1/chat/dev/status").json()["enabled"] is False
    _enable_dev(admin, passphrase=PASS, enabled=True)
    body = chat.get("/v1/chat/dev/status").json()
    assert body == {"enabled": True}
    assert "passphrase" not in json.dumps(body)


def test_dev_session_disabled(chat):
    r = chat.post("/v1/chat/dev/session", json={"oa": "zhangsan", "passphrase": PASS})
    assert r.status_code == 403 and r.json()["error"]["code"] == "DEV_LOGIN_DISABLED"


def test_dev_session_wrong_passphrase(admin, chat, office):
    _enable_dev(admin)
    r = chat.post("/v1/chat/dev/session", json={"oa": "zhangsan", "passphrase": "wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "DEV_LOGIN_INVALID"
    assert office.calls.call_count == 0
    rt = runtime(chat)
    with rt.session() as db:
        row = db.scalar(sa.select(AuditLog).where(AuditLog.action == "chat.dev_login").order_by(AuditLog.id.desc()))
        assert row is not None and row.result == "failure"
        assert "wrong" not in (row.reason or "")
        assert "passphrase" not in (row.after_summary or "")


def test_dev_session_mint_failure(admin, chat, office):
    _enable_dev(admin)
    office.post(f"{OFFICE}/agent/token/mint").mock(return_value=httpx.Response(200, json={"code": 500, "msg": "x"}))
    r = chat.post("/v1/chat/dev/session", json={"oa": "zhangsan", "passphrase": PASS})
    assert r.status_code == 502 and r.json()["error"]["code"] == "MINT_FAILED"


def test_dev_session_success_ticket_and_channel(admin, chat, office):
    _enable_dev(admin)
    r = chat.post("/v1/chat/dev/session", json={"oa": "zhangsan", "passphrase": PASS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["oa"] == "zhangsan" and body["thread_id"].startswith("thr_")
    assert "ticket" in body and "office_token" not in json.dumps(body)
    h = {"Authorization": f"Bearer {body['ticket']}"}
    me = chat.get("/v1/chat/session", headers=h)
    assert me.status_code == 200 and me.json()["display_name"]
    rt = runtime(chat)
    session = chat_launch.load_session(rt.kv.current, body["ticket"])
    assert session is not None and session.channel == "dev_login"
    with rt.session() as db:
        row = db.scalar(
            sa.select(AuditLog).where(AuditLog.action == "chat.dev_login", AuditLog.result == "success")
            .order_by(AuditLog.id.desc())
        )
        assert row is not None and row.actor_id == "zhangsan"


def test_formal_launch_still_works_when_dev_off(chat):
    r = chat.post("/v1/chat/launch", json={"assertion": make_assertion()})
    assert r.status_code == 200
    opened = chat.post("/v1/chat/session", json={"launch_code": r.json()["launch_code"]})
    assert opened.status_code == 200
    assert open_chat(chat)["Authorization"].startswith("Bearer ")
