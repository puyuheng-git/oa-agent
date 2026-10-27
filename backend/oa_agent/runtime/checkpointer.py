"""Checkpointer：默认 SQLite；可通过环境变量切换 Postgres（未配置或失败时回退 SQLite）。"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Callable

from langgraph.checkpoint.sqlite import SqliteSaver

from oa_agent.observability.events import RunRecorder

log = logging.getLogger(__name__)

CHECKPOINT_BACKEND_ENV = "OA_AGENT_CHECKPOINT_BACKEND"
CHECKPOINT_URL_ENV = "OA_AGENT_CHECKPOINT_URL"


class ObservedSqliteSaver(SqliteSaver):
    def __init__(self, conn: sqlite3.Connection, recorder_for: Callable[[str | None], RunRecorder | None]):
        super().__init__(conn)
        self._recorder_for = recorder_for

    def put(self, config, checkpoint, metadata, new_versions):
        result = super().put(config, checkpoint, metadata, new_versions)
        rec = self._recorder_for((config.get("configurable") or {}).get("run_id"))
        if rec is not None:
            rec.event("checkpoint_saved", metadata={"checkpoint_id": checkpoint.get("id"),
                                                    "step": (metadata or {}).get("step")})
        return result


def _open_sqlite(path: Path, recorder_for: Callable[[str | None], RunRecorder | None]) -> ObservedSqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = ObservedSqliteSaver(conn, recorder_for)
    saver.setup()
    return saver


def _open_postgres(url: str, recorder_for: Callable[[str | None], RunRecorder | None]):
    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError("未安装 Postgres checkpointer 依赖") from exc
    saver = PostgresSaver.from_conn_string(url)
    saver.setup()
    return saver


def open_checkpointer(path: Path, recorder_for: Callable[[str | None], RunRecorder | None]):
    backend = (os.environ.get(CHECKPOINT_BACKEND_ENV) or "sqlite").strip().lower()
    if backend == "postgres":
        url = (os.environ.get(CHECKPOINT_URL_ENV) or "").strip()
        if not url:
            log.warning(
                "%s=postgres 但未设置 %s，回退 SQLite",
                CHECKPOINT_BACKEND_ENV,
                CHECKPOINT_URL_ENV,
            )
        else:
            try:
                log.info("使用 Postgres checkpointer")
                return _open_postgres(url, recorder_for)
            except Exception as exc:  # noqa: BLE001 —— 连接/依赖失败时回退
                log.warning(
                    "Postgres checkpointer 不可用（%s），回退 SQLite：%s",
                    type(exc).__name__,
                    exc,
                )
    return _open_sqlite(path, recorder_for)
