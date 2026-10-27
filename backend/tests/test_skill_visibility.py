"""Skill 可见性规则（Subsystem C）数据层冒烟与运行时过滤"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa

from oa_agent.db.models import Skill, SkillVisibilityRule
from oa_agent.runtime.llm import ModelConfig

pytest_plugins = ("tests.test_chat",)

from tests.conftest import audit_rows, login

CFG = ModelConfig("fake", "http://llm", None, 10, "fake-model", {})


@pytest.fixture
def rt(installed):
    return installed.app.state.runtime


@pytest.fixture
def admin_client(installed):
    return login(installed)


def _skill_id(rt, name: str) -> int:
    with rt.session() as db:
        sid = db.scalar(sa.select(Skill.id).where(Skill.tenant_id == rt.tenant_id, Skill.name == name))
    assert sid is not None, f"skill {name!r} not in catalog"
    return sid


def _allow_oa_only(rt, skill_name: str, oa: str) -> None:
    sid = _skill_id(rt, skill_name)
    with rt.session() as db, db.begin():
        db.add(
            SkillVisibilityRule(
                tenant_id=rt.tenant_id,
                skill_id=sid,
                effect="allow",
                principal_type="oa",
                principal_value=oa,
                created_by="test",
            )
        )


def test_visibility_rule_row_persists(rt):
    with rt.session() as db, db.begin():
        skill = db.scalar(sa.select(Skill).limit(1))
        if skill is None:
            skill = Skill(tenant_id=rt.tenant_id, name="_vis_test_skill", display_name="test")
            db.add(skill)
            db.flush()
        db.add(
            SkillVisibilityRule(
                tenant_id=rt.tenant_id,
                skill_id=skill.id,
                effect="allow",
                principal_type="oa",
                principal_value="alice",
                created_by="test",
            )
        )
    with rt.session() as db:
        n = db.scalar(sa.select(sa.func.count()).select_from(SkillVisibilityRule))
        assert n >= 1


def test_no_rules_means_visible(rt):
    from oa_agent.executor.visibility import PrincipalContext, VisibilityService

    with rt.session() as db:
        assert (
            VisibilityService.is_skill_visible(
                db,
                tenant_id=rt.tenant_id,
                skill_id=999001,
                principal=PrincipalContext(oa="alice", tags=[]),
            )
            is True
        )


def test_allow_oa_and_deny_priority(rt):
    from oa_agent.executor.visibility import PrincipalContext, VisibilityService

    with rt.session() as db, db.begin():
        skill = Skill(tenant_id=rt.tenant_id, name="_vis_prio", display_name="prio")
        db.add(skill)
        db.flush()
        sid = skill.id
        db.add(
            SkillVisibilityRule(
                tenant_id=rt.tenant_id,
                skill_id=sid,
                effect="allow",
                principal_type="oa",
                principal_value="alice",
                created_by="test",
            )
        )
        db.add(
            SkillVisibilityRule(
                tenant_id=rt.tenant_id,
                skill_id=sid,
                effect="deny",
                principal_type="oa",
                principal_value="alice",
                created_by="test",
            )
        )
    with rt.session() as db:
        assert (
            VisibilityService.is_skill_visible(
                db,
                tenant_id=rt.tenant_id,
                skill_id=sid,
                principal=PrincipalContext(oa="alice", tags=[]),
            )
            is False
        )

    with rt.session() as db, db.begin():
        skill2 = Skill(tenant_id=rt.tenant_id, name="_vis_bob_only", display_name="bob")
        db.add(skill2)
        db.flush()
        sid2 = skill2.id
        db.add(
            SkillVisibilityRule(
                tenant_id=rt.tenant_id,
                skill_id=sid2,
                effect="allow",
                principal_type="oa",
                principal_value="alice",
                created_by="test",
            )
        )
    with rt.session() as db:
        assert (
            VisibilityService.is_skill_visible(
                db,
                tenant_id=rt.tenant_id,
                skill_id=sid2,
                principal=PrincipalContext(oa="bob", tags=[]),
            )
            is False
        )


def test_tag_rule_no_hit_when_tags_empty(rt):
    from oa_agent.executor.visibility import PrincipalContext, VisibilityService

    with rt.session() as db, db.begin():
        skill = Skill(tenant_id=rt.tenant_id, name="_vis_tag", display_name="tag")
        db.add(skill)
        db.flush()
        sid = skill.id
        db.add(
            SkillVisibilityRule(
                tenant_id=rt.tenant_id,
                skill_id=sid,
                effect="allow",
                principal_type="tag",
                principal_value="finance",
                created_by="test",
            )
        )
    with rt.session() as db:
        assert (
            VisibilityService.is_skill_visible(
                db,
                tenant_id=rt.tenant_id,
                skill_id=sid,
                principal=PrincipalContext(oa="alice", tags=[]),
            )
            is False
        )


def test_wecom_welcome_text_filters_by_oa(rt):
    from oa_agent.channels import wecom

    label = "行程报销查询"
    _allow_oa_only(rt, "travel_expense_query", "alice")
    assert label in wecom.welcome_text(rt)
    assert label not in wecom.welcome_text(rt, oa="zhangsan")
    assert label in wecom.welcome_text(rt, oa="alice")


def test_skill_menu_hides_for_other_oa(chat, office, rt):
    from tests.test_chat import open_chat

    skill_name = "travel_expense_query"
    _allow_oa_only(rt, skill_name, "alice")

    zhang = chat.get("/v1/chat/session", headers=open_chat(chat))
    names = {s["name"] for s in zhang.json()["skills"]}
    assert skill_name not in names

    alice_h = open_chat(chat, oa="alice")
    alice_names = {s["name"] for s in chat.get("/v1/chat/session", headers=alice_h).json()["skills"]}
    assert skill_name in alice_names


def test_understand_candidate_excludes_hidden_skill_tools(chat, office, rt, monkeypatch):
    from tests.test_chat import LIST_URL, open_chat, send

    _allow_oa_only(rt, "travel_expense_query", "alice")
    route = office.get(LIST_URL)
    calls: list = []

    class PickTool:
        def invoke(self, messages):
            calls.append(list(messages))
            return SimpleNamespace(
                content=json.dumps(
                    {"action": "tool", "tool": "query_my_travel_expense_list", "args": {}},
                    ensure_ascii=False,
                ),
                response_metadata={"token_usage": {"prompt_tokens": 1}},
            )

    monkeypatch.setattr("oa_agent.chat.service._model", lambda rt_, config: (PickTool(), CFG))
    body = send(chat, open_chat(chat, oa="zhangsan"), "查一下报销").json()
    assert body["run_status"] == "succeeded"
    assert not route.called
    system = calls[0][0][1]
    assert "query_my_travel_expense_list" not in system


def test_admin_put_visibility_and_preview(admin_client, rt):
    skill_name = "travel_expense_query"
    put_body = {
        "reason": "限制仅财务试",
        "rules": [{"effect": "allow", "principal_type": "oa", "principal_value": "alice"}],
    }
    r = admin_client.put(f"/v1/admin/skills/{skill_name}/visibility", json=put_body)
    assert r.status_code == 200, r.text
    assert len(r.json()["rules"]) == 1
    assert r.json()["rules"][0]["principal_value"] == "alice"

    r = admin_client.get(f"/v1/admin/skills/{skill_name}/visibility")
    assert r.status_code == 200, r.text
    assert len(r.json()["rules"]) == 1

    alice_preview = admin_client.get("/v1/admin/visibility/preview", params={"oa": "alice"}).json()
    bob_preview = admin_client.get("/v1/admin/visibility/preview", params={"oa": "bob"}).json()
    assert skill_name in alice_preview["skills"]
    assert skill_name not in bob_preview["skills"]

    clear = admin_client.put(
        f"/v1/admin/skills/{skill_name}/visibility",
        json={"reason": "恢复全员可见", "rules": []},
    )
    assert clear.status_code == 200, r.text
    assert clear.json()["rules"] == []

    alice_preview2 = admin_client.get("/v1/admin/visibility/preview", params={"oa": "alice"}).json()
    bob_preview2 = admin_client.get("/v1/admin/visibility/preview", params={"oa": "bob"}).json()
    assert skill_name in alice_preview2["skills"]
    assert skill_name in bob_preview2["skills"]

    actions = [a["action"] for a in audit_rows(admin_client)]
    assert actions.count("skill.visibility.update") >= 2


def test_execute_hidden_tool_returns_not_available_no_upstream(chat, office, rt, monkeypatch):
    from oa_agent.runtime.graphs import oa_assistant as tq
    from tests.test_chat import LIST_URL, open_chat, send

    _allow_oa_only(rt, "travel_expense_query", "alice")
    route = office.get(LIST_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"list": [], "total": 0}})
    )

    def force_hidden_tool(state, ctx, tools):
        return {
            "intent": tq.TOOL,
            "tool": "query_my_travel_expense_list",
            "params": {},
            "intent_source": "test",
        }

    monkeypatch.setattr(tq, "_understand", force_hidden_tool)
    body = send(chat, open_chat(chat, oa="zhangsan"), "查一下报销").json()
    assert body["run_status"] == "failed"
    assert body["reply"]["error_code"] == "TOOL_NOT_AVAILABLE"
    assert "未对你开" in body["reply"]["content"]
    assert route.call_count == 0
