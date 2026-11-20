"""Execution Ledger：幂等/uncertain（P1）+ 租约/fencing（P4）。"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# created → reserved → running → succeeded|failed|uncertain|cancelled
STATUS_CREATED = "created"
STATUS_RESERVED = "reserved"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_UNCERTAIN = "uncertain"
STATUS_CANCELLED = "cancelled"
STATUS_MANUAL = "manual_review"

_WRITE_EFFECTS = frozenset({"write", "irreversible", "high"})

DEFAULT_LEASE_TTL_SEC = 90.0


class FenceRejected(Exception):
    """旧 Worker 持过期 fencing token 提交结果时拒绝。"""

    code = "FENCE_REJECTED"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def request_fingerprint(tool: str, args: dict[str, Any]) -> str:
    payload = json.dumps({"tool": tool, "args": args}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def new_execution_id() -> str:
    return "exec_" + secrets.token_hex(8)


def new_attempt_id() -> str:
    return "att_" + secrets.token_hex(6)


class LedgerStore:
    """租户目录下 JSON 账本：data/react_ledger/{tenant}/{execution_id}.json"""

    def __init__(self, data_dir: Path, tenant_id: str):
        self.root = Path(data_dir) / "react_ledger" / _safe(tenant_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, execution_id: str) -> Path:
        return self.root / f"{_safe(execution_id)}.json"

    def load(self, execution_id: str) -> dict[str, Any] | None:
        path = self.path(execution_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, record: dict[str, Any]) -> None:
        eid = str(record.get("execution_id") or "")
        if not eid:
            raise ValueError("execution_id required")
        path = self.path(eid)
        tmp = path.with_suffix(".tmp")
        text = json.dumps(record, ensure_ascii=False, indent=0, default=str)
        with self._lock:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)

    def find_by_fingerprint(self, *, task_id: str, fingerprint: str) -> dict[str, Any] | None:
        """同任务同指纹：优先返回已成功或 uncertain，避免盲重试。"""
        for path in self.root.glob("exec_*.json"):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if rec.get("task_id") != task_id:
                continue
            if rec.get("request_fingerprint") != fingerprint:
                continue
            if rec.get("status") in (STATUS_SUCCEEDED, STATUS_UNCERTAIN, STATUS_RUNNING, STATUS_RESERVED):
                return rec
        return None


class ExecutionLedger:
    def __init__(self, store: LedgerStore):
        self.store = store

    def reserve(
        self,
        *,
        task_id: str,
        run_id: str,
        tool: str,
        args: dict[str, Any],
        effect_type: str = "read",
        idempotent: bool = True,
    ) -> dict[str, Any]:
        """执行前预留。写操作若已有成功/进行中同指纹记录则复用，禁止新开副作用。"""
        fp = request_fingerprint(tool, args)
        existing = self.store.find_by_fingerprint(task_id=task_id, fingerprint=fp)
        if existing is not None and effect_type in _WRITE_EFFECTS:
            return existing
        if existing is not None and existing.get("status") == STATUS_SUCCEEDED:
            return existing

        eid = new_execution_id()
        aid = new_attempt_id()
        record = {
            "execution_id": eid,
            "task_id": task_id,
            "run_id": run_id,
            "tool_name": tool,
            "idempotency_key": f"{task_id}:{fp[:24]}",
            "request_fingerprint": fp,
            "status": STATUS_RESERVED,
            "effect_type": effect_type,
            "idempotent": bool(idempotent),
            "current_attempt_id": aid,
            "attempts": [{"attempt_id": aid, "attempt_number": 1, "status": STATUS_RESERVED}],
            "args_summary": _args_summary(args),
            "result_id": None,
            "error": None,
            "lease_owner": None,
            "lease_expires_at": None,
            "fencing_token": 0,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        self.store.save(record)
        return record

    def acquire_lease(
        self,
        execution_id: str,
        *,
        owner: str,
        ttl_seconds: float = DEFAULT_LEASE_TTL_SEC,
    ) -> dict[str, Any]:
        """获取执行租约并递增 fencing_token；他方未过期租约则拒绝。"""
        rec = self._require(execution_id)
        if rec.get("status") == STATUS_SUCCEEDED:
            return rec
        now = utc_now()
        expires_raw = rec.get("lease_expires_at")
        current_owner = rec.get("lease_owner")
        if current_owner and current_owner != owner and expires_raw:
            try:
                expires = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if expires > now:
                    raise FenceRejected(
                        f"lease held by {current_owner} until {expires_raw}"
                    )
            except (TypeError, ValueError):
                pass
        fencing = int(rec.get("fencing_token") or 0) + 1
        rec["lease_owner"] = owner
        rec["lease_expires_at"] = (now + timedelta(seconds=max(1.0, float(ttl_seconds)))).isoformat()
        rec["fencing_token"] = fencing
        rec["updated_at"] = utc_now_iso()
        self.store.save(rec)
        return rec

    def mark_running(self, execution_id: str, *, fencing_token: int | None = None) -> dict[str, Any]:
        rec = self._require(execution_id)
        if rec.get("status") == STATUS_SUCCEEDED:
            return rec
        if fencing_token is not None:
            self._assert_fence(rec, fencing_token)
        rec["status"] = STATUS_RUNNING
        att = _current_attempt(rec)
        if att:
            att["status"] = STATUS_RUNNING
            att["started_at"] = utc_now_iso()
        rec["updated_at"] = utc_now_iso()
        self.store.save(rec)
        return rec

    def mark_succeeded(
        self,
        execution_id: str,
        *,
        result_id: str | None = None,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        rec = self._require(execution_id)
        if fencing_token is not None:
            self._assert_fence(rec, fencing_token)
        rec["status"] = STATUS_SUCCEEDED
        rec["result_id"] = result_id
        att = _current_attempt(rec)
        if att:
            att["status"] = STATUS_SUCCEEDED
            att["finished_at"] = utc_now_iso()
        rec["lease_owner"] = None
        rec["lease_expires_at"] = None
        rec["updated_at"] = utc_now_iso()
        self.store.save(rec)
        return rec

    def mark_failed(
        self,
        execution_id: str,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        fencing_token: int | None = None,
    ) -> dict[str, Any]:
        rec = self._require(execution_id)
        if fencing_token is not None:
            self._assert_fence(rec, fencing_token)
        rec["status"] = STATUS_FAILED
        rec["error"] = {"code": code, "message": message, "retryable": retryable}
        att = _current_attempt(rec)
        if att:
            att["status"] = STATUS_FAILED
            att["error_code"] = code
            att["error_message"] = message
            att["finished_at"] = utc_now_iso()
        rec["lease_owner"] = None
        rec["lease_expires_at"] = None
        rec["updated_at"] = utc_now_iso()
        self.store.save(rec)
        return rec

    def mark_uncertain(self, execution_id: str, *, reason: str, fencing_token: int | None = None) -> dict[str, Any]:
        """超时或崩溃窗口：外部可能已成功，禁止盲重试。"""
        rec = self._require(execution_id)
        if fencing_token is not None:
            self._assert_fence(rec, fencing_token)
        if not rec.get("idempotent") or rec.get("effect_type") in _WRITE_EFFECTS:
            rec["status"] = STATUS_UNCERTAIN
        else:
            rec["status"] = STATUS_FAILED
        rec["error"] = {"code": "UNCERTAIN", "message": reason, "retryable": False}
        att = _current_attempt(rec)
        if att:
            att["status"] = rec["status"]
            att["error_code"] = "UNCERTAIN"
            att["error_message"] = reason
            att["finished_at"] = utc_now_iso()
        rec["lease_owner"] = None
        rec["lease_expires_at"] = None
        rec["updated_at"] = utc_now_iso()
        self.store.save(rec)
        return rec

    def mark_cancelled(self, execution_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
        rec = self._require(execution_id)
        if rec.get("status") in (STATUS_SUCCEEDED, STATUS_UNCERTAIN, STATUS_MANUAL):
            return rec
        rec["status"] = STATUS_CANCELLED
        rec["error"] = {"code": "CANCELLED", "message": reason, "retryable": False}
        att = _current_attempt(rec)
        if att:
            att["status"] = STATUS_CANCELLED
            att["error_code"] = "CANCELLED"
            att["error_message"] = reason
            att["finished_at"] = utc_now_iso()
        rec["lease_owner"] = None
        rec["lease_expires_at"] = None
        rec["updated_at"] = utc_now_iso()
        self.store.save(rec)
        return rec

    def should_skip_execute(self, record: dict[str, Any]) -> bool:
        """已成功或 uncertain/running 写操作：跳过实际调用，复用账本。"""
        status = record.get("status")
        if status == STATUS_SUCCEEDED:
            return True
        if status in (STATUS_UNCERTAIN, STATUS_MANUAL, STATUS_CANCELLED):
            return True
        if status == STATUS_RUNNING and record.get("effect_type") in _WRITE_EFFECTS:
            return True
        return False

    def _assert_fence(self, rec: dict[str, Any], fencing_token: int) -> None:
        current = int(rec.get("fencing_token") or 0)
        if int(fencing_token) != current:
            raise FenceRejected(
                f"stale fencing_token={fencing_token} current={current} "
                f"execution_id={rec.get('execution_id')}"
            )

    def _require(self, execution_id: str) -> dict[str, Any]:
        rec = self.store.load(execution_id)
        if rec is None:
            raise KeyError(execution_id)
        return rec


def effect_type_for_spec(spec: Any | None) -> str:
    from oa_agent.runtime.react.tool_contract import contract_for_spec

    return contract_for_spec(spec).effect_type


def _current_attempt(rec: dict[str, Any]) -> dict[str, Any] | None:
    attempts = rec.get("attempts") or []
    if not attempts:
        return None
    return attempts[-1]


def _args_summary(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in list(args.items())[:20]:
        text = str(value)
        out[key] = text if len(text) <= 120 else text[:117] + "..."
    return out


def _safe(segment: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (segment or "x"))[:80]
