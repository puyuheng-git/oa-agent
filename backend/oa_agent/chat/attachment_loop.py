from __future__ import annotations

import re
from dataclasses import dataclass

from oa_agent.chat.attachment_extract import Extracted, Sheet

TEXT_BUDGET = 30_000
IMAGE_BUDGET = 8
MAX_READS = 20
MAX_ROWS = 200
MAX_PAGES = 3
MAX_SLICE_CHARS = 8000

NO_MORE = "没有更多可读内容"

_DRIVE = re.compile(r"[A-Za-z]:[\\/]")
_HTTP_URL = re.compile(r"https?://", re.IGNORECASE)
_HTTP_WORD = re.compile(r"http", re.IGNORECASE)


@dataclass(frozen=True)
class LoadedFile:
    file_id: str
    filename: str
    media_kind: str
    size_bytes: int
    sha256: str
    extracted: Extracted


@dataclass(frozen=True)
class Projection:
    mode: str
    catalog_text: str
    full_text: str
    images: list[tuple[str, bytes]]


@dataclass(frozen=True)
class ReadArgs:
    file_id: str
    sheet: str | None = None
    row_offset: int = 0
    page_from: int = 0
    char_offset: int = 0


@dataclass(frozen=True)
class LoopResult:
    kind: str
    answer: str
    steps: list
    read_note: str


@dataclass(frozen=True)
class _Slice:
    text: str
    note: str


def project(files: list[LoadedFile]) -> Projection:
    catalog = "\n\n".join(_catalog_entry(item) for item in files)
    text_length = sum(len(item.extracted.text or "") for item in files)
    images = [
        (item.file_id, item.extracted.image_png)
        for item in files
        if item.extracted.image_png
    ]
    if text_length <= TEXT_BUDGET and len(images) <= IMAGE_BUDGET:
        full_text = "\n\n".join(part for part in (_full_entry(item) for item in files) if part)
        return Projection("full", catalog, full_text, images)
    return Projection("catalog", catalog, "", [])


def read_slice(file: LoadedFile, args: ReadArgs) -> str:
    extracted = file.extracted
    if extracted.unreadable:
        return extracted.unreadable
    if extracted.sheets:
        return _read_sheet(extracted.sheets, args.sheet, args.row_offset)
    if extracted.pages:
        return _read_pages(extracted.pages, args.page_from)
    return _read_text(extracted.text or "", args.char_offset)


def run_loop(files: list[LoadedFile], ask) -> LoopResult:
    projection = project(files)
    base = _base_prompt(projection)
    reads: list[_Slice] = []

    while True:
        if len(reads) >= MAX_READS:
            return _closed(reads)
        decision = ask(_compose(base, reads))
        action = str(decision.get("action") or "")
        if action == "tool" and not reads:
            return LoopResult("delegate", "", list(decision.get("steps") or []), "")
        if action == "answer":
            return LoopResult("answer", str(decision.get("answer") or ""), [], _notes(reads))
        if action != "read":
            note = _notes(reads)
            answer = str(decision.get("answer") or "").strip() or _forced(note)
            return LoopResult("answer", answer, [], note)

        reads.append(_perform(files, decision))
        if len(reads) >= MAX_READS:
            return _closed(reads)
        if reads[-1].text == NO_MORE:
            return _answer_when_exhausted(ask, base, reads)


def _scrub(text: str) -> str:
    cleaned = text.replace("object_key", "")
    cleaned = _DRIVE.sub("", cleaned)
    cleaned = _HTTP_URL.sub("", cleaned)
    return _HTTP_WORD.sub("", cleaned)


def _visible_name(filename: str) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if len(name) >= 2 and name[1] == ":":
        name = name[2:]
    return _scrub(name)


def _catalog_entry(file: LoadedFile) -> str:
    extracted = file.extracted
    lines = [
        f"文件编号：{_scrub(file.file_id)}",
        f"文件名：{_visible_name(file.filename)}",
        f"类型：{_scrub(file.media_kind)}",
        f"大小：{file.size_bytes}",
        f"哈希：{_scrub((file.sha256 or '')[:8])}",
    ]
    if extracted.unreadable:
        lines.append(extracted.unreadable)
    elif extracted.profile:
        lines.append(_scrub(extracted.profile))
    if extracted.width or extracted.height:
        lines.append(f"宽：{extracted.width}")
        lines.append(f"高：{extracted.height}")
    return "\n".join(lines)


def _full_entry(file: LoadedFile) -> str:
    text = _scrub(file.extracted.text or "")
    if text == "":
        return ""
    return f"文件编号：{_scrub(file.file_id)}\n{text}"


def _base_prompt(projection: Projection) -> str:
    parts: list[str] = []
    if projection.catalog_text:
        parts.append(projection.catalog_text)
    if projection.mode == "full" and projection.full_text:
        parts.append(projection.full_text)
    return "\n\n".join(parts)


def _as_int(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pick_sheet(sheets: list[Sheet], name: str | None) -> Sheet | None:
    if not sheets:
        return None
    if name:
        for sheet in sheets:
            if sheet.name == name:
                return sheet
        return None
    return sheets[0]


def _sheet_window(sheet: Sheet, row_offset: int) -> tuple[int, list[list[str]]] | None:
    offset = max(0, row_offset)
    if offset >= len(sheet.rows):
        return None
    return offset, sheet.rows[offset : offset + MAX_ROWS]


def _page_window(pages: list[str], page_from: int) -> tuple[int, list[str]] | None:
    start = page_from if page_from >= 1 else 1
    index = start - 1
    if index >= len(pages):
        return None
    return start, pages[index : index + MAX_PAGES]


def _read_sheet(sheets: list[Sheet], name: str | None, row_offset: int) -> str:
    sheet = _pick_sheet(sheets, name)
    if sheet is None:
        return NO_MORE
    window = _sheet_window(sheet, row_offset)
    if window is None:
        return NO_MORE
    _, rows = window
    lines = [f"表名：{sheet.name}"]
    if sheet.columns:
        lines.append("\t".join(sheet.columns))
    lines.extend("\t".join(row) for row in rows)
    return _scrub("\n".join(lines))


def _read_pages(pages: list[str], page_from: int) -> str:
    window = _page_window(pages, page_from)
    if window is None:
        return NO_MORE
    start, chunk = window
    lines: list[str] = []
    for index, page in enumerate(chunk):
        lines.append(f"第{start + index}页")
        lines.append(page)
    return _scrub("\n".join(lines))


def _read_text(text: str, char_offset: int) -> str:
    offset = max(0, char_offset)
    if offset >= len(text):
        return NO_MORE
    return _scrub(text[offset : offset + MAX_SLICE_CHARS])


def _note_for(file: LoadedFile, args: ReadArgs) -> str:
    extracted = file.extracted
    if extracted.unreadable:
        return ""
    if extracted.sheets:
        sheet = _pick_sheet(extracted.sheets, args.sheet)
        if sheet is None:
            return ""
        window = _sheet_window(sheet, args.row_offset)
        if window is None:
            return ""
        offset, rows = window
        return f"已读过：{sheet.name}，第{offset + 1}行到第{offset + len(rows)}行"
    if extracted.pages:
        window = _page_window(extracted.pages, args.page_from)
        if window is None:
            return ""
        start, chunk = window
        return f"已读过：第{start}页到第{start + len(chunk) - 1}页"
    text = extracted.text or ""
    offset = max(0, args.char_offset)
    if offset >= len(text):
        return ""
    length = min(MAX_SLICE_CHARS, len(text) - offset)
    name = _visible_name(file.filename) or _scrub(file.file_id)
    return f"已读过：{name}，第{offset + 1}字到第{offset + length}字"


def _perform(files: list[LoadedFile], decision: dict) -> _Slice:
    args = ReadArgs(
        file_id=str(decision.get("file_id") or ""),
        sheet=str(decision["sheet"]) if decision.get("sheet") else None,
        row_offset=_as_int(decision.get("row_offset")),
        page_from=_as_int(decision.get("page_from")),
        char_offset=_as_int(decision.get("char_offset")),
    )
    file = next((item for item in files if item.file_id == args.file_id), None)
    if file is None:
        return _Slice(NO_MORE, "")
    text = read_slice(file, args)
    if text == NO_MORE:
        return _Slice(NO_MORE, "")
    return _Slice(text, _scrub(_note_for(file, args)))


def _compose(base: str, reads: list[_Slice]) -> list[dict[str, str]]:
    total = sum(len(item.text) for item in reads)
    parts = [base] if base else []
    if total > TEXT_BUDGET and len(reads) > 1:
        for item in reads[:-1]:
            parts.append(item.note or item.text)
        parts.append(reads[-1].text)
    else:
        parts.extend(item.text for item in reads if item.text)
    return [{"role": "user", "content": _scrub("\n\n".join(parts))}]


def _notes(reads: list[_Slice]) -> str:
    notes: list[str] = []
    for item in reads:
        if item.note and item.note not in notes:
            notes.append(item.note)
    return "\n".join(notes)


def _forced(note: str) -> str:
    text = note.strip() or "已读过：本轮已读内容"
    return f"根据已读内容回答。{text}"


def _closed(reads: list[_Slice]) -> LoopResult:
    note = _notes(reads)
    return LoopResult("answer", _forced(note), [], note)


def _answer_when_exhausted(ask, base: str, reads: list[_Slice]) -> LoopResult:
    note = _notes(reads)
    messages = _compose(base, reads)
    messages.append(
        {
            "role": "user",
            "content": "没有更多可读内容。必须根据已读内容回答，不要再读。",
        }
    )
    decision = ask(messages)
    if decision.get("action") == "answer" and str(decision.get("answer") or "").strip():
        return LoopResult("answer", str(decision["answer"]), [], note)
    if decision.get("action") == "tool" and not any(item.text != NO_MORE for item in reads):
        return LoopResult("delegate", "", list(decision.get("steps") or []), note)
    return LoopResult("answer", _forced(note), [], note)
