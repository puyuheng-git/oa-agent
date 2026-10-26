"""P5 验收：未校验不能发布；历史不可改；运行中版本不变；全有审计。"""

from __future__ import annotations

import httpx
import sqlalchemy as sa
from fastapi.testclient import TestClient

from oa_agent.db.models import InterventionTask, Run
from oa_agent.runtime.graphs import travel_query
from tests.conftest import audit_rows, login
from tests.test_accounts_rbac import VIEWER_PASS, _role, _user
from tests.test_chat import LIST_URL, ROW, chat, office, open_chat, runtime, send  # noqa: F401
from tests.workflow_helpers import WF, publish_config


def detail(admin) -> dict:
    r = admin.get(WF)
    assert r.status_code == 200, r.text
    return r.json()


def test_seeded_v1_release(admin):
    d = detail(admin)
    assert d["current_version"]["version_no"] == 1 and d["current_version"]["status"] == "published"
    assert d["current_version"]["content"] == travel_query.DEFAULT_CONFIG
    assert len(d["releases"]) == 1 and d["releases"][0]["release_type"] == "publish"
    assert d["draft"] is None


def test_unvalidated_cannot_publish(admin):
    content = {**travel_query.DEFAULT_CONFIG, "list_default_limit": 5}
    draft = admin.put(f"{WF}/draft", json={"content": content}).json()
    assert draft["status"] == "draft"
    r = admin.post(f"{WF}/publish", json={"content_hash": draft["content_hash"], "reason": "直接发布"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_VALIDATED"

    validated = admin.post(f"{WF}/draft/validate").json()
    assert validated["status"] == "validated"
    changed = admin.put(f"{WF}/draft", json={"content": {**content, "list_default_limit": 6}}).json()
    assert changed["status"] == "draft", "校验后修改应回到草稿"
    r = admin.post(f"{WF}/publish", json={"content_hash": changed["content_hash"], "reason": "改后发布"})
    assert r.status_code == 409

    validated = admin.post(f"{WF}/draft/validate").json()
    r = admin.post(f"{WF}/publish", json={"content_hash": "0" * 64, "reason": "哈希不符"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DRAFT_CHANGED"
    r = admin.post(f"{WF}/publish", json={"content_hash": validated["content_hash"], "reason": "正式发布"})
    assert r.status_code == 200 and r.json()["version_no"] == 2


def test_validation_errors_are_reported(admin):
    bad = {**travel_query.DEFAULT_CONFIG, "list_default_limit": 99, "skill": "nope", "extra": 1}
    admin.put(f"{WF}/draft", json={"content": bad})
    v = admin.post(f"{WF}/draft/validate").json()
    assert v["status"] == "draft" and v["validation"]["ok"] is False
    joined = "；".join(v["validation"]["errors"])
    assert "未知字段" in joined and "1～20" in joined and "skill" not in joined, "旧版 skill 字段兼容保留"
    assert any(a["action"] == "workflow.draft.validate" and a["result"] == "failed" for a in audit_rows(admin))


def test_published_history_is_immutable_and_rollback(admin):
    publish_config(admin, {"list_default_limit": 5}, "v2")
    publish_config(admin, {"list_default_limit": 7}, "v3")
    d = detail(admin)
    by_no = {v["version_no"]: v for v in d["versions"]}
    assert by_no[1]["content"]["list_default_limit"] == 10
    assert by_no[2]["content"]["list_default_limit"] == 5
    assert d["current_version"]["version_no"] == 3

    diff = admin.get(f"{WF}/diff", params={"from_no": 1, "to": "3"}).json()
    assert diff["changes"] == [{"key": "list_default_limit", "old": 10, "new": 7}]

    r = admin.post(f"{WF}/rollback", json={"version_no": 1, "reason": "v3 有问题"})
    assert r.status_code == 200 and r.json()["release_type"] == "rollback" and r.json()["version_no"] == 1
    d = detail(admin)
    assert d["current_version"]["version_no"] == 1 and len(d["releases"]) == 4
    assert admin.post(f"{WF}/rollback", json={"version_no": 1, "reason": "重复"}).status_code == 409
    assert admin.post(f"{WF}/rollback", json={"version_no": 9, "reason": "不存在"}).status_code == 404
    actions = [a["action"] for a in audit_rows(admin)]
    for action in ("workflow.draft.save", "workflow.draft.validate", "workflow.publish", "workflow.rollback"):
        assert action in actions, action


def test_runs_bind_release_and_config_takes_effect(chat, office, admin):
    office.get(LIST_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [ROW]}}))
    h = open_chat(chat)
    rel = publish_config(admin, {"help_text": "这是新的帮助文案"}, "改帮助")
    body = send(chat, h, "你好").json()
    assert body["reply"]["content"] == "这是新的帮助文案"
    with runtime(chat).session() as db:
        assert db.scalar(sa.select(Run.config_release_id).where(Run.run_id == body["run_id"])) == rel["release_id"]
    assert admin.get(f"/v1/admin/runs/{body['run_id']}").json()["config_release_id"] == rel["release_id"]


def test_running_version_unchanged_across_publish(chat, office, admin):
    """等待人工期间发布新配置：恢复仍按运行绑定的发布执行。"""
    route = office.get(LIST_URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json={
        "code": 0, "data": {"list": [ROW]}})])
    rel_a = publish_config(admin, {"on_upstream_error": "handoff", "list_default_limit": 8}, "版本A")
    h = open_chat(chat)
    body = send(chat, h, "查上周的行程报销").json()
    assert body["run_status"] == "waiting_human"
    publish_config(admin, {"on_upstream_error": "fail", "list_default_limit": 3}, "版本B")

    rt = runtime(chat)
    with rt.session() as db:
        task = db.scalar(sa.select(InterventionTask).where(InterventionTask.run_id == body["run_id"]))
        assert db.scalar(sa.select(Run.config_release_id).where(Run.run_id == body["run_id"])) == rel_a["release_id"]
    r = admin.post(f"/v1/admin/interventions/{task.task_id}/resume", json={"reason": "恢复", "version": 1})
    assert r.status_code == 200 and r.json()["run_status"] == "succeeded", r.text
    assert route.calls[-1].request.url.params["limit"] == "8"


def test_config_permissions_are_separated(admin, installed):
    for code, perms in (("cfg_edit", ["ops.config.edit"]), ("cfg_pub", ["ops.config.publish"])):
        role = _role(admin, code, perms)
        _user(admin, f"u_{code}", [role["id"]])
    editor = login(TestClient(installed.app), "u_cfg_edit", VIEWER_PASS)
    publisher = login(TestClient(installed.app), "u_cfg_pub", VIEWER_PASS)

    draft = editor.put(f"{WF}/draft", json={"content": {**travel_query.DEFAULT_CONFIG, "list_default_limit": 4}})
    assert draft.status_code == 200
    v = editor.post(f"{WF}/draft/validate").json()
    assert editor.post(f"{WF}/publish", json={"content_hash": v["content_hash"], "reason": "越权"}).status_code == 403
    assert editor.post(f"{WF}/rollback", json={"version_no": 1, "reason": "越权"}).status_code == 403
    assert publisher.put(f"{WF}/draft", json={"content": travel_query.DEFAULT_CONFIG}).status_code == 403
    assert detail(admin)["current_version"]["version_no"] == 1
    assert any(a["action"] == "access.denied" for a in audit_rows(admin))
