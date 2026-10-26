"""规则意图解析：LLM 未配置或调用失败时使用（设计 §15.2）。"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

LIST, DETAIL, HELP = "list", "detail", "help"

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_TOPIC = re.compile(r"报销|行程|差旅|出差|外出")
_DETAIL = re.compile(r"详情|明细|详细|单号|编号|第?\s*(\d+)\s*号?单")


def _num(text: str) -> int | None:
    if text.isdigit():
        return int(text)
    if text in _CN_NUM:
        return _CN_NUM[text]
    if len(text) == 2 and text[0] == "十":
        return 10 + _CN_NUM.get(text[1], 0)
    if len(text) == 2 and text[1] == "十":
        return _CN_NUM.get(text[0], 0) * 10
    return None


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def parse_date_range(text: str, today: date) -> tuple[date, date] | None:
    m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})\s*(?:到|至|~|-|—)\s*(\d{4}-\d{1,2}-\d{1,2})", text)
    if m:
        a, b = (date(*map(int, s.split("-"))) for s in m.groups())
        return a, b
    if "今天" in text:
        return today, today
    if "昨天" in text:
        d = today - timedelta(days=1)
        return d, d
    monday = today - timedelta(days=today.weekday())
    if "上上周" in text:
        return monday - timedelta(days=14), monday - timedelta(days=8)
    if re.search(r"上周|上星期|上个星期", text):
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if re.search(r"本周|这周|这星期|这个星期", text):
        return monday, today
    if re.search(r"上个?月", text):
        prev = today.replace(day=1) - timedelta(days=1)
        return _month_range(prev.year, prev.month)
    if re.search(r"本月|这个?月", text):
        return today.replace(day=1), today
    if "去年" in text:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if re.search(r"今年|本年", text):
        return date(today.year, 1, 1), today
    m = re.search(r"(?:最近|近|过去)\s*([0-9一二两三四五六七八九十]+)\s*(天|周|个?月)", text)
    if m:
        n = _num(m.group(1)) or 0
        unit = m.group(2)
        days = n if unit == "天" else n * 7 if unit == "周" else n * 30
        if n > 0:
            return today - timedelta(days=days - 1), today
    m = re.search(r"(?:(\d{4})年)?\s*([0-9]{1,2}|[一二三四五六七八九十]{1,2})月份?", text)
    if m:
        month = _num(m.group(2))
        year = int(m.group(1)) if m.group(1) else today.year
        if month and 1 <= month <= 12:
            return _month_range(year, month)
    return None


def parse(text: str, today: date) -> dict:
    """返回 {intent, params}。params 只含模型可见字段。"""
    text = text.strip()
    detail = _DETAIL.search(text)
    ids = re.findall(r"(?<![\d-])(\d{1,12})(?![\d-])", text)
    if detail and ids:
        return {"intent": DETAIL, "params": {"id": int(ids[-1])}}

    params: dict = {}
    rng = parse_date_range(text, today)
    if rng:
        params["date_gte"], params["date_lte"] = rng[0].isoformat(), rng[1].isoformat()
    if "未报销" in text or "没报销" in text:
        params["status"] = 0
    elif "已报销" in text:
        params["status"] = 1
    if "191" in text or "请款" in text:
        params["source"] = 2
    elif "外出" in text:
        params["source"] = 1
    if _TOPIC.search(text) or "status" in params or "source" in params:
        return {"intent": LIST, "params": params}
    return {"intent": HELP, "params": {}}
