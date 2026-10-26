"""测试用：走真实的 草稿 → 校验 → 发布 流程，让当前发布配置带上指定覆盖项。"""

from __future__ import annotations

WF = "/v1/admin/workflows/travel_query"


def publish_config(admin, overrides: dict, reason: str = "测试发布") -> dict:
    current = admin.get(WF).json()["current_version"]["content"]
    r = admin.put(f"{WF}/draft", json={"content": {**current, **overrides}})
    assert r.status_code == 200, r.text
    r = admin.post(f"{WF}/draft/validate")
    assert r.status_code == 200 and r.json()["status"] == "validated", r.text
    r = admin.post(f"{WF}/publish", json={"content_hash": r.json()["content_hash"], "reason": reason})
    assert r.status_code == 200, r.text
    return r.json()
