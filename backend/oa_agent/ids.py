"""统一标识生成（设计 §7）。"""

from __future__ import annotations

from ulid import ULID


def _new(prefix: str) -> str:
    return f"{prefix}_{ULID()}"


def new_run_id() -> str:
    return _new("run")


def new_thread_id() -> str:
    return _new("thr")


def new_event_id() -> str:
    return _new("evt")


def new_audit_id() -> str:
    return _new("aud")


def new_request_id() -> str:
    return _new("req")


def new_task_id() -> str:
    return _new("itv")


def new_workflow_version_id() -> str:
    return _new("wfv")


def new_release_id() -> str:
    return _new("rel")


def new_message_id() -> str:
    return _new("msg")


def new_model_call_id() -> str:
    return _new("mcl")


def new_memory_id() -> str:
    return _new("mem")
