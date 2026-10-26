"""运行统计口径（设计 §10）：只汇总库内真实记录，没有数据就返回 None，由前端显示「暂无数据」。

- 成功率 = succeeded / (succeeded + failed + timed_out)；cancelled、expired 单列。
- 时间范围按 started_at。
- 耗时取已结束运行的 duration_ms，缺失时用 ended_at - started_at（巡检/启动恢复写入的终态没有 duration_ms）。
- P95 样本 < 20 视为样本不足，不给出数值。
- Token 只汇总提供方原样返回的 usage；没有任何 usage 时为 None。
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.db.models import Run
from oa_agent.runtime.run_service import (
    CANCEL_REQUESTED,
    CANCELLED,
    EXPIRED,
    FAILED,
    QUEUED,
    RUNNING,
    SUCCEEDED,
    TIMED_OUT,
    WAITING_CONFIRMATION,
    WAITING_HUMAN,
)

ALL_STATUSES = (QUEUED, RUNNING, WAITING_CONFIRMATION, WAITING_HUMAN, CANCEL_REQUESTED,
                SUCCEEDED, FAILED, TIMED_OUT, CANCELLED, EXPIRED)
RATE_STATUSES = (SUCCEEDED, FAILED, TIMED_OUT)
ENDED_STATUSES = (SUCCEEDED, FAILED, TIMED_OUT, CANCELLED, EXPIRED)
IN_PROGRESS = (QUEUED, RUNNING, WAITING_CONFIRMATION, WAITING_HUMAN, CANCEL_REQUESTED)
P95_MIN_SAMPLES = 20
CHINA_TZ = timezone(timedelta(hours=8))

PROMPT_KEYS = ("prompt_tokens", "input_tokens")
COMPLETION_KEYS = ("completion_tokens", "output_tokens")


def percentile(sorted_values: list[int], p: float) -> int | None:
    """最近秩法。"""
    if not sorted_values:
        return None
    return sorted_values[max(0, math.ceil(p * len(sorted_values)) - 1)]


def run_duration_ms(run: Run) -> int | None:
    if run.duration_ms is not None:
        return run.duration_ms
    if run.ended_at and run.started_at:
        return max(0, int((run.ended_at - run.started_at).total_seconds() * 1000))
    return None


def _first(usage: dict, keys: tuple[str, ...]) -> int | None:
    for k in keys:
        if isinstance(usage.get(k), (int, float)):
            return int(usage[k])
    return None


def sum_tokens(usage_lists: list[list]) -> dict | None:
    prompt = completion = total = 0
    runs = calls = 0
    for items in usage_lists:
        counted = False
        for item in items or []:
            usage = item.get("usage") if isinstance(item, dict) else None
            if not isinstance(usage, dict):
                continue
            p, c = _first(usage, PROMPT_KEYS), _first(usage, COMPLETION_KEYS)
            t = usage.get("total_tokens")
            if p is None and c is None and not isinstance(t, (int, float)):
                continue
            prompt += p or 0
            completion += c or 0
            total += int(t) if isinstance(t, (int, float)) else (p or 0) + (c or 0)
            calls += 1
            counted = True
        runs += counted
    if not calls:
        return None
    return {"runs_with_usage": runs, "model_calls_with_usage": calls, "prompt_tokens": prompt,
            "completion_tokens": completion, "total_tokens": total}


def compute_stats(db: Session, tenant_id: str, start: datetime, end: datetime, now: datetime,
                  stuck_threshold_seconds: int, p95_min_samples: int = P95_MIN_SAMPLES) -> dict:
    rows = db.execute(
        sa.select(Run.run_status, Run.started_at, Run.last_event_at, Run.ended_at, Run.duration_ms,
                  Run.tool_call_count, Run.model_call_count, Run.usage_json)
        .where(Run.tenant_id == tenant_id, Run.started_at >= start, Run.started_at < end)
    ).all()

    by_status = {s: 0 for s in ALL_STATUSES}
    durations: list[int] = []
    daily: dict[date, Counter] = {}
    stuck_before = now - timedelta(seconds=stuck_threshold_seconds)
    stuck = tool_calls = model_calls = 0
    usages = []
    for r in rows:
        by_status[r.run_status] = by_status.get(r.run_status, 0) + 1
        tool_calls += r.tool_call_count or 0
        model_calls += r.model_call_count or 0
        if r.usage_json:
            usages.append(r.usage_json)
        if r.run_status == RUNNING and (r.last_event_at or r.started_at) < stuck_before:
            stuck += 1
        if r.run_status in ENDED_STATUSES:
            d = run_duration_ms(r)
            if d is not None:
                durations.append(d)
        day = r.started_at.astimezone(CHINA_TZ).date()
        daily.setdefault(day, Counter())[r.run_status] += 1

    denominator = sum(by_status[s] for s in RATE_STATUSES)
    durations.sort()
    return {
        "range": {"start": start, "end": end},
        "total": len(rows),
        "by_status": by_status,
        "success_rate": round(by_status[SUCCEEDED] / denominator, 4) if denominator else None,
        "rate_denominator": denominator,
        "in_progress": sum(by_status[s] for s in IN_PROGRESS),
        "suspected_stuck": stuck,
        "duration_ms": {
            "samples": len(durations),
            "p50": percentile(durations, 0.5),
            "p95": percentile(durations, 0.95) if len(durations) >= p95_min_samples else None,
            "p95_insufficient": len(durations) < p95_min_samples,
        },
        "tool_calls": tool_calls,
        "model_calls": model_calls,
        "tokens": sum_tokens(usages),
        "daily": [
            {"date": d.isoformat(), "total": sum(c.values()), **{s: c.get(s, 0) for s in (SUCCEEDED, FAILED, TIMED_OUT)}}
            for d, c in sorted(daily.items())
        ],
    }


def top_errors(db: Session, tenant_id: str, start: datetime, end: datetime, limit: int) -> list[dict]:
    base = (Run.tenant_id == tenant_id, Run.started_at >= start, Run.started_at < end, Run.error_code.is_not(None))
    groups = db.execute(
        sa.select(Run.error_code, Run.failed_node, sa.func.count().label("n"), sa.func.max(Run.started_at).label("last"))
        .where(*base)
        .group_by(Run.error_code, Run.failed_node)
        .order_by(sa.desc("n"), sa.desc("last"))
        .limit(limit)
    ).all()
    out = []
    for g in groups:
        node_cond = Run.failed_node.is_(None) if g.failed_node is None else Run.failed_node == g.failed_node
        sample = db.execute(
            sa.select(Run.run_id, Run.error_summary).where(*base, Run.error_code == g.error_code, node_cond)
            .order_by(Run.started_at.desc()).limit(1)
        ).first()
        out.append({"error_code": g.error_code, "failed_node": g.failed_node, "count": g.n, "last_at": g.last,
                    "sample_run_id": sample.run_id if sample else None,
                    "sample_summary": sample.error_summary if sample else None})
    return out
