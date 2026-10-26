"""本机 SQLite Checkpointer（单实例），保存后发 checkpoint_saved 事件。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from langgraph.checkpoint.sqlite import SqliteSaver

from oa_agent.observability.events import RunRecorder


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


def open_checkpointer(path: Path, recorder_for: Callable[[str | None], RunRecorder | None]) -> ObservedSqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = ObservedSqliteSaver(conn, recorder_for)
    saver.setup()
    return saver
