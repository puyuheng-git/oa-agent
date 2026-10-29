"""长期记忆注入前的越权/注入短语过滤（检测委托 oa_agent.security.prompt_guard）。"""

from __future__ import annotations

from oa_agent.db.models import EmployeeMemory
from oa_agent.security.prompt_guard import FLAG_INJECTION, scan_flags


def is_blocked_memory_text(text: str) -> bool:
    if not text:
        return False
    return FLAG_INJECTION in scan_flags(text)


def filter_injection_rows(rows: list[EmployeeMemory]) -> list[EmployeeMemory]:
    """丢弃含常见注入短语的条目，再交给 format_injection。"""
    return [row for row in rows if not is_blocked_memory_text(row.text)]
