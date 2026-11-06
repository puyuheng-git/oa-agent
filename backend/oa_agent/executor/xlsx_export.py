"""把表格或文本写成最小的 xlsx（Office Open XML），不依赖第三方库。"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from xml.sax.saxutils import escape


def _col_name(index: int) -> str:
    name = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell(ref: str, value: object) -> str:
    text = "" if value is None else str(value)
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def build_xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    head = headers or ["内容"]
    body = rows or []
    sheet_rows = []
    all_rows = [head, *body]
    for r_index, row in enumerate(all_rows, start=1):
        cells = "".join(_cell(f"{_col_name(c)}{r_index}", value) for c, value in enumerate(row))
        sheet_rows.append(f'<row r="{r_index}">{cells}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="导出" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/></Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook)
        zf.writestr("xl/_rels/workbook.xml.rels", rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def _pairs(text: str) -> list[tuple[str, str]] | None:
    lines = [ln.strip().lstrip("-").strip() for ln in text.splitlines() if ln.strip()]
    pairs: list[tuple[str, str]] = []
    for line in lines:
        if "：" in line:
            left, right = line.split("：", 1)
        elif ":" in line and not line.lower().startswith("http"):
            left, right = line.split(":", 1)
        else:
            return None
        pairs.append((left.strip(), right.strip()))
    return pairs or None


def table_from_content(content: str) -> tuple[list[str], list[list[str]]]:
    """JSON 表格、CSV，或「字段：值」文本，都收成表头和行。"""
    raw = (content or "").strip()
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            headers = [str(h) for h in (payload.get("headers") or [])]
            rows = [[("" if cell is None else str(cell)) for cell in row] for row in payload["rows"] if isinstance(row, list)]
            if headers or rows:
                return headers or ["内容"], rows
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if lines and any("," in ln for ln in lines):
        parsed = list(csv.reader(io.StringIO(raw)))
        parsed = [row for row in parsed if any(cell.strip() for cell in row)]
        if parsed:
            return [str(c) for c in parsed[0]], [[str(c) for c in row] for row in parsed[1:]]
    pairs = _pairs(raw)
    if pairs:
        return ["字段", "内容"], [[left, right] for left, right in pairs]
    if not lines:
        return ["内容"], []
    return ["内容"], [[ln] for ln in lines]


def content_to_xlsx(content: str) -> bytes:
    headers, rows = table_from_content(content)
    return build_xlsx(headers, rows)
