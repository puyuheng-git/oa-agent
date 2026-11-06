from __future__ import annotations

import csv
import io
from dataclasses import dataclass

import openpyxl
import xlrd
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image, ImageOps
from PIL.Image import DecompressionBombError
from pypdf import PdfReader

from oa_agent.chat.attachment_admit import MSG_TYPE, AdmitError

UNREADABLE = "已加密，无法读取"
NO_PAGE_TEXT = "没有可提取的文字"
TRUNCATED = "已截断"

MAX_SIDE = 8192
MAX_PIXELS = 64_000_000
MAX_LONG_SIDE = 2048
MAX_PROFILE_CHARS = 8000

_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


@dataclass(frozen=True)
class Sheet:
    name: str
    columns: list[str]
    rows: list[list[str]]
    numeric_summary: str


@dataclass(frozen=True)
class Extracted:
    text: str
    profile: str
    sheets: list[Sheet]
    pages: list[str]
    width: int
    height: int
    image_png: bytes | None
    unreadable: str | None


def extract_upload(filename: str, data: bytes) -> Extracted:
    extension = _extension(filename)
    if extension in _IMAGE_EXTENSIONS:
        return _extract_image(data)
    if extension == "csv":
        return _extract_csv(data)
    if extension in {"md", "markdown"}:
        return _extract_markdown(data)
    if extension == "xlsx":
        return _extract_xlsx(data)
    if extension == "xls":
        return _extract_xls(data)
    if extension == "docx":
        return _extract_docx(data)
    if extension == "pdf":
        return _extract_pdf(data)
    raise AdmitError(MSG_TYPE)


def _extension(filename: str) -> str:
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[-1].lower()


def _blank(unreadable: str | None = None) -> Extracted:
    return Extracted(
        text="",
        profile="",
        sheets=[],
        pages=[],
        width=0,
        height=0,
        image_png=None,
        unreadable=unreadable,
    )


def _unreadable() -> Extracted:
    return _blank(UNREADABLE)


def _decode_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("gbk")
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _cell_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(value, "g")
    return str(value)


def _normalize_table(raw_rows: list[list[object]]) -> tuple[list[str], list[list[str]]]:
    rows = [[_cell_str(cell) for cell in raw] for raw in raw_rows]
    while rows and all(cell == "" for cell in rows[-1]):
        rows.pop()
    if not rows:
        return [], []
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return padded[0], padded[1:]


def _parse_number(raw: str) -> float | None:
    text = raw.strip()
    if not text or text.startswith("="):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_total(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return format(value, "g")


def _numeric_summary(columns: list[str], rows: list[list[str]]) -> str:
    parts: list[str] = []
    for index, name in enumerate(columns):
        numbers: list[float] = []
        numeric = True
        for row in rows:
            if index >= len(row):
                continue
            raw = row[index].strip()
            if not raw:
                continue
            value = _parse_number(raw)
            if value is None:
                numeric = False
                break
            numbers.append(value)
        if numeric and numbers:
            label = name or f"列{index + 1}"
            total = _format_total(sum(numbers))
            parts.append(f"{label} 计数 {len(numbers)} 合计 {total}")
    return "；".join(parts)


def _sheet_from_rows(name: str, raw_rows: list[list[object]]) -> Sheet:
    columns, rows = _normalize_table(raw_rows)
    return Sheet(name, columns, rows, _numeric_summary(columns, rows))


def _sheet_text(sheet: Sheet) -> str:
    header = "\t".join(sheet.columns)
    body = ["\t".join(row) for row in sheet.rows]
    lines = [sheet.name, header, *body]
    return "\n".join(line for line in lines if line != "")


def _from_sheets(sheets: list[Sheet]) -> Extracted:
    return Extracted(
        text="\n\n".join(_sheet_text(sheet) for sheet in sheets),
        profile=_fit_sheet_profile(sheets),
        sheets=sheets,
        pages=[],
        width=0,
        height=0,
        image_png=None,
        unreadable=None,
    )


def _column_text(columns: list[str], limit: int | None) -> str:
    joined = "、".join(columns)
    if limit is None or len(joined) <= limit:
        return joined
    return joined[:limit]


def _render_sheets(
    sheets: list[Sheet],
    column_limit: int | None,
    include_numeric: bool,
) -> str:
    blocks: list[str] = []
    for sheet in sheets:
        lines = [
            f"表名：{sheet.name}",
            f"列名：{_column_text(sheet.columns, column_limit)}",
            f"行数：{len(sheet.rows)}",
        ]
        if include_numeric and sheet.numeric_summary:
            lines.append(f"数值：{sheet.numeric_summary}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _fit_sheet_profile(sheets: list[Sheet]) -> str:
    full = _render_sheets(sheets, None, True)
    if len(full) <= MAX_PROFILE_CHARS:
        return full

    suffix = "\n" + TRUNCATED

    def render(limit: int) -> str:
        return _render_sheets(sheets, limit, False) + suffix

    widest = max((len("、".join(sheet.columns)) for sheet in sheets), default=0)
    if len(render(0)) > MAX_PROFILE_CHARS:
        names = "\n".join(f"表名：{sheet.name}\n行数：{len(sheet.rows)}" for sheet in sheets)
        text = names + suffix
        if len(text) <= MAX_PROFILE_CHARS:
            return text
        keep = max(0, MAX_PROFILE_CHARS - len(suffix))
        return text[:keep] + suffix

    best = 0
    low = 0
    high = widest
    while low <= high:
        mid = (low + high) // 2
        if len(render(mid)) <= MAX_PROFILE_CHARS:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return render(best)


def _cap_profile(profile: str) -> str:
    if len(profile) <= MAX_PROFILE_CHARS:
        return profile
    keep = MAX_PROFILE_CHARS - len(TRUNCATED)
    return profile[:keep] + TRUNCATED


def _extract_csv(data: bytes) -> Extracted:
    text = _decode_text(data)
    raw_rows = [list(row) for row in csv.reader(io.StringIO(text))]
    sheet = _sheet_from_rows("CSV", raw_rows)
    extracted = _from_sheets([sheet])
    return Extracted(
        text=text,
        profile=extracted.profile,
        sheets=extracted.sheets,
        pages=[],
        width=0,
        height=0,
        image_png=None,
        unreadable=None,
    )


def _extract_markdown(data: bytes) -> Extracted:
    text = _decode_text(data)
    headings = [line for line in text.splitlines() if line.startswith("#")]
    return Extracted(
        text=text,
        profile=_cap_profile("\n".join(headings)),
        sheets=[],
        pages=[],
        width=0,
        height=0,
        image_png=None,
        unreadable=None,
    )


def _extract_xlsx(data: bytes) -> Extracted:
    try:
        return _read_xlsx(data)
    except (MemoryError, AdmitError):
        raise
    except Exception:
        return _unreadable()


def _read_xlsx(data: bytes) -> Extracted:
    workbook = openpyxl.load_workbook(
        io.BytesIO(data),
        data_only=False,
        read_only=True,
    )
    try:
        sheets = [
            _sheet_from_rows(
                worksheet.title,
                [list(row) for row in worksheet.iter_rows(values_only=True)],
            )
            for worksheet in workbook.worksheets
        ]
    finally:
        workbook.close()
    return _from_sheets(sheets)


def _xls_cell(cell: xlrd.sheet.Cell, datemode: int) -> str:
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
        return ""
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "TRUE" if cell.value else "FALSE"
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return _format_total(float(cell.value))
    if cell.ctype == xlrd.XL_CELL_DATE:
        try:
            return str(xlrd.xldate_as_datetime(cell.value, datemode))
        except (ValueError, xlrd.xldate.XLDateError):
            return _format_total(float(cell.value))
    return str(cell.value)


def _extract_xls(data: bytes) -> Extracted:
    try:
        return _read_xls(data)
    except (MemoryError, AdmitError):
        raise
    except Exception:
        return _unreadable()


def _read_xls(data: bytes) -> Extracted:
    book = xlrd.open_workbook(file_contents=data)
    sheets: list[Sheet] = []
    for sheet in book.sheets():
        raw_rows: list[list[object]] = []
        for row_index in range(sheet.nrows):
            raw_rows.append(
                [
                    _xls_cell(sheet.cell(row_index, col_index), book.datemode)
                    for col_index in range(sheet.ncols)
                ]
            )
        sheets.append(_sheet_from_rows(sheet.name, raw_rows))
    return _from_sheets(sheets)


def _is_heading(paragraph: Paragraph) -> bool:
    style = paragraph.style
    name = style.name if style is not None and style.name else ""
    return name.startswith("Heading") or name.startswith("标题")


def _iter_docx_blocks(document: Document):
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _extract_docx(data: bytes) -> Extracted:
    try:
        return _read_docx(data)
    except (MemoryError, AdmitError):
        raise
    except Exception:
        return _unreadable()


def _read_docx(data: bytes) -> Extracted:
    document = Document(io.BytesIO(data))

    chunks: list[str] = []
    headings: list[str] = []
    for block in _iter_docx_blocks(document):
        if isinstance(block, Paragraph):
            chunks.append(block.text)
            if _is_heading(block) and block.text.strip():
                headings.append(block.text.strip())
        else:
            for row in block.rows:
                chunks.append("\t".join(cell.text for cell in row.cells))
    return Extracted(
        text="\n".join(chunks),
        profile=_cap_profile("\n".join(headings)),
        sheets=[],
        pages=[],
        width=0,
        height=0,
        image_png=None,
        unreadable=None,
    )


def _outline_title(item: object) -> str:
    title = None
    getter = getattr(item, "get", None)
    if callable(getter):
        title = getter("/Title")
    if not title:
        title = getattr(item, "title", None)
    if title is None:
        return ""
    return str(title).strip()


def _walk_outline(node: object) -> list[str]:
    if isinstance(node, list):
        lines: list[str] = []
        for item in node:
            lines.extend(_walk_outline(item))
        return lines
    title = _outline_title(node)
    return [title] if title else []


def _extract_pdf(data: bytes) -> Extracted:
    try:
        return _read_pdf(data)
    except (MemoryError, AdmitError):
        raise
    except Exception:
        return _unreadable()


def _read_pdf(data: bytes) -> Extracted:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except Exception:
            return _unreadable()
        if not opened:
            return _unreadable()

    pages: list[str] = []
    for page in reader.pages:
        raw = page.extract_text() or ""
        pages.append(raw if raw.strip() else NO_PAGE_TEXT)

    outline_lines: list[str] = []
    try:
        outline_lines = _walk_outline(reader.outline)
    except Exception:
        outline_lines = []
    profile_lines = [f"页数：{len(pages)}"]
    if outline_lines:
        profile_lines.append("目录：")
        profile_lines.extend(outline_lines)
    return Extracted(
        text="\n".join(pages),
        profile=_cap_profile("\n".join(profile_lines)),
        sheets=[],
        pages=pages,
        width=0,
        height=0,
        image_png=None,
        unreadable=None,
    )


def _has_alpha(image: Image.Image) -> bool:
    if image.mode in {"RGBA", "LA"}:
        return True
    return image.mode == "P" and "transparency" in image.info


def _extract_image(data: bytes) -> Extracted:
    try:
        return _normalize_image(data)
    except DecompressionBombError:
        raise AdmitError(MSG_TYPE) from None


def _image_exceeds_limit(width: int, height: int) -> bool:
    return width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS


def _normalize_image(data: bytes) -> Extracted:
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if _image_exceeds_limit(width, height):
            raise AdmitError(MSG_TYPE)
        if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1:
            image.seek(0)
            width, height = image.size
            if _image_exceeds_limit(width, height):
                raise AdmitError(MSG_TYPE)
        oriented = ImageOps.exif_transpose(image)
        if oriented is None:
            oriented = image
        width, height = oriented.size
        if _image_exceeds_limit(width, height):
            raise AdmitError(MSG_TYPE)
        long_side = max(width, height)
        if long_side > MAX_LONG_SIDE:
            scale = MAX_LONG_SIDE / long_side
            width = max(1, round(width * scale))
            height = max(1, round(height * scale))
            oriented = oriented.resize((width, height), Image.Resampling.LANCZOS)
        colored = oriented.convert("RGBA" if _has_alpha(oriented) else "RGB")
        buffer = io.BytesIO()
        colored.save(buffer, format="PNG")
        png = buffer.getvalue()
    return Extracted(
        text="",
        profile=f"宽：{width}\n高：{height}",
        sheets=[],
        pages=[],
        width=width,
        height=height,
        image_png=png,
        unreadable=None,
    )
