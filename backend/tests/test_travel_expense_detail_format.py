"""行程报销详情：可读摘要、路线格式化、对话正文（适配外置 chat UI 不展示 - 列表项）。"""

from __future__ import annotations

import httpx

from oa_agent.executor.display_format import (
    format_field_value,
    record_reply_body,
    travel_expense_detail_body,
)
from oa_agent.executor.registry import ToolRegistry
from oa_agent.runtime.graphs import oa_assistant as tq
from tests.test_chat import DETAIL_URL, ROW, chat, office, open_chat, send  # noqa: F401


def test_format_travel_route_list_as_chinese_path():
    assert format_field_value(["北京", "上海", "杭州"]) == "北京 → 上海 → 杭州"
    assert format_field_value([{"city": "南京"}, {"name": "苏州"}]) == "南京 → 苏州"


def test_travel_detail_body_has_required_lines():
    spec = ToolRegistry.load().get("query_my_travel_expense_detail")
    body = travel_expense_detail_body(
        spec,
        {
            "id": 3843,
            "status_text": "已报销",
            "total_amount": "1,200.50",
            "date": "2026-05-08",
            "transport_types_desc": "高铁",
            "travel_route": ["杭州", "宁波"],
        },
    )
    assert "单号：3843" in body
    assert "状态：已报销" in body
    assert "金额：1,200.50" in body
    assert "行程日期：2026-05-08" in body
    assert "交通：高铁" in body
    assert "路线：杭州 → 宁波" in body
    assert not body.strip().startswith("-")
    assert "[" not in body


def test_record_reply_body_not_markdown_bullets():
    spec = ToolRegistry.load().get("query_my_travel_expense_detail")
    text = record_reply_body(spec, "行程报销查询", {**ROW, "travel_route": ["A", "B"]})
    assert "单号：101" in text
    assert "- 单号" not in text


def test_detail_query_chat_body_shows_human_fields(chat, office):
    route = office.get(DETAIL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "info": {
                        **ROW,
                        "travel_route": ["北京", "上海"],
                        "transport_types_desc": "飞机",
                    }
                },
            },
        ),
    )
    body = send(chat, open_chat(chat), "查看报销单 101 的详情").json()
    content = body["reply"]["content"]
    assert "单号：101" in content
    assert "状态：未报销" in content
    assert "金额：120.00" in content
    assert "行程日期：2026-09-30" in content
    assert "交通：飞机" in content
    assert "路线：北京 → 上海" in content
    assert "查看报销单" not in content or content.count("：") >= 4
    data = body["reply"]["data"]
    assert data["summary"] == content
    assert data["item"]["travel_route"] == "北京 → 上海"
    assert "[" not in str(data["item"].get("travel_route"))
    _ = route


def test_detail_missing_id_still_asks(chat, office):
    route = office.get(DETAIL_URL)
    h = open_chat(chat)
    body = send(chat, h, "查看报销单的详情").json()
    assert body["run_status"] == "waiting_input"
    assert "单号" in body["reply"]["content"]
    assert not route.called
