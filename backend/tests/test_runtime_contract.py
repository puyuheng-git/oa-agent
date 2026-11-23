"""候选契约：非 builtin 孤儿不进候选；未绑定的 builtin 仍可用；Pack 不扩业务 Tool。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from oa_agent.runtime.graphs.oa_assistant import (
    EXPORT_TOOL,
    SKILL_LOAD_TOOL,
    RunContext,
)
from oa_agent.runtime.react.validate import DecisionValidationError, validate_tool_decision


class FakeSpec:
    """注册表桩：tools() 只读 kind；执行门禁只读 name。"""

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind
        self.version = "t"
        self.model_params: dict = {}
        self.summary = name


class FakeSkill:
    def __init__(self, name: str, display_name: str, tools: list[str]):
        self.name = name
        self.display_name = display_name
        self.description = ""
        self.instructions = ""
        self.tools = tools
        self.enabled = True
        self.valid = True


class FakeReg:
    def __init__(self, specs: dict):
        self._specs = specs

    def names(self):
        return list(self._specs)

    def get(self, name):
        return self._specs.get(name)


def _ctx(specs: dict, skills, packs=None) -> RunContext:
    executor = SimpleNamespace(registry=FakeReg(specs))
    return RunContext(
        recorder=SimpleNamespace(),
        identity=SimpleNamespace(oa="alice"),
        executor=executor,
        today=date(2026, 11, 20),
        skills=skills,
        skill_packs=list(packs or []),
    )


def _sample_specs() -> dict:
    return {
        "orphan_office": FakeSpec("orphan_office", kind="office"),
        "orphan_invoke": FakeSpec("orphan_invoke", kind="open_oa_invoke"),
        "orphan_mcp": FakeSpec("orphan_mcp", kind="mcp"),
        "bound_office": FakeSpec("bound_office", kind="office"),
        "sys_calc": FakeSpec("sys_calc", kind="builtin"),
        EXPORT_TOOL: FakeSpec(EXPORT_TOOL, kind="builtin"),
        SKILL_LOAD_TOOL: FakeSpec(SKILL_LOAD_TOOL, kind="builtin"),
        "query_leave": FakeSpec("query_leave", kind="office"),
    }


def test_tools_excludes_orphan_non_builtin():
    """skills 已给出时：绑定 Tool 与未门禁的 builtin 进候选；office/invoke/mcp 孤儿不进。"""
    skill = FakeSkill("travel", "行程", tools=["bound_office"])
    ctx = _ctx(_sample_specs(), skills=[skill], packs=[])
    names = set(ctx.tools())
    assert "bound_office" in names
    assert "orphan_office" not in names
    assert "orphan_invoke" not in names
    assert "orphan_mcp" not in names
    # 未绑 Skill 的 builtin 必须在候选里。EXPORT 本来就会注入，不能用「或 EXPORT」代替本断言。
    assert "sys_calc" in names
    assert EXPORT_TOOL in names


def test_bound_builtin_keeps_declaring_skill():
    """已绑到目录 Skill 的 builtin 保留该 Skill，不被全局例外覆盖成 None。"""
    skill = FakeSkill("calc", "计算", tools=["sys_calc"])
    ctx = _ctx(_sample_specs(), skills=[skill], packs=[])
    _spec, owner = ctx.tools()["sys_calc"]
    assert owner is skill


def test_skills_none_exposes_full_registry_empty_list_does_not():
    """skills=None 仍暴露全注册表（兼容旧单测）；空列表按契约收窄，只留绑定与 builtin。"""
    specs = _sample_specs()
    full = set(_ctx(specs, skills=None).tools())
    assert "orphan_office" in full
    assert "sys_calc" in full
    assert "bound_office" in full

    narrowed = set(_ctx(specs, skills=[]).tools())
    assert "orphan_office" not in narrowed
    assert "query_leave" not in narrowed
    assert "sys_calc" in narrowed
    assert EXPORT_TOOL in narrowed


def test_skill_pack_does_not_inject_business_tools():
    """Pack 即使带业务 Tool 名，也不得进入候选；SKILL_* / 其它 builtin 可以。"""
    pack = SimpleNamespace(
        kind="user",
        name="leave-tips",
        tools=["query_leave", "orphan_office", "orphan_mcp"],
    )
    ctx = _ctx(_sample_specs(), skills=[], packs=[pack])
    names = set(ctx.tools())
    assert "query_leave" not in names
    assert "orphan_office" not in names
    assert "orphan_mcp" not in names
    assert SKILL_LOAD_TOOL in names
    assert "sys_calc" in names


def test_pack_gated_builtins_need_skill_packs():
    """无包时不注入元工具；系统包才带上创建/更新，并挂到合成 Skill。"""
    from oa_agent.runtime.graphs.oa_assistant import (
        SKILL_CREATE_TOOL,
        SKILL_EDIT_TOOL,
        SKILL_EXEC_TOOL,
        SKILL_READ_TOOL,
    )

    specs = _sample_specs()
    specs[SKILL_READ_TOOL] = FakeSpec(SKILL_READ_TOOL, kind="builtin")
    specs[SKILL_EXEC_TOOL] = FakeSpec(SKILL_EXEC_TOOL, kind="builtin")
    specs[SKILL_CREATE_TOOL] = FakeSpec(SKILL_CREATE_TOOL, kind="builtin")
    specs[SKILL_EDIT_TOOL] = FakeSpec(SKILL_EDIT_TOOL, kind="builtin")
    gated = {SKILL_LOAD_TOOL, SKILL_READ_TOOL, SKILL_EXEC_TOOL, SKILL_CREATE_TOOL, SKILL_EDIT_TOOL}

    empty = set(_ctx(specs, skills=[], packs=[]).tools())
    assert gated.isdisjoint(empty)
    assert "sys_calc" in empty

    system = SimpleNamespace(kind="system", name="skill-creator", tools=[])
    tools = _ctx(specs, skills=[], packs=[system]).tools()
    assert SKILL_CREATE_TOOL in tools and SKILL_EDIT_TOOL in tools
    assert tools[SKILL_CREATE_TOOL][1].name == "agent_skill_create"
    assert tools[SKILL_EDIT_TOOL][1].name == "agent_skill_edit"


def test_orphan_rejected_before_execute():
    """孤儿不在允许集：决策校验拒绝，且与 call_tool 同一条件（name not in ctx.tools()）。"""
    skill = FakeSkill("travel", "行程", tools=["bound_office"])
    ctx = _ctx(_sample_specs(), skills=[skill], packs=[])
    allowed = ctx.tools()
    assert "orphan_office" not in allowed
    with pytest.raises(DecisionValidationError) as raised:
        validate_tool_decision(tool="orphan_office", args={}, steps=None, tools=allowed)
    assert raised.value.code == "TOOL_NOT_AVAILABLE"
    # 绑定工具与 builtin 例外可以通过这道门
    validate_tool_decision(tool="bound_office", args={}, steps=None, tools=allowed)
    validate_tool_decision(tool="sys_calc", args={}, steps=None, tools=allowed)


def test_chat_build_context_skills_never_none(monkeypatch):
    """生产对话组装 RunContext 时 skills 必须是列表；上游给出 None 也要收成 []。"""
    import oa_agent.chat.service as chat

    monkeypatch.setattr(chat, "visible_skills_for", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "_load_skill_packs", lambda *args, **kwargs: [])
    monkeypatch.setattr(chat, "_runtime_routing_defaults", lambda rt: {})
    monkeypatch.setattr(chat, "_model", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "_model_pairs", lambda *args, **kwargs: [])
    monkeypatch.setattr(chat, "_router_model_pairs", lambda *args, **kwargs: [])
    monkeypatch.setattr(chat, "_load_long_term_memory", lambda *args, **kwargs: "")
    monkeypatch.setattr(chat, "_recent_tool_names", lambda *args, **kwargs: [])
    monkeypatch.setattr(chat, "tool_clients", lambda rt: {})
    monkeypatch.setattr(chat, "tool_connectors", lambda rt: None)
    monkeypatch.setattr(chat, "get_mcp_client", lambda rt: None)
    monkeypatch.setattr(chat, "build_builtin_runtime", lambda rt: None)
    monkeypatch.setattr(chat, "setting", lambda rt, group, key: 100)
    monkeypatch.setattr(chat, "load_settings", lambda rt, group: {})

    session = SimpleNamespace(oa="alice", office_token="tok", thread_id="th-1", credentials={})
    rec = SimpleNamespace(run_id="run-1")
    rt = SimpleNamespace(
        tenant_id="dscpa",
        settings=SimpleNamespace(data_dir=None),
        engine=SimpleNamespace(live_registry=FakeReg({})),
        session=lambda: None,
    )
    ctx = chat._build_context(rt, rec, session, {})
    assert ctx.skills is not None
    assert ctx.skills == []

    # 领域裁剪若返回 None，同样不得把 None 传进 RunContext
    monkeypatch.setattr(chat.multi_agent, "filter_skills", lambda skills, domain: None)
    domain = SimpleNamespace(name="finance", skill_names=frozenset(), system_extra="")
    narrowed = chat._build_context(rt, rec, session, {}, domain=domain)
    assert narrowed.skills == []


def _err_message(response) -> str:
    """管理端错误体是 error.message；兼容 brief 里的 detail / message。"""
    body = response.json()
    err = body.get("error") or {}
    return err.get("message") or body.get("detail") or body.get("message") or ""


def _office_tool(name: str) -> dict:
    from tests.test_catalog_admin import LEAVE_TOOL

    return {**LEAVE_TOOL, "name": name, "summary": name, "reason": "入库闸门测试"}


def _skill_body(name: str, tools: list[str]) -> dict:
    from tests.test_catalog_admin import LEAVE_SKILL

    return {**LEAVE_SKILL, "name": name, "display_name": name, "tools": tools, "reason": "入库闸门测试"}


def test_enable_orphan_office_tool_allowed(admin):
    """未绑定 Skill 的非 builtin Tool 也可启用；对话仍只经 Skill 暴露，列表标 skill_bound=false。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    name = "orphan_x"
    created = admin.post("/v1/admin/tools", json=_office_tool(name))
    assert created.status_code == 200, created.text
    assert created.json()["tool"]["enabled"] is False
    assert created.json()["tool"]["kind"] == "office"
    disabled = admin.post(f"/v1/admin/tools/{name}/disable", json={"reason": "先停用"})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False

    r = admin.post(f"/v1/admin/tools/{name}/enable", json={"reason": "未绑 Skill 也启用"})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert r.json().get("skill_bound") is False
    listed = admin.get("/v1/admin/tools").json()["items"]
    row = next(i for i in listed if i["name"] == name)
    assert row["enabled"] is True
    assert row["skill_bound"] is False


def test_list_orphans_includes_unbound(admin):
    """孤儿清单只含未绑定的非 builtin；已绑定业务 Tool 与 builtin 不出现。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    created = admin.post("/v1/admin/tools", json=_office_tool("orphan_x"))
    assert created.status_code == 200, created.text
    disabled = admin.post("/v1/admin/tools/orphan_x/disable", json={"reason": "先停用"})
    assert disabled.status_code == 200, disabled.text

    r = admin.get("/v1/admin/tools/orphans")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    names = [i["name"] for i in items]
    assert "orphan_x" in names
    row = next(i for i in items if i["name"] == "orphan_x")
    assert set(row) >= {"name", "kind", "enabled"}
    assert row["kind"] == "office"
    assert row["enabled"] is False
    assert "builtin.time" not in names
    assert "query_my_travel_expense_list" not in names


def test_enable_office_tool_after_skill_bind(admin):
    """绑上 Skill 之后，同一只 office Tool 可以启用。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    name = "bound_office_gate"
    assert admin.post("/v1/admin/tools", json=_office_tool(name)).status_code == 200
    assert admin.post(f"/v1/admin/tools/{name}/disable", json={"reason": "先停用"}).status_code == 200
    skill = admin.post("/v1/admin/skills", json=_skill_body("bind_office_gate", [name]))
    assert skill.status_code == 200, skill.text

    r = admin.post(f"/v1/admin/tools/{name}/enable", json={"reason": "已绑定"})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True


def test_enable_builtin_without_skill_allowed(admin):
    """builtin 不要求 Skill 绑定，停用后仍可启用，且不进孤儿清单。"""
    disabled = admin.post("/v1/admin/tools/builtin.calc/disable", json={"reason": "停内置"})
    assert disabled.status_code == 200, disabled.text
    r = admin.post("/v1/admin/tools/builtin.calc/enable", json={"reason": "开内置"})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    names = [i["name"] for i in admin.get("/v1/admin/tools/orphans").json()["items"]]
    assert "builtin.calc" not in names


def test_skill_put_rejects_unbinding_enabled_tool(admin):
    """保存 Skill 若使已启用的非 builtin Tool 失去全部引用，拒绝并保持原绑定。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    keep, drop = "keep_bound_tool", "drop_enabled_tool"
    assert admin.post("/v1/admin/tools", json=_office_tool(keep)).status_code == 200
    assert admin.post("/v1/admin/tools", json=_office_tool(drop)).status_code == 200
    body = _skill_body("bind_two_tools", [keep, drop])
    created = admin.post("/v1/admin/skills", json=body)
    assert created.status_code == 200, created.text
    assert admin.post(f"/v1/admin/tools/{keep}/enable", json={"reason": "绑定后启用"}).status_code == 200
    assert admin.post(f"/v1/admin/tools/{drop}/enable", json={"reason": "绑定后启用"}).status_code == 200

    r = admin.put("/v1/admin/skills/bind_two_tools", json={**body, "tools": [keep], "reason": "解绑启用工具"})
    assert r.status_code == 400
    assert "请先改绑或先禁用 Tool" in _err_message(r)
    still = [t["name"] for t in admin.get("/v1/admin/skills/bind_two_tools").json()["tools"]]
    assert drop in still
    assert admin.get(f"/v1/admin/tools/{drop}").json()["enabled"] is True


def test_skill_put_allows_unbinding_disabled_tool(admin):
    """已禁用的 Tool 可以解绑，随后出现在孤儿清单。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    keep, drop = "keep_for_disable", "drop_disabled_tool"
    assert admin.post("/v1/admin/tools", json=_office_tool(keep)).status_code == 200
    assert admin.post("/v1/admin/tools", json=_office_tool(drop)).status_code == 200
    body = _skill_body("bind_then_disable", [keep, drop])
    assert admin.post("/v1/admin/skills", json=body).status_code == 200
    assert admin.post(f"/v1/admin/tools/{drop}/disable", json={"reason": "先禁用"}).status_code == 200

    r = admin.put("/v1/admin/skills/bind_then_disable", json={**body, "tools": [keep], "reason": "解绑已禁用"})
    assert r.status_code == 200, r.text
    names = [i["name"] for i in admin.get("/v1/admin/tools/orphans").json()["items"]]
    assert drop in names
    assert keep not in names


def test_skill_put_allows_unbind_when_other_skill_holds_tool(admin):
    """另一只 Skill 仍引用该 Tool 时，从当前 Skill 移除不算孤儿。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    shared, other = "shared_held_tool", "anchor_tool"
    assert admin.post("/v1/admin/tools", json=_office_tool(shared)).status_code == 200
    assert admin.post("/v1/admin/tools", json=_office_tool(other)).status_code == 200
    first = _skill_body("skill_drop_shared", [shared, other])
    second = _skill_body("skill_keep_shared", [shared])
    assert admin.post("/v1/admin/skills", json=first).status_code == 200
    assert admin.post("/v1/admin/skills", json=second).status_code == 200

    r = admin.put(
        "/v1/admin/skills/skill_drop_shared",
        json={**first, "tools": [other], "reason": "改由另一技能持有"},
    )
    assert r.status_code == 200, r.text
    names = [i["name"] for i in admin.get("/v1/admin/tools/orphans").json()["items"]]
    assert shared not in names


def test_external_mcp_skill_rejects_office_tool(admin):
    """种类 external_mcp 只能绑 mcp；绑 office Tool 时保存失败且不落库。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    tool_name = "office_on_mcp_skill"
    assert admin.post("/v1/admin/tools", json=_office_tool(tool_name)).status_code == 200
    body = _skill_body("mcp_skill_bad_kind", [tool_name])
    body["category"] = "external_mcp"

    r = admin.post("/v1/admin/skills", json=body)
    assert r.status_code == 422, r.text
    msg = _err_message(r)
    assert "external_mcp" in msg
    assert "office" in msg
    assert admin.get("/v1/admin/skills/mcp_skill_bad_kind").status_code == 404


def test_oa_query_skill_stores_category_and_allows_office(admin):
    """种类写进 content_json；oa_query 允许 office，空种类不参与路由键。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    tool_name = "office_on_query_skill"
    assert admin.post("/v1/admin/tools", json=_office_tool(tool_name)).status_code == 200
    body = _skill_body("query_skill_ok", [tool_name])
    body["category"] = "oa_query"

    r = admin.post("/v1/admin/skills", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "oa_query"
    detail = admin.get("/v1/admin/skills/query_skill_ok")
    assert detail.status_code == 200, detail.text
    assert detail.json()["versions"][0]["content"]["category"] == "oa_query"


def test_skill_save_rejects_unknown_category(admin):
    """种类只能是约束表里的值或空串。"""
    from tests.test_catalog_admin import _ensure_office_upstream

    _ensure_office_upstream(admin)
    tool_name = "office_for_bad_category"
    assert admin.post("/v1/admin/tools", json=_office_tool(tool_name)).status_code == 200
    body = _skill_body("skill_bad_category", [tool_name])
    body["category"] = "not_a_category"

    r = admin.post("/v1/admin/skills", json=body)
    assert r.status_code == 422, r.text
    assert "category" in _err_message(r)
    assert admin.get("/v1/admin/skills/skill_bad_category").status_code == 404


WF = "/v1/admin/workflows/oa_assistant"
TRUTH = "/v1/admin/routing/config-truth"


def _publish_legacy(admin) -> dict:
    from tests.workflow_helpers import publish_config

    return publish_config(
        admin,
        {"tool_routing_mode": "legacy_prompt"},
        reason="钉住海选快照",
    )


def test_config_truth_lists_legacy_prompt_release(admin):
    """当前发布钉在海选时，真相接口列出该 release，且与全局默认不一致。"""
    published = _publish_legacy(admin)
    r = admin.get(TRUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["global_mode"] == "deterministic_first"
    assert body["global_fallback"] == "skill_then_tool"
    assert body["note"] == "单次对话以会话绑定 release 快照为准"

    active = body["active_workflows"]
    row = next(i for i in active if i["release_id"] == published["release_id"])
    assert row["workflow_id"] == "oa_assistant"
    assert row["tool_routing_mode"] == "legacy_prompt"
    assert row["matches_global"] is False

    legacy_ids = [i["release_id"] for i in body["legacy_prompt_releases"]]
    assert published["release_id"] in legacy_ids
    assert all(i["tool_routing_mode"] == "legacy_prompt" for i in body["legacy_prompt_releases"])


def test_migrate_contract_writes_draft_and_leaves_published_frozen(admin):
    """迁移只改工作流草稿的路由键；已发布 content 保持海选，并写审计。"""
    from tests.conftest import audit_rows

    published = _publish_legacy(admin)
    before = admin.get(WF).json()
    published_hash = before["current_version"]["content_hash"]
    assert before["current_version"]["content"]["tool_routing_mode"] == "legacy_prompt"

    r = admin.post(
        f"/v1/admin/routing/releases/{published['release_id']}/migrate-contract",
        json={"confirm": True, "reason": "迁到契约默认"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["next_step"] == "publish"
    draft = body["draft_version"]
    content = draft["content"]
    assert content["tool_routing_mode"] == "deterministic_first"
    assert content["deterministic_fallback_mode"] == "skill_then_tool"
    assert content["routing_clarify_on_low_confidence"] is True

    after = admin.get(WF).json()
    assert after["current_version"]["content_hash"] == published_hash
    assert after["current_version"]["status"] == "published"
    assert after["current_version"]["content"]["tool_routing_mode"] == "legacy_prompt"
    assert after["draft"]["content"]["tool_routing_mode"] == "deterministic_first"
    assert after["draft"]["content"]["deterministic_fallback_mode"] == "skill_then_tool"
    assert after["draft"]["content"]["routing_clarify_on_low_confidence"] is True
    # 草稿继承发布快照里的非路由项，不把发布行改掉
    assert after["draft"]["content"]["help_text"] == before["current_version"]["content"]["help_text"]

    audits = audit_rows(admin, action="routing.snapshot.migrate")
    assert any(a["resource_id"] == published["release_id"] for a in audits)


def test_migrate_contract_requires_confirm(admin):
    """未确认时不写草稿。"""
    published = _publish_legacy(admin)
    r = admin.post(
        f"/v1/admin/routing/releases/{published['release_id']}/migrate-contract",
        json={"confirm": False, "reason": "还没确认"},
    )
    assert r.status_code == 422
    detail = admin.get(WF).json()
    assert detail["draft"] is None
    assert detail["current_version"]["content"]["tool_routing_mode"] == "legacy_prompt"


def test_ack_keep_legacy_hides_release_from_list(admin):
    """标记保留海选后，待迁移清单不再列出该 release；在用工作流仍显示真相。"""
    published = _publish_legacy(admin)
    r = admin.post(
        f"/v1/admin/routing/releases/{published['release_id']}/ack-keep-legacy",
        json={"confirm": True, "reason": "这版继续海选"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["acked"] is True

    truth = admin.get(TRUTH).json()
    legacy_ids = [i["release_id"] for i in truth["legacy_prompt_releases"]]
    assert published["release_id"] not in legacy_ids
    active = next(i for i in truth["active_workflows"] if i["release_id"] == published["release_id"])
    assert active["tool_routing_mode"] == "legacy_prompt"
    assert active["matches_global"] is False

    shown = admin.get(TRUTH, params={"include_acked": True}).json()
    assert published["release_id"] in [i["release_id"] for i in shown["legacy_prompt_releases"]]


def test_config_truth_readable_with_run_view_migrate_needs_config_edit(admin, installed):
    """ops.run.view 能读真相；没有 ops.config.edit 不能迁移。"""
    from fastapi.testclient import TestClient

    from tests.conftest import login
    from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

    published = _publish_legacy(admin)
    role = _role(admin, "run_view_only", ["ops.run.view"])
    _user(admin, "truth_reader", [role["id"]])
    reader = login(TestClient(installed.app), "truth_reader", VIEWER_PASS)
    got = reader.get(TRUTH)
    assert got.status_code == 200, got.text
    denied = reader.post(
        f"/v1/admin/routing/releases/{published['release_id']}/migrate-contract",
        json={"confirm": True, "reason": "越权迁移"},
    )
    assert denied.status_code == 403
