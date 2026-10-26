"""员工治理：权限点与 admin employees 目录 / 会话 Tab API。"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from fastapi.testclient import TestClient

from oa_agent.auth.perms import PERMISSIONS
from oa_agent.chat import threads as th
from oa_agent.db.models import ChatThread, ConversationMessage, EmployeeMemory
from oa_agent.db.types import utcnow
from oa_agent.ids import new_memory_id, new_message_id, new_run_id
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user

EMPLOYEE_PERMISSIONS = {
    "ops.employee.view": "员工治理：目录与摘要",
    "ops.employee.sensitive": "员工治理：会话原文与记忆正文（访问即审计）",
    "ops.employee.manage": "员工治理：写操作",
}

LIST_URL = "/v1/admin/employees"


def _threads_url(oa: str, suffix: str = "") -> str:
    return f"{LIST_URL}/{oa}/threads{suffix}"


def _memory_url(oa: str, suffix: str = "") -> str:
    return f"{LIST_URL}/{oa}/memory{suffix}"


def _visibility_url(oa: str, suffix: str = "") -> str:
    return f"{LIST_URL}/{oa}/visibility{suffix}"


def _patch(admin, url: str, json: dict):
    return admin.client.patch(url, json=json, headers=admin._h())


def _delete_json(admin, url: str, json: dict):
    return admin.client.request("DELETE", url, json=json, headers=admin._h())


def test_permissions_include_employee_governance_codes():
    for code, label in EMPLOYEE_PERMISSIONS.items():
        assert code in PERMISSIONS, f"missing permission {code}"
        assert PERMISSIONS[code] == label


def test_list_employees_aggregates_thread_and_memory(admin, installed):
    rt = installed.app.state.runtime
    oa = "gov_alice_g2"
    with rt.session() as db, db.begin():
        th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        th.create_thread(db, oa=oa, channel="wecom", tenant_id=rt.tenant_id)
        db.add(
            EmployeeMemory(
                memory_id=new_memory_id(),
                tenant_id=rt.tenant_id,
                oa=oa,
                kind="preference",
                text="偏好九月",
                status="active",
            )
        )
        db.add(
            EmployeeMemory(
                memory_id=new_memory_id(),
                tenant_id=rt.tenant_id,
                oa=oa,
                kind="note",
                text="已删",
                status="deleted",
            )
        )

    r = admin.get(LIST_URL, params={"q": oa})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["oa"] == oa
    assert item["thread_count"] == 2
    assert item["memory_active_count"] == 1
    assert item["last_active_at"] is not None


def test_list_employees_requires_view_permission(admin, installed):
    role = _role(admin, "emp_viewer", ["ops.employee.view"])
    empty = _role(admin, "no_emp_role", [])
    _user(admin, "emp_reader", [role["id"]])
    _user(admin, "no_emp_user", [empty["id"]])

    reader = login(TestClient(installed.app), "emp_reader", VIEWER_PASS)
    assert reader.get(LIST_URL).status_code == 200

    denied = login(TestClient(installed.app), "no_emp_user", VIEWER_PASS)
    assert denied.get(LIST_URL).status_code == 403


def test_list_employees_q_prefix_filter(admin, installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        th.create_thread(db, oa="prefix_one", channel="web", tenant_id=rt.tenant_id)
        th.create_thread(db, oa="prefix_two", channel="web", tenant_id=rt.tenant_id)
        th.create_thread(db, oa="other", channel="web", tenant_id=rt.tenant_id)

    r = admin.get(LIST_URL, params={"q": "prefix_"})
    assert r.status_code == 200, r.text
    oas = {i["oa"] for i in r.json()["items"]}
    assert oas == {"prefix_one", "prefix_two"}


def test_list_employees_includes_run_only_oa(admin, installed):
    from oa_agent.db.models import Run
    from oa_agent.ids import new_thread_id

    rt = installed.app.state.runtime
    oa = "run_only_g2"
    started = utcnow() - timedelta(hours=2)
    with rt.session() as db, db.begin():
        db.add(
            Run(
                run_id=new_run_id(),
                thread_id=new_thread_id(),
                tenant_id=rt.tenant_id,
                oa=oa,
                channel="oa_web",
                agent_id="oa_assistant",
                workflow_id="travel_query",
                workflow_version="1",
                run_status="succeeded",
                started_at=started,
                ended_at=started + timedelta(seconds=30),
            )
        )

    r = admin.get(LIST_URL, params={"q": oa})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["thread_count"] == 0


def test_admin_list_threads_includes_deleted_status(admin, installed):
    rt = installed.app.state.runtime
    oa = "g3_threads_list"
    with rt.session() as db, db.begin():
        active = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        deleted = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        th.soft_delete(db, deleted)
        active_id, deleted_id = active.thread_id, deleted.thread_id

    r = admin.get(_threads_url(oa), params={"status": "deleted"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["thread_id"] == deleted_id

    r2 = admin.get(_threads_url(oa), params={"status": "active"})
    assert r2.json()["total"] == 1
    assert r2.json()["items"][0]["thread_id"] == active_id


def test_admin_messages_requires_sensitive_permission(admin, installed):
    rt = installed.app.state.runtime
    oa = "g3_msg_perm"
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        tid = t.thread_id
        db.add(
            ConversationMessage(
                message_id=new_message_id(),
                tenant_id=rt.tenant_id,
                thread_id=tid,
                run_id=new_run_id(),
                oa=oa,
                channel="web",
                role="user",
                content="机密内容",
            )
        )

    view_role = _role(admin, "g3_view_only", ["ops.employee.view"])
    _user(admin, "g3_viewer", [view_role["id"]])
    viewer = login(TestClient(installed.app), "g3_viewer", VIEWER_PASS)
    assert viewer.get(_threads_url(oa, f"/{tid}/messages")).status_code == 403


def test_admin_messages_audited_with_sensitive_permission(admin, installed):
    rt = installed.app.state.runtime
    oa = "g3_msg_audit"
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        tid = t.thread_id
        db.add(
            ConversationMessage(
                message_id=new_message_id(),
                tenant_id=rt.tenant_id,
                thread_id=tid,
                run_id=new_run_id(),
                oa=oa,
                channel="web",
                role="user",
                content="审计测试正文",
            )
        )

    r = admin.get(_threads_url(oa, f"/{tid}/messages"))
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["content"] == "审计测试正文"
    assert any(a["action"] == "employee.sensitive.read" for a in audit_rows(admin))


def test_admin_thread_wrong_oa_path_is_404(admin, installed):
    rt = installed.app.state.runtime
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa="owner_oa", channel="web", tenant_id=rt.tenant_id)
        tid = t.thread_id

    assert admin.get(_threads_url("other_oa", f"/{tid}/messages")).status_code == 404


def test_admin_restore_thread_active_without_checkpointer_write(admin, installed, monkeypatch):
    rt = installed.app.state.runtime
    oa = "g3_restore"
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        tid = t.thread_id
        th.soft_delete(db, t)

    writes: list[str] = []
    cp = rt.engine.checkpointer
    monkeypatch.setattr(cp, "put", lambda *a, **k: writes.append("put"))
    monkeypatch.setattr(cp, "put_writes", lambda *a, **k: writes.append("put_writes"))

    r = admin.post(
        _threads_url(oa, f"/{tid}/restore"),
        json={"reason": "误删恢复", "status": "active"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    assert writes == []

    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.status == th.STATUS_ACTIVE
    assert any(a["action"] == "employee.thread.restore" for a in audit_rows(admin))


def test_admin_manage_patch_and_batch(admin, installed):
    rt = installed.app.state.runtime
    oa = "g3_manage"
    with rt.session() as db, db.begin():
        t1 = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        t2 = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        id1, id2 = t1.thread_id, t2.thread_id

    r = _patch(admin, _threads_url(oa, f"/{id1}"), {"title": "新标题", "reason": "治理修正"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "新标题"

    r2 = admin.post(
        _threads_url(oa, "/batch"),
        json={"action": "archive", "thread_ids": [id2], "reason": "批量归档"},
    )
    assert r2.status_code == 200, r.text
    assert r2.json()["count"] == 1

    with rt.session() as db:
        row2 = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == id2))
        assert row2.status == th.STATUS_ARCHIVED

    actions = {a["action"] for a in audit_rows(admin)}
    assert "employee.thread.update" in actions
    assert "employee.thread.batch" in actions


def test_admin_soft_delete_requires_manage(admin, installed):
    rt = installed.app.state.runtime
    oa = "g3_delete"
    with rt.session() as db, db.begin():
        t = th.create_thread(db, oa=oa, channel="web", tenant_id=rt.tenant_id)
        tid = t.thread_id

    r = _delete_json(admin, _threads_url(oa, f"/{tid}"), {"reason": "合规清理"})
    assert r.status_code == 200, r.text
    with rt.session() as db:
        row = db.scalar(sa.select(ChatThread).where(ChatThread.thread_id == tid))
        assert row.status == th.STATUS_DELETED


def test_admin_memory_list_hides_text_by_default(admin, installed):
    rt = installed.app.state.runtime
    oa = "g4_mem_list"
    with rt.session() as db, db.begin():
        db.add(
            EmployeeMemory(
                memory_id=new_memory_id(),
                tenant_id=rt.tenant_id,
                oa=oa,
                kind="preference",
                text="九月出差偏好",
                status="active",
            )
        )

    r = admin.get(_memory_url(oa))
    assert r.status_code == 200, r.text
    item = r.json()["items"][0]
    assert item["kind"] == "preference"
    assert item.get("text") is None


def test_admin_memory_include_text_requires_sensitive(admin, installed):
    rt = installed.app.state.runtime
    oa = "g4_mem_perm"
    with rt.session() as db, db.begin():
        db.add(
            EmployeeMemory(
                memory_id=new_memory_id(),
                tenant_id=rt.tenant_id,
                oa=oa,
                kind="note",
                text="敏感正文",
                status="active",
            )
        )

    view_role = _role(admin, "g4_view_only", ["ops.employee.view"])
    _user(admin, "g4_viewer", [view_role["id"]])
    viewer = login(TestClient(installed.app), "g4_viewer", VIEWER_PASS)
    assert viewer.get(_memory_url(oa), params={"include_text": "1"}).status_code == 403


def test_admin_memory_include_text_audited(admin, installed):
    rt = installed.app.state.runtime
    oa = "g4_mem_audit"
    with rt.session() as db, db.begin():
        db.add(
            EmployeeMemory(
                memory_id=new_memory_id(),
                tenant_id=rt.tenant_id,
                oa=oa,
                kind="note",
                text="审计记忆正文",
                status="active",
            )
        )

    r = admin.get(_memory_url(oa), params={"include_text": "1"})
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["text"] == "审计记忆正文"
    assert any(a["action"] == "employee.sensitive.read" for a in audit_rows(admin))


def test_admin_memory_patch_rejects_sensitive_id(admin, installed):
    rt = installed.app.state.runtime
    oa = "g4_mem_edit"
    mid = new_memory_id()
    with rt.session() as db, db.begin():
        db.add(
            EmployeeMemory(
                memory_id=mid,
                tenant_id=rt.tenant_id,
                oa=oa,
                kind="note",
                text="合法内容",
                status="active",
            )
        )

    r = _patch(
        admin,
        _memory_url(oa, f"/{mid}"),
        {"text": "身份证110101199001011234", "reason": "治理修正"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "MEMORY_REJECTED"


def test_admin_memory_manage_create_delete_clear_restore(admin, installed):
    rt = installed.app.state.runtime
    oa = "g4_mem_manage"
    r = admin.post(
        _memory_url(oa),
        json={"kind": "preference", "text": "管理员代写", "reason": "合规录入"},
    )
    assert r.status_code == 200, r.text
    mid = r.json()["memory_id"]
    assert r.json()["text"] == "管理员代写"

    r2 = _delete_json(admin, _memory_url(oa, f"/{mid}"), {"reason": "单条清理"})
    assert r2.status_code == 200, r.text

    with rt.session() as db:
        row = db.scalar(sa.select(EmployeeMemory).where(EmployeeMemory.memory_id == mid))
        assert row.status == "deleted"

    r3 = admin.post(_memory_url(oa, f"/{mid}/restore"), json={"reason": "误删恢复"})
    assert r3.status_code == 200, r.text
    assert r3.json()["status"] == "active"

    r4 = _delete_json(
        admin, _memory_url(oa), {"confirm": True, "reason": "一键清空测试"}
    )
    assert r4.status_code == 200, r.text
    assert r4.json()["deleted"] == 1

    actions = {a["action"] for a in audit_rows(admin)}
    assert "employee.memory.create" in actions
    assert "employee.memory.delete" in actions
    assert "employee.memory.restore" in actions
    assert "employee.memory.clear" in actions


def test_admin_visibility_deny_grant_hides_target_oa_only(admin, installed):
    skill_name = "travel_expense_query"
    oa_denied = "g5_vis_denied"
    oa_other = "g5_vis_other"

    r0 = admin.get(_visibility_url(oa_denied))
    assert r0.status_code == 200, r0.text
    assert any(s["name"] == skill_name for s in r0.json()["visible"])

    r1 = admin.post(
        _visibility_url(oa_denied, "/grants"),
        json={"skill_name": skill_name, "effect": "deny", "reason": "合规限制单人"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["inserted"] is True

    denied_preview = admin.get(_visibility_url(oa_denied)).json()
    hidden_names = {h["name"] for h in denied_preview["hidden"]}
    assert skill_name in hidden_names
    reason = next(h["reason"] for h in denied_preview["hidden"] if h["name"] == skill_name)
    assert reason == "deny"

    other_preview = admin.get(_visibility_url(oa_other)).json()
    assert skill_name in {s["name"] for s in other_preview["visible"]}
    assert skill_name not in {h["name"] for h in other_preview["hidden"]}

    r2 = _delete_json(
        admin,
        _visibility_url(oa_denied, "/grants"),
        {"skill_name": skill_name, "effect": "deny", "reason": "恢复可见"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["removed"] >= 1

    restored = admin.get(_visibility_url(oa_denied)).json()
    assert skill_name in {s["name"] for s in restored["visible"]}

    assert any(a["action"] == "employee.visibility.grant" for a in audit_rows(admin))


def test_admin_visibility_batch_grant(admin, installed):
    skill_name = "travel_expense_query"
    oa = "g5_vis_batch"
    r = admin.post(
        _visibility_url(oa, "/grants/batch"),
        json={
            "skill_names": [skill_name],
            "effect": "deny",
            "reason": "批量限制",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1
    preview = admin.get(_visibility_url(oa)).json()
    assert skill_name in {h["name"] for h in preview["hidden"]}
