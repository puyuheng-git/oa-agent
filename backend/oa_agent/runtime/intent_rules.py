"""规则意图解析：LLM 未配置或调用失败时使用（设计 §15.2）。"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

LIST, DETAIL, HELP = "list", "detail", "help"

# 行程报销话题；不含「外出申请」（那是独立工具）
_TOPIC = re.compile(r"报销|行程|差旅|出差")
_OUTING_APPLICATION = re.compile(r"外出\s*申请")
_TRAVEL_CONTEXT = re.compile(r"报销|行程|差旅|出差|请款|191")
_DETAIL = re.compile(r"详情|明细|详细|单号|编号|第?\s*(\d+)\s*号?单")
_ALL_ROWS = re.compile(r"全部|所有|全量|都显示|显示全部|全部显示")
_LIMIT_N = re.compile(r"(?:最近|前|显示|只要|看)?\s*([0-9一二两三四五六七八九十]+)\s*条")
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


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


def wants_all_rows(text: str) -> bool:
    """员工是否要求看全部/所有行（相对默认分页）。"""
    return bool(_ALL_ROWS.search(text or ""))


def parse_list_limit(text: str) -> int | None:
    """从话里解析列表条数。返回正整数、「全部」时返回 -1；未提及返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    if wants_all_rows(text):
        return -1
    m = _LIMIT_N.search(text)
    if not m:
        return None
    n = _num(m.group(1))
    if n is None or n <= 0:
        return None
    return n


def merge_relative_date_params(text: str, today: date, params: dict | None) -> dict:
    """用户话里含相对日期（上周/本月等）时，以规则解析为准覆盖模型或错误填参。"""
    merged = dict(params or {})
    rng = parse_date_range(text, today)
    if rng:
        merged["date_gte"], merged["date_lte"] = rng[0].isoformat(), rng[1].isoformat()
    return merged


def merge_list_limit_params(text: str, params: dict | None, *, max_limit: int) -> dict:
    """员工说了条数/全部时覆盖 limit；全部 → 工具允许的最大每页条数。"""
    merged = dict(params or {})
    want = parse_list_limit(text)
    if want is None:
        return merged
    cap = max(1, int(max_limit or 1))
    if want < 0:
        merged["limit"] = cap
    else:
        merged["limit"] = min(want, cap)
    return merged


def is_outing_application_query(text: str) -> bool:
    """「外出申请」且非行程报销语境 → 应走外出申请工具，不走行程报销。"""
    text = text or ""
    if not _OUTING_APPLICATION.search(text):
        return False
    return not _TRAVEL_CONTEXT.search(text)


def parse(text: str, today: date) -> dict:
    """返回 {intent, params}。params 只含模型可见字段。"""
    text = text.strip()
    # 外出申请列表 ≠ 行程报销（来源=外出）；交给 Skill/LLM 选 search_application_list
    if is_outing_application_query(text):
        return {"intent": HELP, "params": {}}

    detail = _DETAIL.search(text)
    ids = re.findall(r"(?<![\d-])(\d{1,12})(?![\d-])", text)
    if detail and ids:
        return {"intent": DETAIL, "params": {"id": int(ids[-1])}}
    if detail and _TOPIC.search(text):
        return {"intent": DETAIL, "params": {}}

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
    elif "外出" in text and _TOPIC.search(text):
        # 仅「外出」+ 报销/行程等才把 source=外出；单独「外出申请」已在上方拦截
        params["source"] = 1
    if _TOPIC.search(text) or "status" in params or "source" in params:
        return {"intent": LIST, "params": params}
    return {"intent": HELP, "params": {}}
