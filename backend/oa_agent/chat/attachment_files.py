"""Register employee uploads and read rows the same employee already sent."""

from __future__ import annotations

import secrets

import sqlalchemy as sa
from sqlalchemy.orm import Session

from oa_agent.chat.attachment_admit import MSG_TOO_MANY, AdmitError, admit_batch
from oa_agent.chat.attachment_store import put_upload, read_upload
from oa_agent.db.models import ExportFile
from oa_agent.errors import AppError
from oa_agent.executor.executor import ToolError
from oa_agent.executor.export_store import MSG_SAVE_FAILED, ExportStore
from oa_agent.ids import new_upload_file_id

_FILENAME_MAX = 255
_BIND_MAX = 5
_NOT_FOUND = "\u6587\u4ef6\u4e0d\u5b58\u5728"


def _missing() -> AppError:
    return AppError(404, "NOT_FOUND", _NOT_FOUND)


def save_uploads(
    db: Session,
    store: ExportStore,
    *,
    tenant_id: str,
    oa: str,
    thread_id: str,
    files: list[tuple[str, bytes]],
) -> list[dict]:
    """Admit the whole batch before any object or row is written.

    A later put_upload failure rolls back rows already added in this call.
    Objects that were already written are left in place.
    """
    try:
        admitted = admit_batch(list(files))
    except AdmitError as exc:
        raise AppError(422, "VALIDATION_ERROR", exc.message) from exc

    saved: list[dict] = []
    seen_tickets: set[str] = set()
    try:
        with db.begin():
            for item in admitted:
                storage, object_key, digest = put_upload(store, item.data)
                filename = (item.filename or "")[:_FILENAME_MAX]
                ticket = _new_ticket(db, seen_tickets)
                file_id = new_upload_file_id()
                db.add(ExportFile(
                    file_id=file_id,
                    tenant_id=tenant_id,
                    ticket=ticket,
                    oa=oa,
                    thread_id=thread_id,
                    filename=filename,
                    size_bytes=len(item.data),
                    content_type=item.content_type,
                    storage=storage,
                    object_key=object_key,
                    origin="upload",
                    sha256=digest,
                    media_kind=item.media_kind,
                    in_message=False,
                ))
                saved.append({
                    "file_id": file_id,
                    "filename": filename,
                    "size_bytes": len(item.data),
                    "media_kind": item.media_kind,
                })
    except ToolError as exc:
        raise AppError(500, exc.code, exc.user_message or exc.message or MSG_SAVE_FAILED) from exc
    return saved


def bind_uploads(
    db: Session,
    *,
    tenant_id: str,
    oa: str,
    thread_id: str,
    file_ids: list[str],
) -> None:
    """Mark this employee's unsent uploads as sent. Any miss rolls back the whole call."""
    ids = list(file_ids)
    if len(ids) > _BIND_MAX:
        raise AppError(422, "VALIDATION_ERROR", MSG_TOO_MANY)
    if not ids:
        return
    with db.begin():
        rows: list[ExportFile] = []
        for file_id in ids:
            row = _row(db, tenant_id=tenant_id, file_id=file_id)
            if not _unsent_upload(row, oa=oa, thread_id=thread_id):
                raise _missing()
            rows.append(row)
        for row in rows:
            row.in_message = True


def read_owned(
    db: Session,
    store: ExportStore,
    *,
    tenant_id: str,
    oa: str,
    file_id: str,
) -> tuple[ExportFile, bytes]:
    row = _row(db, tenant_id=tenant_id, file_id=file_id)
    if row is None or row.origin != "upload" or row.in_message is not True or row.oa != oa or not row.sha256:
        raise _missing()
    try:
        data = read_upload(store, row.storage, row.object_key, row.sha256)
    except ToolError as exc:
        if exc.code == "ATTACHMENT_CORRUPT":
            raise AppError(422, "ATTACHMENT_CORRUPT", exc.user_message or exc.message) from exc
        raise _missing() from exc
    return row, data


def _row(db: Session, *, tenant_id: str, file_id: str) -> ExportFile | None:
    return db.scalar(
        sa.select(ExportFile).where(
            ExportFile.tenant_id == tenant_id,
            ExportFile.file_id == file_id,
        )
    )


def _unsent_upload(row: ExportFile | None, *, oa: str, thread_id: str) -> bool:
    return (
        row is not None
        and row.oa == oa
        and row.thread_id == thread_id
        and row.origin == "upload"
        and row.in_message is False
    )


def _new_ticket(db: Session, seen: set[str]) -> str:
    for _ in range(8):
        ticket = secrets.token_urlsafe(18)
        if ticket in seen:
            continue
        exists = db.scalar(sa.select(ExportFile.id).where(ExportFile.ticket == ticket))
        if exists is None:
            seen.add(ticket)
            return ticket
    raise AppError(500, "INTERNAL_ERROR", MSG_SAVE_FAILED)
