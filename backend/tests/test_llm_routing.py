"""模型路由解析：resolve_model / resolve_candidates（设计 §4.1–4.4）。直接用库表种子，不依赖后台 API。"""

import pytest
import sqlalchemy as sa

from oa_agent.db.models import LlmDefaults, LlmModel, LlmProvider, LlmRoute
from oa_agent.runtime.llm import (
    ModelCallError, ModelConfig, invoke_json_failover, is_provider_error, resolve_candidates, resolve_model)


def _provider(rt, db, name="p1", enabled=True, key="sk-test-KEY9"):
    p = LlmProvider(tenant_id=rt.tenant_id, name=name, base_url="https://llm.example.com/v1", enabled=enabled)
    db.add(p)
    db.flush()
    if key:
        p.secret_ref = f"llm.provider.{p.id}.api_key"
        rt.vault.set(db, p.secret_ref, key, "tester")
    return p


def _model(rt, db, provider, name, tier="large", caps=("text",), enabled=True, tags=()):
    m = LlmModel(tenant_id=rt.tenant_id, provider_id=provider.id, model_name=name, capabilities=list(caps),
                 model_tier=tier, enabled=enabled, purpose_tags=list(tags))
    db.add(m)
    db.flush()
    return m


def _route(rt, db, cap, tier, ids, enabled=True):
    db.add(LlmRoute(tenant_id=rt.tenant_id, capability=cap, model_tier=tier, model_ids=list(ids), enabled=enabled))


def _defaults(rt, db, gid=None, max_failover=3):
    # 迁移/安装可能已种下默认行：有则覆盖，无则新增
    row = db.scalar(sa.select(LlmDefaults).where(LlmDefaults.tenant_id == rt.tenant_id))
    if row is None:
        db.add(LlmDefaults(tenant_id=rt.tenant_id, global_default_model_id=gid, max_failover=max_failover))
        return
    row.global_default_model_id, row.max_failover = gid, max_failover


def _ids(cands):
    return [c.model_id for c in cands]


def test_global_default_when_unspecified(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        _model(rt, db, p, "big")
        m2 = _model(rt, db, p, "small", tier="small")
        _defaults(rt, db, gid=m2.id)
        m2_id = m2.id
    with rt.session() as db:
        cfg = resolve_model(db, rt.vault, rt.tenant_id, None)
    assert cfg is not None and cfg.model_id == m2_id and cfg.model_tier == "small"


def test_legacy_fallback_purpose_then_any(installed):
    rt = installed.app.state.runtime
    with rt.session() as db:
        assert resolve_model(db, rt.vault, rt.tenant_id) is None
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        first = _model(rt, db, p, "a")
        tagged = _model(rt, db, p, "b", tags=["intent"])
        first_id, tagged_id = first.id, tagged.id
    with rt.session() as db:
        assert resolve_model(db, rt.vault, rt.tenant_id).model_id == tagged_id
        assert resolve_model(db, rt.vault, rt.tenant_id, purpose="other").model_id == first_id


def test_route_pool_text_small(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        _model(rt, db, p, "big")
        m2 = _model(rt, db, p, "small", tier="small")
        _route(rt, db, "text", "small", [m2.id])
        m2_id = m2.id
    with rt.session() as db:
        cfg = resolve_model(db, rt.vault, rt.tenant_id, None, capability="text", model_tier="small")
        none_cfg = resolve_model(db, rt.vault, rt.tenant_id, None, capability="vision", model_tier="small")
    assert cfg.model_id == m2_id
    assert none_cfg is None


def test_route_pool_skips_invalid_entries(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        nokey = _provider(rt, db, name="p2", key=None)
        off = _provider(rt, db, name="p3", enabled=False)
        a = _model(rt, db, nokey, "nokey", tier="small")
        b = _model(rt, db, off, "provoff", tier="small")
        c = _model(rt, db, p, "disabled", tier="small", enabled=False)
        d = _model(rt, db, p, "wrongtier", tier="large")
        e = _model(rt, db, p, "wrongcap", tier="small", caps=("vision",))
        ok = _model(rt, db, p, "ok", tier="small")
        _route(rt, db, "text", "small", [9999, a.id, b.id, c.id, d.id, e.id, ok.id])
        ok_id = ok.id
    with rt.session() as db:
        cands = resolve_candidates(db, rt.vault, rt.tenant_id, None, capability="text", model_tier="small")
    assert _ids(cands) == [ok_id]


def test_disabled_route_is_ignored(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        m = _model(rt, db, p, "small", tier="small")
        _route(rt, db, "text", "small", [m.id], enabled=False)
    with rt.session() as db:
        assert resolve_model(db, rt.vault, rt.tenant_id, None, capability="text", model_tier="small") is None


def test_pinned_id_first_then_pool_after_and_limit(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        ms = [_model(rt, db, p, f"m{i}") for i in range(5)]
        ids = [m.id for m in ms]
        _route(rt, db, "text", "large", ids)
        _defaults(rt, db, max_failover=3)
    with rt.session() as db:
        cands = resolve_candidates(db, rt.vault, rt.tenant_id, ids[1], capability="text")
        implicit = resolve_candidates(db, rt.vault, rt.tenant_id, ids[1])
    # 顺延只取其后，且总数 ≤ max_failover
    assert _ids(cands) == ids[1:4]
    assert _ids(implicit) == ids[1:4]


def test_pinned_unavailable_continues_after_it_in_pool(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        a = _model(rt, db, p, "a")
        b = _model(rt, db, p, "b", enabled=False)
        c = _model(rt, db, p, "c")
        d = _model(rt, db, p, "d")
        _route(rt, db, "text", "large", [a.id, b.id, c.id, d.id])
        a_id, b_id, c_id, d_id = a.id, b.id, c.id, d.id
    with rt.session() as db:
        cands = resolve_candidates(db, rt.vault, rt.tenant_id, b_id)
    assert _ids(cands) == [c_id, d_id] and a_id not in _ids(cands)


def test_pinned_unavailable_without_pool_falls_to_default(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        bad = _model(rt, db, p, "bad", enabled=False)
        good = _model(rt, db, p, "good")
        _defaults(rt, db, gid=good.id)
        bad_id, good_id = bad.id, good.id
    with rt.session() as db:
        assert _ids(resolve_candidates(db, rt.vault, rt.tenant_id, bad_id)) == [good_id]
        assert _ids(resolve_candidates(db, rt.vault, rt.tenant_id, 424242)) == [good_id]


def test_pinned_without_capability_picks_first_capability_pool(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        pinned = _model(rt, db, p, "pinned", caps=("text", "vision"))
        v = _model(rt, db, p, "v", caps=("vision",))
        t = _model(rt, db, p, "t", caps=("text",))
        # vision 池先创建，但 text 在固定顺序里更靠前
        _route(rt, db, "vision", "large", [pinned.id, v.id])
        _route(rt, db, "text", "large", [pinned.id, t.id])
        pinned_id, t_id = pinned.id, t.id
    with rt.session() as db:
        assert _ids(resolve_candidates(db, rt.vault, rt.tenant_id, pinned_id)) == [pinned_id, t_id]


def test_pinned_not_in_pool_with_capability_continues_from_head(installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        pinned = _model(rt, db, p, "pinned")
        a = _model(rt, db, p, "a")
        b = _model(rt, db, p, "b")
        _route(rt, db, "text", "large", [a.id, b.id])
        pinned_id, a_id, b_id = pinned.id, a.id, b.id
    with rt.session() as db:
        cands = resolve_candidates(db, rt.vault, rt.tenant_id, pinned_id, capability="text")
    assert _ids(cands) == [pinned_id, a_id, b_id]


def test_modelconfig_positional_compat_and_resolve_model_positional(installed):
    cfg = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})
    assert cfg.model_id == 0 and cfg.capabilities == ("text",) and cfg.model_tier == "large"
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        m = _model(rt, db, p, "m", tags=["intent"])
        m_id = m.id
    with rt.session() as db:
        # 旧签名：位置传 model_id 与 purpose
        assert resolve_model(db, rt.vault, rt.tenant_id, m_id, "intent").model_id == m_id


# ---- Admin API：defaults / routes / set-default / 模型字段 ----


def _mk_provider(admin, name="p1"):
    r = admin.post("/v1/admin/llm/providers", json={
        "name": name, "base_url": "https://llm.example.com/v1", "api_key": "sk-x"})
    assert r.status_code == 200, r.text
    return r.json()


def _mk_model(admin, pid, name, **kw):
    r = admin.post("/v1/admin/llm/models", json={"provider_id": pid, "model_name": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _audit_actions(admin):
    from tests.conftest import audit_rows
    return [r["action"] for r in audit_rows(admin)]


def test_set_default_and_list_defaults(admin):
    p = _mk_provider(admin)
    m = _mk_model(admin, p["id"], "a")
    assert m["capabilities"] == ["text"] and m["model_tier"] == "large" and m["is_default"] is False
    r = admin.post(f"/v1/admin/llm/models/{m['id']}/set-default")
    assert r.status_code == 200
    assert r.json()["global_default_model_id"] == m["id"]
    d = admin.get("/v1/admin/llm/defaults").json()
    assert d["global_default_model_id"] == m["id"]
    assert d["max_failover"] == 3
    items = admin.get("/v1/admin/llm/models").json()["items"]
    assert [i["is_default"] for i in items] == [True]
    assert "llm.model.set_default" in _audit_actions(admin)


def test_set_default_switches_flag_and_404(admin):
    p = _mk_provider(admin)
    a = _mk_model(admin, p["id"], "a")
    b = _mk_model(admin, p["id"], "b")
    admin.post(f"/v1/admin/llm/models/{a['id']}/set-default")
    admin.post(f"/v1/admin/llm/models/{b['id']}/set-default")
    flags = {i["model_name"]: i["is_default"] for i in admin.get("/v1/admin/llm/models").json()["items"]}
    assert flags == {"a": False, "b": True}
    assert admin.post("/v1/admin/llm/models/99999/set-default").status_code == 404


def test_put_defaults_updates_and_validates(admin):
    p = _mk_provider(admin)
    m = _mk_model(admin, p["id"], "a")
    r = admin.put("/v1/admin/llm/defaults", json={"global_default_model_id": m["id"], "max_failover": 5})
    assert r.status_code == 200
    assert r.json()["global_default_model_id"] == m["id"] and r.json()["max_failover"] == 5
    assert admin.get("/v1/admin/llm/defaults").json()["max_failover"] == 5
    bad = admin.put("/v1/admin/llm/defaults", json={"global_default_model_id": 99999, "max_failover": 3})
    assert bad.status_code == 404
    bad = admin.put("/v1/admin/llm/defaults", json={"global_default_model_id": None, "max_failover": 0})
    assert bad.status_code == 422
    # 允许清空默认模型
    r = admin.put("/v1/admin/llm/defaults", json={"global_default_model_id": None, "max_failover": 2})
    assert r.status_code == 200 and r.json()["global_default_model_id"] is None
    assert "llm.defaults.update" in _audit_actions(admin)


def test_model_fields_validated(admin):
    p = _mk_provider(admin)
    m = _mk_model(admin, p["id"], "mm", capabilities=["vision", "text", "vision"], model_tier="small")
    assert m["capabilities"] == ["vision", "text"] and m["model_tier"] == "small"
    url = "/v1/admin/llm/models"
    assert admin.post(url, json={"provider_id": p["id"], "model_name": "x", "capabilities": ["audio"]}).status_code == 422
    assert admin.post(url, json={"provider_id": p["id"], "model_name": "y", "model_tier": "huge"}).status_code == 422
    assert admin.post(url, json={"provider_id": p["id"], "model_name": "z", "capabilities": []}).status_code == 422
    r = admin.put(f"{url}/{m['id']}", json={
        "provider_id": p["id"], "model_name": "mm", "capabilities": ["embedding"], "model_tier": "large"})
    assert r.json()["capabilities"] == ["embedding"] and r.json()["model_tier"] == "large"


def test_put_route_warns_mismatch(admin):
    p = _mk_provider(admin)
    m = _mk_model(admin, p["id"], "v", capabilities=["vision"], model_tier="large")
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "large", "model_ids": [m["id"]], "enabled": True})
    assert r.status_code == 200
    assert r.json()["warnings"]
    assert r.json()["model_ids"] == [m["id"]]


def test_put_route_tier_mismatch_warns_and_ok_has_none(admin):
    p = _mk_provider(admin)
    good = _mk_model(admin, p["id"], "g", model_tier="small")
    wrong = _mk_model(admin, p["id"], "w", model_tier="large")
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "small", "model_ids": [good["id"], wrong["id"]], "enabled": True})
    assert len(r.json()["warnings"]) == 1
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "small", "model_ids": [good["id"]], "enabled": True})
    assert r.json()["warnings"] == []


def test_routes_crud_overwrite_and_audit(admin):
    p = _mk_provider(admin)
    a = _mk_model(admin, p["id"], "a")
    b = _mk_model(admin, p["id"], "b")
    assert admin.get("/v1/admin/llm/routes").json() == {"items": []}
    body = {"capability": "text", "model_tier": "large", "model_ids": [a["id"], b["id"], a["id"]], "enabled": True}
    r = admin.put("/v1/admin/llm/routes", json=body)
    assert r.status_code == 200 and r.json()["model_ids"] == [a["id"], b["id"]]
    # 覆盖同一池
    body.update(model_ids=[b["id"]], enabled=False)
    r = admin.put("/v1/admin/llm/routes", json=body)
    assert r.json()["model_ids"] == [b["id"]] and r.json()["enabled"] is False
    items = admin.get("/v1/admin/llm/routes").json()["items"]
    assert len(items) == 1 and items[0]["capability"] == "text" and items[0]["enabled"] is False
    assert admin.delete("/v1/admin/llm/routes/text/large").json() == {"ok": True}
    assert admin.get("/v1/admin/llm/routes").json()["items"] == []
    assert admin.delete("/v1/admin/llm/routes/text/large").status_code == 404
    actions = _audit_actions(admin)
    assert "llm.route.put" in actions and "llm.route.delete" in actions


def test_put_route_rejects_unknown_model_and_bad_enum(admin):
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "large", "model_ids": [99999], "enabled": True})
    assert r.status_code == 404
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "audio", "model_tier": "large", "model_ids": [], "enabled": True})
    assert r.status_code == 422
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "mid", "model_ids": [], "enabled": True})
    assert r.status_code == 422
    assert admin.delete("/v1/admin/llm/routes/audio/large").status_code == 404


# ---- 运行失败顺延（设计 §4.3）----

class _Boom:
    def invoke(self, messages):
        raise ConnectionError("down")


class _Resp:
    response_metadata: dict = {}
    usage_metadata = None

    def __init__(self, content):
        self.content = content


class _Fixed:
    def __init__(self, content):
        self.content, self.calls = content, 0

    def invoke(self, messages):
        self.calls += 1
        return _Resp(self.content)


class _Rec:
    """RunRecorder 最小替身：invoke_json 只用到这几个成员。"""

    def __init__(self):
        self.model_call_count, self.model_logs, self.usages, self.events = 0, [], [], []

    def event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def _cfg(mid):
    return ModelConfig("p", "http://x", "k", 30, f"m{mid}", {}, mid)


def test_is_provider_error():
    assert is_provider_error(ModelCallError("connection reset"))
    assert is_provider_error(ConnectionError("x"))
    assert not is_provider_error(ModelCallError("模型输出不是合法 JSON"))
    assert not is_provider_error(ModelCallError("模型没有输出内容"))


def test_failover_skips_provider_error():
    rec, ok = _Rec(), _Fixed('{"reply":"hi"}')
    out = invoke_json_failover([(_Boom(), _cfg(1)), (ok, _cfg(2))], [("human", "hi")], rec, "understand")
    assert out["reply"] == "hi" and ok.calls == 1
    assert rec.model_call_count == 2
    assert rec.model_logs[0]["status"] == "error" and rec.model_logs[-1]["status"] == "ok"
    assert rec.model_logs[-1]["failover_from"] == 1 and rec.model_logs[-1]["attempt"] == 2


def test_failover_no_marker_on_first_success():
    rec = _Rec()
    invoke_json_failover([(_Fixed('{"reply":"hi"}'), _cfg(1)), (_Fixed("{}"), _cfg(2))], [("human", "hi")], rec, "x")
    assert "failover_from" not in rec.model_logs[-1]


def test_failover_invalid_json_does_not_switch():
    rec, second = _Rec(), _Fixed('{"reply":"hi"}')
    with pytest.raises(ModelCallError, match="合法 JSON"):
        invoke_json_failover([(_Fixed("not json"), _cfg(1)), (second, _cfg(2))], [("human", "hi")], rec, "x")
    assert second.calls == 0 and rec.model_call_count == 1


def test_failover_exhausted_raises_last_provider_error():
    rec = _Rec()
    with pytest.raises(ModelCallError, match="down"):
        invoke_json_failover([(_Boom(), _cfg(1)), (_Boom(), _cfg(2))], [("human", "hi")], rec, "x")
    assert rec.model_call_count == 2


def test_failover_empty_pairs_rejected():
    with pytest.raises(ModelCallError):
        invoke_json_failover([], [("human", "hi")], _Rec(), "x")

# ---- 路由阶段不继承发布配置 llm_model_id（设计 §4.5）----

def test_router_pairs_prefer_small_pool_over_release_pin(installed):
    from oa_agent.chat.service import _router_model_pairs
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        p = _provider(rt, db)
        big = _model(rt, db, p, "big")
        small = _model(rt, db, p, "small", tier="small")
        _route(rt, db, "text", "small", [small.id])
        big_id, small_id = big.id, small.id
    release = {"llm_model_id": str(big_id)}
    pairs = _router_model_pairs(rt, release, {})
    assert [cfg.model_id for _, cfg in pairs][0] == small_id


# ---- 正文已流式输出后不再顺延 ----

class _StreamThenBoom:
    """先流出部分 reply 正文，再抛提供方错误。"""

    def __init__(self):
        self.calls = 0

    def stream(self, messages):
        self.calls += 1
        yield _Resp('{"reply":"he')
        raise ConnectionError("dropped")


def test_failover_after_reply_streamed_reraises():
    rec, second, deltas = _Rec(), _Fixed('{"reply":"hi"}'), []
    first = _StreamThenBoom()
    with pytest.raises(ModelCallError, match="dropped"):
        invoke_json_failover([(first, _cfg(1)), (second, _cfg(2))], [("human", "hi")], rec, "x",
                             on_delta=deltas.append)
    assert deltas == ["he"] and second.calls == 0 and rec.model_call_count == 1


def test_failover_before_reply_streamed_still_switches():
    class _BoomBeforeText:
        def stream(self, messages):
            raise ConnectionError("down")
            yield  # pragma: no cover

    rec, second = _Rec(), _Fixed('{"reply":"hi"}')
    out = invoke_json_failover([(_BoomBeforeText(), _cfg(1)), (second, _cfg(2))], [("human", "hi")], rec, "x",
                               on_delta=lambda s: None)
    assert out["reply"] == "hi" and second.calls == 1
