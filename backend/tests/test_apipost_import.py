""""Apipost 分享链接生成 Tool 草稿：链接校验、确定性映射、身份参数注入、凭证字段排除、模型补全"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from oa_agent.executor import apipost
from oa_agent.executor.catalog import compare
from tests.conftest import audit_rows
from tests.test_chat import OFFICE, chat, make_assertion, office, send  # noqa: F401

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "apipost_contract.json").read_text(encoding="utf-8"))
SHARE = "https://docs.apipost.net/docs/detail/4852d92344b0000?target_id=4f335407bc00a"
CONTRACT_URL = f"{OFFICE}/workbench/contract/fetchunreceivedcontractlist"


def test_parse_share_url():
    assert apipost.parse_share_url(SHARE) == ("4852d92344b0000", ["4f335407bc00a"])
    for bad in ("http://docs.apipost.net/docs/detail/4852d92344b0000?target_id=4f335407bc00a",
                "https://evil.example.com/docs/detail/4852d92344b0000?target_id=4f335407bc00a",
                "https://docs.apipost.net.evil.com/docs/detail/4852d92344b0000?target_id=a1b2c3",
                "https://docs.apipost.net/docs/detail/4852d92344b0000",
                "https://docs.apipost.net/docs/password/4852d92344b0000"):
        with pytest.raises(apipost.ApipostError):
            apipost.parse_share_url(bad)


def test_draft_mapping():
    draft = apipost.to_draft(FIXTURE["data"]["list"][0])
    form = draft["form"]
    assert form["method"] == "GET" and form["path"] == "/workbench/contract/fetchunreceivedcontractlist"
    assert form["identity_params"] == {"user_id": "oa"} and "user_id" not in form["model_params"]
    assert form["query_params_field"] is None
    assert form["model_params"]["ht_bh"]["label"] == "合同编号" and form["model_params"]["ht_bh"]["required"] is True
    result = form["result"]
    assert result["kind"] == "list" and "auth_key" not in result["fields"]
    assert result["labels"]["id"] == "合同标识" and result["labels"]["kh_name"] == "客户名称"
    assert len(result["list_columns"]) == 6
    joined = "".join(draft["warnings"])
    assert "auth_key" in joined and "user_id" in joined and "必填" in joined

    post = {**FIXTURE["data"]["list"][0], "method": "POST"}
    with pytest.raises(apipost.ApipostError):
        apipost.to_draft(post)


def test_identity_params_rules():
    base = {"method": "GET", "path": "/x", "model_params": {}, "result": {"kind": "list", "fields": ["id"]}}
    assert compare(base, {**base, "identity_params": {}})[0] != "breaking", "旧版本没有该字段不算不兼"
    assert compare(base, {**base, "identity_params": {"user_id": "oa"}})[0] == "breaking"


def _fake_llm(monkeypatch, reply: dict):
    def invoke(messages):
        assert "示例客户" not in messages[1][1], "示例数据不发给模"
        return SimpleNamespace(content=json.dumps(reply, ensure_ascii=False), response_metadata={})
    monkeypatch.setattr("oa_agent.admin.catalog_api._draft_model", lambda ctx: SimpleNamespace(invoke=invoke))


def test_import_endpoint_then_save_and_chat(admin, chat, office, monkeypatch):
    office.post("https://docs.apipost.net/doc/details").mock(return_value=httpx.Response(200, json=FIXTURE))
    _fake_llm(monkeypatch, {
        "name": "query_my_unreceived_contracts", "description": "查询本人待接收的合同",
        "list_columns": ["ht_bh", "kh_name", "ht_je", "nope"],
        "params": {"ht_bh": "员工提到具体合同编号时填"},
        "skill": {"name": "contract_receive_query", "display_name": "待接收合", "description": "查询本人待接收的合同",
                  "instructions": "", "examples": ["我有哪些合同还没接收"]}})
    r = admin.post("/v1/admin/tools/import/apipost", json={"url": SHARE})
    assert r.status_code == 200, r.text
    draft = r.json()["drafts"][0]
    form = draft["form"]
    assert form["name"] == "query_my_unreceived_contracts"
    assert form["result"]["list_columns"] == ["ht_bh", "kh_name", "ht_je"]
    assert draft["skill"]["tools"] == ["query_my_unreceived_contracts"]
    assert any(a["action"] == "tool.import_draft" for a in audit_rows(admin))

    for p in ("ht_bh", "run_id"):  # 管理员检查后改为非必填
        form["model_params"][p]["required"] = False
    assert admin.post("/v1/admin/tools", json={**form, "reason": "从 Apipost 导入"}).status_code == 200
    skill = admin.post("/v1/admin/skills", json={**draft["skill"], "reason": "从 Apipost 导入"})
    assert skill.status_code == 200 and skill.json()["validation_status"] == "valid", skill.text

    route = office.get(CONTRACT_URL).mock(return_value=httpx.Response(200, json={"code": 0, "data": {"list": [
        {"id": 1, "ht_bh": "H-1", "kh_name": "客户A", "ht_je": "500", "auth_key": "secret-key"}]}}))
    model_reply = json.dumps({"tool": "query_my_unreceived_contracts", "args": {"user_id": "lisi"}})
    fake = SimpleNamespace(invoke=lambda _: SimpleNamespace(content=model_reply, response_metadata={}))
    from oa_agent.runtime.llm import ModelConfig
    monkeypatch.setattr("oa_agent.chat.service._model",
                        lambda rt, config: (fake, ModelConfig("f", "http://llm", None, 10, "m", {})))
    code = chat.post("/v1/chat/launch", json={"assertion": make_assertion()}).json()["launch_code"]
    ticket = chat.post("/v1/chat/session", json={"launch_code": code}).json()["ticket"]
    body = send(chat, {"Authorization": f"Bearer {ticket}"}, "我有哪些合同还没接收").json()
    assert body["run_status"] == "succeeded", body
    params = route.calls.last.request.url.params
    assert params["user_id"] == "zhangsan", "身份参数由服务端注入，模型给的 lisi 被覆盖"
    assert "auth_key" not in body["reply"]["data"]["items"][0]
    assert [c["label"] for c in body["reply"]["data"]["columns"]] == ["合同编号", "客户名称", "合同金额"]


def test_import_errors(admin, office):
    r = admin.post("/v1/admin/tools/import/apipost", json={"url": "https://example.com/docs/detail/abc123?target_id=x1y2"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "IMPORT_FAILED"
    office.post("https://docs.apipost.net/doc/details").mock(
        return_value=httpx.Response(200, json={"code": 10001, "msg": "文档不存"}))
    r = admin.post("/v1/admin/tools/import/apipost", json={"url": SHARE, "use_llm": False})
    assert r.status_code == 422 and "文档不存" in r.json()["error"]["message"]


def test_missing_required_params_asks_instead_of_help():
    from oa_agent.executor.catalog import SkillState
    from oa_agent.executor.registry import ToolSpec
    from oa_agent.runtime.graphs import travel_query as tq

    spec = ToolSpec(name="query_unreceived_contract_list", method="GET", path="/x", version="1", schema_hash="h",
                    risk_level="low", requires_confirmation=False, timeout_seconds=10, inject_identity_fields=(),
                    top_level_fields=(), query_params_field=None, result_kind="list", result_fields=("ht_bh",),
                    model_params={"ht_bh": {"type": "string", "required": True, "label": "合同编号"},
                                  "run_id": {"type": "string", "required": True, "label": "流水"}})
    skill = SkillState(name="contract", enabled=True, valid=True, display_name="未接收合同查",
                       tools=[spec.name])
    tools = {spec.name: (spec, skill)}

    parsed = tq._normalize_llm({"tool": spec.name, "args": {"run_id": ""}}, tools)
    assert parsed == {"intent": tq.ASK, "tool": spec.name, "params": {}, "missing": ["ht_bh", "run_id"]}
    assert tq._route(parsed) == "respond"
    ctx = SimpleNamespace(tools=lambda: tools, config={}, skills=[skill], delta=lambda: None, streamed=False,
                          num=lambda key: tq.DEFAULT_CONFIG[key])
    reply = tq.respond(parsed, ctx)["reply"]
    assert "未接收合同查" in reply["content"] and "合同编号、流水号" in reply["content"]

    full = tq._normalize_llm({"tool": spec.name, "args": {"ht_bh": "HT1", "run_id": "R1"}}, tools)
    assert full == {"intent": tq.TOOL, "tool": spec.name, "params": {"ht_bh": "HT1", "run_id": "R1"}}
