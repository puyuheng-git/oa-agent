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

# 无文字层且页面也渲不出图时的员工可见兜底（禁止把「已读过」内部备注直接当回复）
SCANNED_FALLBACK = (
    "这份附件没有可提取的文字，页面也未能渲染成图片供识读。"
    "请换可复制文字的 PDF/Word，或把关键页截成图片后再发。"
)
GENERIC_FALLBACK = (
    "我已查看附件，但没能整理出可用结论。"
    "请再具体说明要核对或提取的内容。"
)

_DRIVE = re.compile(r"[A-Za-z]:[\\/]")
_HTTP_URL = re.compile(r"https?://", re.IGNORECASE)
_HTTP_WORD = re.compile(r"http", re.IGNORECASE)
_THINK_WRAP = re.compile(r"^<think\b[^>]*>(.*?)</think\s*>\s*(.*)$", re.I | re.S)
_META_ANSWER = re.compile(
    r"(need ensure json|json valid|no markdown|builtin\.skill_exec|"
    r"action\s*[:=]\s*[\"']?(?:answer|read|tool)|let'?s settle|could use builtin)",
    re.I,
)


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


def _file_images(file: LoadedFile) -> list[tuple[str, bytes]]:
    """收集可送多模态的 PNG：扫描 PDF 的 page_images 优先，其次单图附件。"""
    extracted = file.extracted
    if extracted.page_images:
        return [
            (f"{file.file_id}#p{index + 1}", png)
            for index, png in enumerate(extracted.page_images)
            if png
        ]
    if extracted.image_png:
        return [(file.file_id, extracted.image_png)]
    return []


def project(files: list[LoadedFile]) -> Projection:
    catalog = "\n\n".join(_catalog_entry(item) for item in files)
    text_length = sum(len(item.extracted.text or "") for item in files)
    images: list[tuple[str, bytes]] = []
    for item in files:
        images.extend(_file_images(item))
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
    # 全是无正文页、又没有可识图 PNG：不必空转 read，直接说明扫描件限制
    if _files_are_scanned_without_image(files):
        return LoopResult("answer", SCANNED_FALLBACK, [], "")

    while True:
        if len(reads) >= MAX_READS:
            return _closed(reads)
        decision = ask(_compose(base, reads))
        action = str(decision.get("action") or "")
        if action == "tool" and not reads:
            return LoopResult("delegate", "", list(decision.get("steps") or []), "")
        if action == "answer":
            answer = _usable_answer(decision.get("answer"))
            note = _notes(reads)
            if answer:
                return LoopResult("answer", answer, [], note)
            return LoopResult("answer", _forced(reads), [], note)
        if action != "read":
            note = _notes(reads)
            answer = _usable_answer(decision.get("answer")) or _forced(reads)
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
    parts = [f"文件编号：{_scrub(file.file_id)}"]
    if file.extracted.page_images:
        parts.append(f"已附带{len(file.extracted.page_images)}页页面图，请直接识图阅读单据内容。")
    if text == "":
        return "\n".join(parts) if file.extracted.page_images else ""
    parts.append(text)
    return "\n".join(parts)


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


def _peel_answer(text: str) -> str:
    """去掉泄漏的 think 包裹，只留员工可见正文。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    matched = _THINK_WRAP.match(raw)
    if matched:
        return (matched.group(2) or "").strip()
    return raw


def _usable_answer(value: object) -> str:
    """过滤空串、内部备注口吻、英文 JSON 元指令，避免泄漏到聊天。"""
    text = _peel_answer(str(value or ""))
    if not text:
        return ""
    if text.startswith("根据已读内容回答"):
        return ""
    if text.startswith("已读过：") and len(text) < 80:
        return ""
    if _META_ANSWER.search(text):
        return ""
    return text


def _slice_has_extractable_text(text: str) -> bool:
    from oa_agent.chat.attachment_extract import NO_PAGE_TEXT

    body = (text or "").strip()
    if not body or body == NO_MORE:
        return False
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        # 「第N页」标题行不算正文
        if re.fullmatch(r"第\d+页", line):
            continue
        if line != NO_PAGE_TEXT:
            return True
    return False


def _reads_look_empty(reads: list[_Slice]) -> bool:
    texts = [item.text for item in reads if item.text]
    if not texts:
        return True
    return not any(_slice_has_extractable_text(text) for text in texts)


def _files_are_scanned_without_image(files: list[LoadedFile]) -> bool:
    """全部 PDF 页均为「没有可提取的文字」，且没有可送视觉的 PNG（含未渲染成功）。"""
    from oa_agent.chat.attachment_extract import NO_PAGE_TEXT

    if not files:
        return False
    saw_pages = False
    for item in files:
        extracted = item.extracted
        # 已有页面图或单图 → 交给多模态，不要短路
        if extracted.image_png or extracted.page_images:
            return False
        if extracted.unreadable:
            continue
        if extracted.sheets:
            return False
        pages = extracted.pages or []
        if pages:
            saw_pages = True
            for page in pages:
                if (page or "").strip() and (page or "").strip() != NO_PAGE_TEXT:
                    return False
            continue
        text = (extracted.text or "").strip()
        if text and text != NO_PAGE_TEXT:
            return False
    return saw_pages


def _forced(reads: list[_Slice] | None = None) -> str:
    # 只有真正读过、且读到的全是空页时，才用扫描件文案；无 read 的坏答案用通用兜底
    if reads and _reads_look_empty(reads):
        return SCANNED_FALLBACK
    return GENERIC_FALLBACK


def _closed(reads: list[_Slice]) -> LoopResult:
    note = _notes(reads)
    return LoopResult("answer", _forced(reads), [], note)


def _answer_when_exhausted(ask, base: str, reads: list[_Slice]) -> LoopResult:
    note = _notes(reads)
    messages = _compose(base, reads)
    messages.append(
        {
            "role": "user",
            "content": (
                "没有更多可读内容。必须用 action=answer 直接回复员工；"
                "若正文是「没有可提取的文字」，说明是扫描件且当前不能 OCR，不要编造识别结果，"
                "也不要把「已读过」备注写进 answer。"
            ),
        }
    )
    decision = ask(messages)
    if decision.get("action") == "answer":
        answer = _usable_answer(decision.get("answer"))
        if answer:
            return LoopResult("answer", answer, [], note)
    if decision.get("action") == "tool" and not any(item.text != NO_MORE for item in reads):
        return LoopResult("delegate", "", list(decision.get("steps") or []), note)
    return LoopResult("answer", _forced(reads), [], note)
