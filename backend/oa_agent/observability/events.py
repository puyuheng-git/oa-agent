"""事件采集（设计 §11）。

EventSink：进程内有界队列 + 后台线程批量写库；重试 3 次仍失败 → 落 data/event_spool/*.jsonl 并计数告警，
恢复后由后台线程补写。业务线程只做入队，永不因监控库故障而阻塞或失败。
"""

from __future__ import annotations

import itertools
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from oa_agent.db.models import Run, RunEvent
from oa_agent.db.types import utcnow
from oa_agent.ids import new_event_id
from oa_agent.observability.redact import MAX_SUMMARY, redact, redact_secrets

log = logging.getLogger(__name__)

EVENT_SUMMARY_LIMIT = 16000  # MySQL TEXT 上限 64KB，按 UTF-8 中文 3 字节留余量

RETRY_DELAYS = (0.2, 0.5, 1.0)
REPLAY_INTERVAL = 30.0
RUN_COLUMNS = {c.name for c in Run.__table__.columns} - {"id"}
EVENT_COLUMNS = {c.name for c in RunEvent.__table__.columns} - {"id"}


def _encode(row: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}


def _decode(row: dict, columns: set[str]) -> dict:
    out = {}
    for k, v in row.items():
        if k not in columns:
            continue
        if isinstance(v, str) and k.endswith("_at"):
            v = datetime.fromisoformat(v)
        out[k] = v
    return out


class EventSink:
    def __init__(self, session_factory: Callable[[], Session], spool_dir: Path, maxsize: int = 10_000,
                 batch_size: int = 200):
        self._session_factory = session_factory
        self._spool_dir = spool_dir
        self._queue: queue.Queue[dict] = queue.Queue(maxsize=maxsize)
        self._batch_size = batch_size
        self._stop = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._spool_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.write_failures = 0
        self.spooled = 0
        self.dropped = 0
        self.last_error: str | None = None
        self._last_replay = 0.0

    # ---- lifecycle ----
    def start(self) -> None:
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._loop, name="event-sink", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.flush(timeout)
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def flush(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._queue.empty() and self._idle.is_set():
                return True
            time.sleep(0.01)
        return False

    # ---- producer side ----
    def emit(self, event: dict) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            self.dropped += 1
            self.spool("event", [event])

    def spool(self, kind: str, rows: list[dict]) -> None:
        """直接落本地 spool（监控库不可用时由调用方使用）。"""
        try:
            with self._spool_lock:
                self._spool_dir.mkdir(parents=True, exist_ok=True)
                path = self._spool_dir / f"{time.strftime('%Y%m%d')}.jsonl"
                with path.open("a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps({"kind": kind, "data": _encode(row)}, ensure_ascii=False, default=str) + "\n")
            self.spooled += len(rows)
        except OSError:
            log.exception("写 event spool 失败，事件丢失 %d 条", len(rows))
            self.dropped += len(rows)

    def status(self) -> dict:
        pending = 0
        for f in self._spool_dir.glob("*.jsonl") if self._spool_dir.exists() else []:
            try:
                with f.open(encoding="utf-8") as fh:
                    pending += sum(1 for _ in fh)
            except OSError:
                pass
        degraded = pending > 0 or self.dropped > 0
        return {
            "status": "degraded" if degraded else "ok",
            "queue_size": self._queue.qsize(),
            "spool_pending": pending,
            "write_failures": self.write_failures,
            "dropped": self.dropped,
            "last_error": self.last_error,
        }

    # ---- consumer side ----
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                first = self._queue.get(timeout=0.5)
            except queue.Empty:
                self._maybe_replay()
                continue
            self._idle.clear()
            batch = [first]
            while len(batch) < self._batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._write_batch(batch)
            if self._queue.empty():
                self._idle.set()
            self._maybe_replay()

    def _write_batch(self, batch: list[dict]) -> None:
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if delay:
                time.sleep(delay)
            try:
                with self._session_factory() as db, db.begin():
                    db.execute(sa.insert(RunEvent), [_decode(e, EVENT_COLUMNS) for e in batch])
                return
            except IntegrityError:
                self._insert_one_by_one(batch)
                return
            except (SQLAlchemyError, OSError) as exc:
                self.last_error = redact(f"{type(exc).__name__}: {exc}", 300)
        self.write_failures += 1
        log.error("事件写库失败（重试 %d 次），落 spool %d 条：%s", len(RETRY_DELAYS), len(batch), self.last_error)
        self.spool("event", batch)

    def _insert_one_by_one(self, rows: list[dict]) -> None:
        for row in rows:
            try:
                with self._session_factory() as db, db.begin():
                    db.execute(sa.insert(RunEvent), [_decode(row, EVENT_COLUMNS)])
            except IntegrityError:
                pass  # event_id 已存在：重复，忽略

    def _maybe_replay(self) -> None:
        if time.monotonic() - self._last_replay < REPLAY_INTERVAL:
            return
        self._last_replay = time.monotonic()
        self.replay_spool()

    def replay_spool(self) -> int:
        """补写 spool；整文件成功才删除。返回补写条数。"""
        done = 0
        if not self._spool_dir.exists():
            return 0
        for path in sorted(self._spool_dir.glob("*.jsonl")):
            with self._spool_lock:
                work = path.with_suffix(".replaying")
                try:
                    path.replace(work)
                except OSError:
                    continue
            try:
                lines = [json.loads(line) for line in work.read_text(encoding="utf-8").splitlines() if line.strip()]
                runs = [r["data"] for r in lines if r["kind"] == "run"]
                events = [r["data"] for r in lines if r["kind"] == "event"]
                for run in runs:
                    upsert_run(self._session_factory, _decode(run, RUN_COLUMNS))
                self._insert_one_by_one(events)
                work.unlink()
                done += len(lines)
            except (SQLAlchemyError, OSError, ValueError) as exc:
                self.last_error = redact(f"补写失败 {type(exc).__name__}: {exc}", 300)
                with self._spool_lock:
                    if path.exists():  # 期间又有新数据落盘：追加回去
                        with path.open("a", encoding="utf-8") as fh:
                            fh.write(work.read_text(encoding="utf-8"))
                        work.unlink()
                    else:
                        work.replace(path)
                break
        return done


def upsert_run(session_factory: Callable[[], Session], row: dict) -> None:
    with session_factory() as db, db.begin():
        existing = db.scalar(sa.select(Run).where(Run.run_id == row["run_id"]))
        if existing is None:
            db.add(Run(**row))
        else:
            for k, v in row.items():
                setattr(existing, k, v)


# ---- per-run recorder ----

@dataclass
class RunRecorder:
    """一次运行的上下文：分配 seq、汇总计数、把事件交给 sink。"""

    run_id: str
    thread_id: str
    oa: str
    correlation_id: str
    sink: EventSink
    tool_call_count: int = 0
    model_call_count: int = 0
    usages: list[dict] = field(default_factory=list)
    model_logs: list[dict] = field(default_factory=list)  # 完整模型调用，由对话记录落库后清空
    failed_node: str | None = None
    started_at: datetime | None = None
    snapshot: dict = field(default_factory=dict)
    _seq: Any = field(default_factory=lambda: itertools.count(1))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def continue_after(self, seq: int) -> "RunRecorder":
        """给已有运行续写事件（恢复、管理操作）：seq 从库内最大值之后继续。"""
        self._seq = itertools.count(seq + 1)
        return self

    def event(self, event_type: str, *, node_name: str | None = None, status: str | None = None,
              duration_ms: int | None = None, tool_name: str | None = None, tool_version: str | None = None,
              error_code: str | None = None, error_summary: str | None = None, input_summary: Any = None,
              output_summary: Any = None, retry_count: int = 0, metadata: dict | None = None,
              operator_id: str | None = None) -> None:
        with self._lock:
            seq = next(self._seq)
        self.sink.emit({
            "event_id": new_event_id(),
            "run_id": self.run_id,
            "seq": seq,
            "event_type": event_type,
            "node_name": node_name,
            "status": status,
            "occurred_at": utcnow(),
            "duration_ms": duration_ms,
            "tool_name": tool_name,
            "tool_version": tool_version,
            "correlation_id": self.correlation_id,
            "error_code": error_code,
            "error_summary": redact_secrets(error_summary, MAX_SUMMARY) if error_summary else None,
            "input_summary": _summary(input_summary),
            "output_summary": _summary(output_summary),
            "retry_count": retry_count,
            "operator_id": operator_id,
            "metadata_json": metadata,
        })


def _summary(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return redact_secrets(text, EVENT_SUMMARY_LIMIT)
