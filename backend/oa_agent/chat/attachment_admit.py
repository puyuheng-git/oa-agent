from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from typing import Literal

MAX_FILES = 5
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024

MSG_TYPE = '只能上传 Excel、Word、PDF、Markdown、TXT、CSV，以及 png、jpeg、webp、gif 图片'
MSG_TOO_MANY = '一次最多 5 个文件'
MSG_TOO_LARGE = '单个文件不能超过 20MB'
MSG_EMPTY = '文件是空的'

MediaKind = Literal["image", "document"]

_EXTENSION_META: dict[str, tuple[MediaKind, str]] = {
    "png": ("image", "image/png"),
    "jpg": ("image", "image/jpeg"),
    "jpeg": ("image", "image/jpeg"),
    "gif": ("image", "image/gif"),
    "webp": ("image", "image/webp"),
    "pdf": ("document", "application/pdf"),
    "xls": ("document", "application/vnd.ms-excel"),
    "xlsx": (
        "document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "docx": (
        "document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    "csv": ("document", "text/csv"),
    "txt": ("document", "text/plain"),
    "md": ("document", "text/markdown"),
    "markdown": ("document", "text/markdown"),
}


class AdmitError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Admitted:
    filename: str
    data: bytes
    media_kind: MediaKind
    content_type: str
    extension: str


def admit_batch(files: list[tuple[str, bytes]]) -> list[Admitted]:
    if len(files) > MAX_FILES:
        raise AdmitError(MSG_TOO_MANY)

    admitted: list[Admitted] = []
    for raw_name, data in files:
        admitted.append(_admit_one(raw_name, data))
    return admitted


def _admit_one(raw_name: str, data: bytes) -> Admitted:
    filename = os.path.basename(raw_name.replace("\\", "/"))
    if not data:
        raise AdmitError(MSG_EMPTY)
    if len(data) > MAX_FILE_BYTES:
        raise AdmitError(MSG_TOO_LARGE)

    ext = _extension(filename)
    meta = _EXTENSION_META.get(ext)
    if meta is None:
        raise AdmitError(MSG_TYPE)

    media_kind, content_type = meta
    _validate_payload(ext, data)
    return Admitted(
        filename=filename,
        data=data,
        media_kind=media_kind,
        content_type=content_type,
        extension=ext,
    )


def _extension(filename: str) -> str:
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot + 1 :].lower()


def _validate_payload(ext: str, data: bytes) -> None:
    if ext == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise AdmitError(MSG_TYPE)
    elif ext in ("jpg", "jpeg"):
        if not data.startswith(b"\xff\xd8\xff"):
            raise AdmitError(MSG_TYPE)
    elif ext == "gif":
        if not (data.startswith(b"GIF87a") or data.startswith(b"GIF89a")):
            raise AdmitError(MSG_TYPE)
    elif ext == "webp":
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
            raise AdmitError(MSG_TYPE)
    elif ext == "pdf":
        if not data.startswith(b"%PDF"):
            raise AdmitError(MSG_TYPE)
    elif ext == "xls":
        if not data.startswith(b"\xd0\xcf\x11\xe0"):
            raise AdmitError(MSG_TYPE)
    elif ext == "xlsx":
        _validate_office_zip(data, "xl/")
    elif ext == "docx":
        _validate_office_zip(data, "word/")
    elif ext in ("csv", "txt", "md", "markdown"):
        _validate_text(data)
    else:
        raise AdmitError(MSG_TYPE)


def _validate_text(data: bytes) -> None:
    if b"\x00" in data:
        raise AdmitError(MSG_TYPE)
    if _try_decode(data, "utf-8"):
        return
    if _try_decode(data, "gbk"):
        return
    raise AdmitError(MSG_TYPE)


def _try_decode(data: bytes, encoding: str) -> bool:
    try:
        data.decode(encoding)
    except UnicodeDecodeError:
        return False
    return True


def _validate_office_zip(data: bytes, required_prefix: str) -> None:
    if not data.startswith(b"PK\x03\x04"):
        raise AdmitError(MSG_TYPE)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise AdmitError(MSG_TYPE)
            total = sum(info.file_size for info in infos)
            if total > MAX_ZIP_UNCOMPRESSED:
                raise AdmitError(MSG_TYPE)
            if not any(name.startswith(required_prefix) for name in names):
                raise AdmitError(MSG_TYPE)
    except AdmitError:
        raise
    except Exception:
        raise AdmitError(MSG_TYPE) from None
