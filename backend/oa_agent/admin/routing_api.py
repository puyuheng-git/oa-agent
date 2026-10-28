"""/v1/admin/routing：调用过程明细与路由统计（只读，ops.run.view）。

不伪造指标；无数据返回空列表 / 暂无数据口径由前端展示。
事件来自 agent_run_event（routing_* / tool_call_*）；不新表。
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query

from oa_agent.auth.rbac import AdminCtx, admin_read
from oa_agent.db.models import Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.errors import AppError
from oa_agent.observability.run_stats import P95_MIN_SAMPLES

router = APIRouter(prefix="/v1/admin/routing", tags=["admin-routing"])

VIEW = "ops.run.view"
MAX_RANGE = timedelta(days=92)
DEFAULT_RANGE = timedelta(hours=24)
STATS_CACHE_SECONDS = 30
ROUTING_TYPES = ("routing_start", "routing_stage", "routing_decision", "routing_clarify")
TOOL_TYPES = ("tool_call_start", "tool_call_end")

_stats_lock = threading.Lock()


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)


def _range(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    end = _aware(end) or utcnow()
    start = _aware(start) or end - DEFAULT_RANGE
    if start >= end:
        raise AppError(422, "VALIDATION_ERROR", "开始时间必须早于结束时间")
    if end - start > MAX_RANGE:
        raise AppError(422, "VALIDATION_ERROR", "时间范围不能超过 92 天")
    return start, end


def _meta(ev: RunEvent) -> dict:
    raw = ev.metadata_json
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _cache_seconds(ctx: AdminCtx) -> int:
    cfg = ctx.runtime.settings_svc.effective(ctx.db, "runtime")
    return int(cfg.get("stats_cache_seconds") if cfg.get("stats_cache_seconds") is not None
               else STATS_CACHE_SECONDS)


def _p95_min(ctx: AdminCtx) -> int:
    cfg = ctx.runtime.settings_svc.effective(ctx.db, "runtime")
    return int(cfg.get("p95_min_samples") or P95_MIN_SAMPLES)


@router.get("/runs")
def list_routing_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    run_id: str | None = None,
    oa: str | None = None,
    routing_mode: str | None = None,
    tool: str | None = None,
    skill: str | None = None,
    clarified: bool | None = None,
    fallback: bool | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    ctx: AdminCtx = Depends(admin_read(VIEW)),
):
    start, end = _range(start, end)
    tenant = ctx.runtime.tenant_id

    # 有 routing_decision 的运行（或筛选条件要求从事件反查）
    decision_q = (
        sa.select(RunEvent.run_id, RunEvent.metadata_json, RunEvent.duration_ms, RunEvent.occurred_at,
                  RunEvent.tool_name)
        .where(RunEvent.event_type == "routing_decision",
               RunEvent.occurred_at >= start, RunEvent.occurred_at < end)
    )
    decisions = ctx.db.execute(decision_q).all()

    by_run: dict[str, dict] = {}
    for rid, meta_raw, dur, occurred, tool_name in decisions:
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        if isinstance(meta_raw, str):
            try:
                meta = json.loads(meta_raw)
            except ValueError:
                meta = {}
        by_run[rid] = {
            "run_id": rid,
            "mode": meta.get("mode"),
            "action": meta.get("action"),
            "skill": meta.get("skill"),
            "tool": meta.get("tool") or tool_name,
            "fallback_from": meta.get("fallback_from"),
            "clarified": bool(meta.get("clarify")),
            "routing_duration_ms": dur,
            "decision_at": occurred,
            "stages_summary": "",
            "tool_ok": None,
            "tool_fail": None,
        }

    if not by_run and not run_id:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "empty": True}

    # clarify 事件补全
    if by_run:
        clarifies = ctx.db.scalars(
            sa.select(RunEvent.run_id).where(
                RunEvent.event_type == "routing_clarify",
                RunEvent.run_id.in_(list(by_run.keys())),
            )
        ).all()
        for rid in clarifies:
            if rid in by_run:
                by_run[rid]["clarified"] = True

    # stages 摘要
    if by_run:
        stages = ctx.db.execute(
            sa.select(RunEvent.run_id, RunEvent.metadata_json).where(
                RunEvent.event_type == "routing_stage",
                RunEvent.run_id.in_(list(by_run.keys())),
            ).order_by(RunEvent.seq)
        ).all()
        stage_map: dict[str, list[str]] = defaultdict(list)
        for rid, meta_raw in stages:
            meta = meta_raw if isinstance(meta_raw, dict) else {}
            stage = meta.get("stage") if isinstance(meta, dict) else None
            if stage and rid in by_run:
                stage_map[rid].append(str(stage))
        for rid, names in stage_map.items():
            if rid in by_run:
                by_run[rid]["stages_summary"] = " → ".join(names[:8])

        # tool_call 成败
        ends = ctx.db.execute(
            sa.select(RunEvent.run_id, RunEvent.status).where(
                RunEvent.event_type == "tool_call_end",
                RunEvent.run_id.in_(list(by_run.keys())),
            )
        ).all()
        ok_c: Counter = Counter()
        fail_c: Counter = Counter()
        for rid, status in ends:
            if status == "ok":
                ok_c[rid] += 1
            else:
                fail_c[rid] += 1
        for rid, row in by_run.items():
            row["tool_ok"] = ok_c.get(rid, 0)
            row["tool_fail"] = fail_c.get(rid, 0)

    # 关联 Run 拿 oa / started_at
    run_ids = list(by_run.keys())
    if run_id:
        run_ids = [run_id.strip()] if run_id.strip() in by_run or run_id.strip() else run_ids
        if run_id.strip() and run_id.strip() not in by_run:
            # 无 routing_decision 仍可按 run 返回空过程
            run = ctx.db.scalar(sa.select(Run).where(Run.tenant_id == tenant, Run.run_id == run_id.strip()))
            if run is None:
                return {"items": [], "total": 0, "page": page, "page_size": page_size, "empty": True}
            by_run[run.run_id] = {
                "run_id": run.run_id, "mode": None, "action": None, "skill": None, "tool": None,
                "fallback_from": None, "clarified": False, "routing_duration_ms": None,
                "decision_at": run.started_at, "stages_summary": "", "tool_ok": 0, "tool_fail": 0,
            }
            run_ids = [run.run_id]

    runs = {
        r.run_id: r for r in ctx.db.scalars(
            sa.select(Run).where(Run.tenant_id == tenant, Run.run_id.in_(run_ids or [""]))
        ).all()
    } if run_ids else {}

    items = []
    for rid, row in by_run.items():
        run = runs.get(rid)
        if run is None:
            continue
        if oa and run.oa != oa.strip():
            continue
        if routing_mode and row.get("mode") != routing_mode.strip():
            continue
        if tool and (row.get("tool") or "") != tool.strip():
            continue
        if skill and (row.get("skill") or "") != skill.strip():
            continue
        if clarified is True and not row.get("clarified"):
            continue
        if clarified is False and row.get("clarified"):
            continue
        if fallback is True and not row.get("fallback_from"):
            continue
        if fallback is False and row.get("fallback_from"):
            continue
        if run.started_at and (run.started_at < start or run.started_at >= end) and rid not in (run_id or ""):
            # 已按 decision 时间筛；此处再按 run 时间收紧可选
            pass
        items.append({
            **row,
            "oa": run.oa,
            "started_at": run.started_at,
            "run_status": run.run_status,
        })

    items.sort(key=lambda x: x.get("started_at") or datetime.min.replace(tzinfo=UTC), reverse=True)
    total = len(items)
    page_items = items[(page - 1) * page_size: page * page_size]
    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "empty": total == 0,
    }


@router.get("/runs/{run_id}")
def routing_run_detail(run_id: str, ctx: AdminCtx = Depends(admin_read(VIEW))):
    run = ctx.db.scalar(sa.select(Run).where(Run.tenant_id == ctx.runtime.tenant_id, Run.run_id == run_id))
    if run is None:
        raise AppError(404, "NOT_FOUND", "运行不存在")
    events = ctx.db.scalars(
        sa.select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
    ).all()
    routing = []
    tool_calls = []
    connectors = []
    for e in events:
        meta = _meta(e)
        base = {
            "event_id": e.event_id,
            "seq": e.seq,
            "event_type": e.event_type,
            "occurred_at": e.occurred_at,
            "duration_ms": e.duration_ms,
            "status": e.status,
            "tool_name": e.tool_name,
            "metadata": meta,
        }
        if e.event_type in ROUTING_TYPES:
            routing.append(base)
        elif e.event_type in TOOL_TYPES:
            tool_calls.append(base)
        elif e.event_type and e.event_type.startswith("connector_call"):
            connectors.append(base)

    decision = next((r for r in reversed(routing) if r["event_type"] == "routing_decision"), None)
    return {
        "run": {
            "run_id": run.run_id,
            "oa": run.oa,
            "started_at": run.started_at,
            "run_status": run.run_status,
            "thread_id": run.thread_id,
        },
        "routing_events": routing,
        "tool_call_events": tool_calls,
        "connector_events": connectors,
        "connector_status": "未使用 / 未配置" if not connectors else "有记录",
        "decision": decision,
        "empty_routing": len(routing) == 0,
    }


def _percentile(sorted_vals: list[int], p: float) -> int | None:
    if not sorted_vals:
        return None
    idx = int(round((len(sorted_vals) - 1) * p))
    return sorted_vals[max(0, min(idx, len(sorted_vals) - 1))]


@router.get("/stats")
def routing_stats(start: datetime | None = None, end: datetime | None = None,
                  ctx: AdminCtx = Depends(admin_read(VIEW))):
    start, end = _range(start, end)
    key = ("routing", ctx.runtime.tenant_id, start.replace(second=0, microsecond=0),
           end.replace(second=0, microsecond=0))
    cache_sec = _cache_seconds(ctx)
    cache = getattr(ctx.runtime, "stats_cache", None)
    if cache is None:
        cache = {}
        ctx.runtime.stats_cache = cache
    with _stats_lock:
        hit = cache.get(key)
    if hit and time.monotonic() - hit[0] < cache_sec:
        return hit[1]

    tenant = ctx.runtime.tenant_id
    # 限定租户下时间窗内的 run
    run_ids = list(ctx.db.scalars(
        sa.select(Run.run_id).where(
            Run.tenant_id == tenant, Run.started_at >= start, Run.started_at < end,
        )
    ).all())

    empty = {
        "range": {"start": start, "end": end},
        "empty": True,
        "runs_by_mode": [],
        "mode_share": [],
        "tool_calls": {"total": 0, "ok": 0, "fail": 0, "success_rate": None},
        "clarify_rate": None,
        "fallback_rate": None,
        "avg_routing_ms": None,
        "avg_tool_ms": None,
        "p95_routing_ms": None,
        "p95_tool_ms": None,
        "top_tools": [],
        "top_skills": [],
        "misselect": "未检测",
        "trace_note": None,
        "generated_at": utcnow(),
    }
    if not run_ids:
        with _stats_lock:
            if len(cache) > 256:
                cache.clear()
            cache[key] = (time.monotonic(), empty)
        return empty

    decisions = ctx.db.execute(
        sa.select(RunEvent.run_id, RunEvent.metadata_json, RunEvent.duration_ms).where(
            RunEvent.event_type == "routing_decision",
            RunEvent.run_id.in_(run_ids),
        )
    ).all()
    clarifies = set(ctx.db.scalars(
        sa.select(RunEvent.run_id).where(
            RunEvent.event_type == "routing_clarify", RunEvent.run_id.in_(run_ids),
        )
    ).all())
    tool_ends = ctx.db.execute(
        sa.select(RunEvent.tool_name, RunEvent.status, RunEvent.duration_ms).where(
            RunEvent.event_type == "tool_call_end", RunEvent.run_id.in_(run_ids),
        )
    ).all()

    mode_counter: Counter = Counter()
    fallback_n = 0
    routing_durs: list[int] = []
    skill_counter: Counter = Counter()
    for rid, meta_raw, dur in decisions:
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        mode = meta.get("mode") or "unknown"
        mode_counter[mode] += 1
        if meta.get("fallback_from"):
            fallback_n += 1
        if isinstance(dur, int):
            routing_durs.append(dur)
        sk = meta.get("skill")
        if sk:
            skill_counter[sk] += 1

    decision_runs = len(decisions)
    clarify_n = len(clarifies)

    tool_ok = tool_fail = 0
    tool_durs: list[int] = []
    tool_counter: Counter = Counter()
    for name, status, dur in tool_ends:
        if status == "ok":
            tool_ok += 1
        else:
            tool_fail += 1
        if name:
            tool_counter[name] += 1
        if isinstance(dur, int):
            tool_durs.append(dur)

    total_tools = tool_ok + tool_fail
    p95_min = _p95_min(ctx)
    routing_durs.sort()
    tool_durs.sort()

    total_modes = sum(mode_counter.values()) or 0
    runs_by_mode = [{"mode": m, "count": c} for m, c in mode_counter.most_common()]
    mode_share = [
        {"mode": m, "count": c, "share": round(c / total_modes, 4) if total_modes else None}
        for m, c in mode_counter.most_common()
    ]

    # 无 routing 事件时标注统计降级
    trace_note = None
    if decision_runs == 0 and total_tools > 0:
        trace_note = "未见 routing_* 事件（可能关闭了 routing_trace_enabled），统计仅含 tool_call_*"

    data: dict[str, Any] = {
        "range": {"start": start, "end": end},
        "empty": decision_runs == 0 and total_tools == 0,
        "runs_by_mode": runs_by_mode,
        "mode_share": mode_share,
        "tool_calls": {
            "total": total_tools,
            "ok": tool_ok,
            "fail": tool_fail,
            "success_rate": round(tool_ok / total_tools, 4) if total_tools else None,
        },
        "clarify_rate": round(clarify_n / decision_runs, 4) if decision_runs else None,
        "fallback_rate": round(fallback_n / decision_runs, 4) if decision_runs else None,
        "avg_routing_ms": int(sum(routing_durs) / len(routing_durs)) if routing_durs else None,
        "avg_tool_ms": int(sum(tool_durs) / len(tool_durs)) if tool_durs else None,
        "p95_routing_ms": _percentile(routing_durs, 0.95) if len(routing_durs) >= p95_min else None,
        "p95_tool_ms": _percentile(tool_durs, 0.95) if len(tool_durs) >= p95_min else None,
        "p95_routing_label": None if len(routing_durs) >= p95_min else ("样本不足" if routing_durs else None),
        "p95_tool_label": None if len(tool_durs) >= p95_min else ("样本不足" if tool_durs else None),
        "top_tools": [{"name": n, "count": c} for n, c in tool_counter.most_common(10)],
        "top_skills": [{"name": n, "count": c} for n, c in skill_counter.most_common(10)],
        "misselect": "未检测",
        "decision_runs": decision_runs,
        "trace_note": trace_note,
        "generated_at": utcnow(),
    }
    with _stats_lock:
        if len(cache) > 256:
            cache.clear()
        cache[key] = (time.monotonic(), data)
    return data
