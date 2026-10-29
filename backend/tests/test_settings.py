import fakeredis
import pytest

import oa_agent.kv as kv_mod
from oa_agent.config.schema import default
from tests.conftest import audit_rows

GW_SECRET = "gw-secret-value-ABCD1234"
HMAC_SECRET = "hmac-secret-value-WXYZ5678"


def test_list_groups_masks_secrets(admin):
    r = admin.get("/v1/admin/settings")
    assert r.status_code == 200
    groups = {g["group"]: g for g in r.json()["groups"]}
    assert set(groups) >= {"redis", "oa", "wecom", "runtime"}
    assert groups["oa"]["values"]["gateway_secret"] == {"is_set": False, "display": "未设置"}
    assert groups["runtime"]["values"]["event_retention_days"] == 180


def test_oa_secrets_write_only_and_audited(admin):
    r = admin.put("/v1/admin/settings/oa", json={"values": {
        "mint_base_url": "https://office.example.com/api/",
        "upstreams": [{"key": "office", "label": "office-api", "base_url": "https://office.example.com/api/"}],
        "default_upstream_key": "office",
        "gateway_secret": GW_SECRET,
        "assertion_hmac_secret": HMAC_SECRET,
        "allowed_frame_origins": "https://oa.example.com, https://oa2.example.com",
    }})
    assert r.status_code == 200, r.text
    assert GW_SECRET not in r.text and HMAC_SECRET not in r.text
    vals = r.json()["group"]["values"]
    assert vals["gateway_secret"]["display"] == "已设置 · ****1234"
    assert vals["mint_base_url"] == "https://office.example.com/api"
    assert vals["upstreams"][0]["base_url"] == "https://office.example.com/api"
    assert vals["allowed_frame_origins"] == ["https://oa.example.com", "https://oa2.example.com"]

    got = admin.get("/v1/admin/settings/oa").text
    assert GW_SECRET not in got and HMAC_SECRET not in got

    # 留空 = 不修改
    r = admin.put("/v1/admin/settings/oa", json={"values": {"gateway_secret": ""}})
    assert r.json()["changed"] == []

    r = admin.put("/v1/admin/settings/oa", json={"values": {}, "clear_secrets": ["gateway_secret"]})
    assert r.json()["changed"] == ["gateway_secret"]
    assert r.json()["group"]["values"]["gateway_secret"]["is_set"] is False

    rows = audit_rows(admin, action="setting.update")
    assert len(rows) == 2
    blob = str(rows)
    assert GW_SECRET not in blob and HMAC_SECRET not in blob
    assert "已变更" in blob


def test_untouched_defaults_not_reported_as_changed(admin):
    r = admin.put("/v1/admin/settings/oa", json={"values": {"mint_base_url": "https://o.example.com",
                                                            "allowed_frame_origins": ""}})
    assert r.json()["changed"] == ["mint_base_url"]


def test_frame_origins_normalized_and_validated(admin):
    r = admin.put("/v1/admin/settings/oa", json={"values": {"allowed_frame_origins": "http://127.0.0.1/, http://oa.local:8080"}})
    assert r.status_code == 200, r.text
    assert r.json()["group"]["values"]["allowed_frame_origins"] == ["http://127.0.0.1", "http://oa.local:8080"]

    for bad in ("oa.example.com", "https://oa.example.com/general/", "https://*.example.com"):
        r = admin.put("/v1/admin/settings/oa", json={"values": {"allowed_frame_origins": bad}})
        assert r.status_code == 422, bad
        assert bad in r.json()["error"]["message"]


def test_url_with_password_rejected(admin):
    r = admin.put("/v1/admin/settings/redis", json={"values": {"url": "redis://:pw@127.0.0.1:6379"}})
    assert r.status_code == 422


def test_unknown_group_and_field(admin):
    assert admin.get("/v1/admin/settings/nope").status_code == 404
    r = admin.put("/v1/admin/settings/oa", json={"values": {"bogus": 1}})
    assert r.status_code == 422


def test_every_field_has_help_and_bounds(admin):
    groups = {g["group"]: g for g in admin.get("/v1/admin/settings").json()["groups"]}
    assert {"chat", "messages", "security", "import"} <= set(groups)
    for g in groups.values():
        assert g["description"], g["group"]
        for f in g["fields"]:
            assert f["help"], (g["group"], f["key"])
            if f["kind"] == "int":
                assert f["min"] is not None and f["max"] is not None, (g["group"], f["key"])


def test_security_floor_cannot_be_lowered(admin):
    r = admin.put("/v1/admin/settings/security", json={"values": {"password_min_length": 8}})
    assert r.status_code == 422 and "12" in r.json()["error"]["message"]
    r = admin.put("/v1/admin/settings/security", json={"values": {"login_max_failures": 100}})
    assert r.status_code == 422
    r = admin.put("/v1/admin/settings/runtime", json={"values": {"watchdog_interval_seconds": True}})
    assert r.status_code == 422, "布尔值不能冒充整数"
    r = admin.put("/v1/admin/settings/security", json={"values": {"password_min_length": 16}})
    assert r.status_code == 200, r.text
    r = admin.post("/v1/admin/accounts", json={"username": "ops2", "display_name": "运维二",
                                               "password": "Abcdefgh1234!", "role_ids": []})
    assert r.status_code == 422 and "16" in r.json()["error"]["message"]


def test_message_text_customizable_and_blank_restores_default(admin):
    r = admin.put("/v1/admin/settings/messages", json={"values": {"handoff": "已转给同事处理，请稍候。"}})
    assert r.status_code == 200 and r.json()["group"]["values"]["handoff"] == "已转给同事处理，请稍候。"
    r = admin.put("/v1/admin/settings/messages", json={"values": {"handoff": "  "}})
    assert r.json()["group"]["values"]["handoff"] == default("messages", "handoff")


def test_redis_unreachable_not_saved(admin):
    r = admin.put("/v1/admin/settings/redis", json={"values": {"url": "redis://127.0.0.1:1", "password": "p-1234567"}})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CONNECTION_TEST_FAILED"
    vals = admin.get("/v1/admin/settings/redis").json()["values"]
    assert vals["url"] is None and vals["password"]["is_set"] is False
    assert audit_rows(admin, action="setting.update") == []


@pytest.fixture
def fake_redis(monkeypatch):
    server = fakeredis.FakeServer()

    def client(url, db=0, password=None, timeout=3.0):
        return fakeredis.FakeRedis(server=server, decode_responses=True)

    monkeypatch.setattr(kv_mod, "redis_client", client)
    return server


def test_redis_test_and_hot_switch_keeps_session(admin, fake_redis):
    r = admin.post("/v1/admin/settings/redis/test", json={"values": {"url": "redis://cache:6379"}})
    assert r.status_code == 200 and r.json()["ok"] is True

    assert admin.get("/v1/admin/settings").json()["redis_status"]["backend"] == "memory"
    r = admin.put("/v1/admin/settings/redis", json={"values": {"url": "redis://cache:6379", "db": 2}})
    assert r.status_code == 200, r.text
    assert r.json()["redis_status"] == {"status": "ok", "backend": "redis"}

    # 内存中的会话已迁移到 Redis：同一 Cookie 仍可用
    assert admin.get("/v1/admin/auth/me").status_code == 200
    keys = fakeredis.FakeRedis(server=fake_redis, decode_responses=True).keys("adm:sess:*")
    assert len(keys) == 1
