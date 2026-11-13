import io
import struct
import zlib

import pytest
from docx import Document
from openpyxl import Workbook
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from oa_agent.chat.attachment_admit import AdmitError
from oa_agent.chat.attachment_extract import extract_upload

MSG_TYPE = "\u53ea\u80fd\u4e0a\u4f20 Excel\u3001Word\u3001PDF\u3001Markdown\u3001TXT\u3001CSV\uff0c\u4ee5\u53ca png\u3001jpeg\u3001webp\u3001gif \u56fe\u7247"
UNREADABLE = "\u5df2\u52a0\u5bc6\uff0c\u65e0\u6cd5\u8bfb\u53d6"
NO_PAGE_TEXT = "\u6ca1\u6709\u53ef\u63d0\u53d6\u7684\u6587\u5b57"


def _png(width: int, height: int, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_bytes(writer: PdfWriter) -> bytes:
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _pdf_with_text(text: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    page = writer.pages[0]

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type0"),
            NameObject("/BaseFont"): NameObject("/STSong-Light"),
            NameObject("/Encoding"): NameObject("/Identity-H"),
        }
    )
    font_ref = writer._add_object(font)
    encoded = text.encode("utf-16-be").hex().upper()
    content = f"BT /F1 18 Tf 72 720 Td <{encoded}> Tj ET".encode("ascii")
    stream = DecodedStreamObject()
    stream.set_data(content)
    contents_ref = writer._add_object(stream)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    page[NameObject("/Contents")] = contents_ref
    return _pdf_bytes(writer)


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    return _pdf_bytes(writer)


def _workbook_bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_csv_text_contains_both_lines_and_profile_has_columns():
    result = extract_upload("rows.csv", "a,b\n1,2\n".encode("utf-8"))
    assert "a,b" in result.text
    assert "1,2" in result.text
    assert "a" in result.profile
    assert "b" in result.profile
    assert "\u884c\u6570\uff1a1" in result.profile


def test_gbk_csv_decodes_and_counts_rows():
    raw = "\u59d3\u540d,\u57ce\u5e02\n\u5f20\u4e09,\u5317\u4eac\n".encode("gbk")
    result = extract_upload("people.csv", raw)
    assert "\u5f20\u4e09" in result.text
    assert "\u59d3\u540d" in result.profile
    assert "\u57ce\u5e02" in result.profile
    assert "\u884c\u6570\uff1a1" in result.profile


def test_markdown_text_is_full_and_profile_keeps_headings():
    body = "# \u6807\u9898\n\n\u4f60\u597d\n## \u7b2c\u4e8c\u8282\n\u5185\u5bb9\n"
    result = extract_upload("note.md", body.encode("utf-8"))
    assert result.text == body
    assert "# \u6807\u9898" in result.profile
    assert "## \u7b2c\u4e8c\u8282" in result.profile
    assert "\u4f60\u597d" not in result.profile
    assert "\u5185\u5bb9" not in result.profile


def test_xlsx_profile_has_both_sheet_names_and_row_counts():
    wb = Workbook()
    income = wb.active
    income.title = "\u6536\u5165"
    income.append(["\u6708\u4efd", "\u91d1\u989d"])
    income.append(["\u4e00\u6708", 10])
    income.append(["\u4e8c\u6708", 20])
    expense = wb.create_sheet("\u652f\u51fa")
    expense.append(["\u6708\u4efd", "\u91d1\u989d"])
    expense.append(["\u4e00\u6708", 3])

    result = extract_upload("book.xlsx", _workbook_bytes(wb))

    assert "\u6536\u5165" in result.profile
    assert "\u652f\u51fa" in result.profile
    assert "\u884c\u6570\uff1a2" in result.profile
    assert "\u884c\u6570\uff1a1" in result.profile
    income_sheet = next(sheet for sheet in result.sheets if sheet.name == "\u6536\u5165")
    assert income_sheet.columns == ["\u6708\u4efd", "\u91d1\u989d"]
    assert income_sheet.rows == [["\u4e00\u6708", "10"], ["\u4e8c\u6708", "20"]]
    assert "\u8ba1\u6570 2" in income_sheet.numeric_summary
    assert "\u5408\u8ba1 30" in income_sheet.numeric_summary
    assert "\u6708\u4efd" not in income_sheet.numeric_summary
    expense_sheet = next(sheet for sheet in result.sheets if sheet.name == "\u652f\u51fa")
    assert expense_sheet.rows == [["\u4e00\u6708", "3"]]


def test_xlsx_keeps_formula_text():
    wb = Workbook()
    ws = wb.active
    ws.title = "\u8ba1\u7b97"
    ws["A1"] = "\u503c"
    ws["B1"] = "\u516c\u5f0f"
    ws["A2"] = 10
    ws["B2"] = "=A1+1"

    result = extract_upload("formula.xlsx", _workbook_bytes(wb))
    sheet = result.sheets[0]
    assert sheet.rows == [["10", "=A1+1"]]
    assert "11" not in sheet.rows[0][1]


def test_profile_over_8000_keeps_names_row_counts_and_marks_truncated():
    wb = Workbook()
    wide = wb.active
    wide.title = "\u7532\u8868"
    long_cols = [f"\u5217{i:04d}" + ("\u540d" * 50) for i in range(180)]
    wide.append(long_cols)
    wide.append(["1"] * len(long_cols))
    short = wb.create_sheet("\u4e59\u8868")
    short.append(["\u53ea\u6709\u4e00\u5217"])
    short.append(["x"])
    short.append(["y"])

    result = extract_upload("wide.xlsx", _workbook_bytes(wb))

    assert "\u7532\u8868" in result.profile
    assert "\u4e59\u8868" in result.profile
    assert "\u884c\u6570\uff1a1" in result.profile
    assert "\u884c\u6570\uff1a2" in result.profile
    assert result.profile.endswith("\u5df2\u622a\u65ad")
    assert len(result.profile) <= 8000
    assert long_cols[-1] not in result.profile


def test_text_only_sheet_has_empty_numeric_summary():
    wb = Workbook()
    ws = wb.active
    ws.title = "\u540d\u5355"
    ws.append(["\u59d3\u540d"])
    ws.append(["\u5f20\u4e09"])
    result = extract_upload("names.xlsx", _workbook_bytes(wb))
    assert result.sheets[0].numeric_summary == ""


def test_pdf_page_contains_contract_text():
    result = extract_upload("contract.pdf", _pdf_with_text("\u5408\u540c\u6b63\u6587"))
    assert any("\u5408\u540c\u6b63\u6587" in page for page in result.pages)


def test_blank_pdf_page_says_no_extractable_text():
    result = extract_upload("scan.pdf", _blank_pdf())
    assert result.pages == [NO_PAGE_TEXT]


def test_pdf_outline_goes_into_profile():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    writer.add_outline_item("\u7b2c\u4e00\u7ae0", 0)
    result = extract_upload("toc.pdf", _pdf_bytes(writer))
    assert "\u7b2c\u4e00\u7ae0" in result.profile
    assert "\u9875\u6570\uff1a1" in result.profile


def test_encrypted_pdf_is_unreadable_without_raising():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    result = extract_upload("locked.pdf", _pdf_bytes(writer))
    assert result.unreadable == UNREADABLE


def test_docx_paragraphs_tables_and_headings():
    doc = Document()
    doc.add_heading("\u7b2c\u4e00\u7ae0", level=1)
    doc.add_paragraph("\u6b63\u6587\u6bb5\u843d")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "\u7532"
    table.cell(0, 1).text = "\u4e59"
    buf = io.BytesIO()
    doc.save(buf)

    result = extract_upload("note.docx", buf.getvalue())

    assert "\u7b2c\u4e00\u7ae0" in result.profile
    assert "\u6b63\u6587\u6bb5\u843d" not in result.profile
    assert "\u6b63\u6587\u6bb5\u843d" in result.text
    assert "\u7532" in result.text
    assert "\u4e59" in result.text


def test_png_1x1_yields_png_and_width():
    result = extract_upload("dot.png", _png(1, 1))
    assert result.image_png
    assert result.image_png.startswith(b"\x89PNG")
    assert result.width == 1
    assert result.height == 1
    assert result.unreadable is None


def test_long_edge_2048_is_not_shrunk():
    result = extract_upload("edge.png", _png(2048, 10, (1, 2, 3)))
    assert result.width == 2048
    assert result.height == 10


def test_long_edge_over_2048_shrinks_to_2048():
    result = extract_upload("photo.png", _png(3000, 1500, (1, 2, 3)))
    assert result.width == 2048
    assert result.height == 1024


def test_edge_8192_is_accepted():
    result = extract_upload("limit.png", _png(8192, 1))
    assert result.width == 2048
    assert result.height == 1


def test_edge_9000_raises_type_message():
    with pytest.raises(AdmitError) as exc_info:
        extract_upload("too-wide.png", _png(9000, 1))
    assert str(exc_info.value) == MSG_TYPE


def test_gif_uses_first_frame_only():
    first = Image.new("RGB", (2, 2), (255, 0, 0))
    second = Image.new("RGB", (2, 2), (0, 0, 255))
    buf = io.BytesIO()
    first.save(
        buf,
        format="GIF",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    result = extract_upload("anim.gif", buf.getvalue())
    out = Image.open(io.BytesIO(result.image_png))
    assert out.getpixel((0, 0))[:3] == (255, 0, 0)
    assert result.width == 2
    assert result.height == 2


def test_broken_xlsx_is_unreadable_without_raising():
    result = extract_upload("secret.xlsx", b"PK\x03\x04not-a-real-zip")
    assert result.unreadable == UNREADABLE
    assert "BadZip" not in (result.unreadable or "")
    assert "Error" not in (result.unreadable or "")
    assert result.sheets == []


def _png_header(width: int, height: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def test_pixel_count_over_64_million_rejects_from_header():
    data = _png_header(8001, 8001)
    assert len(data) < 100
    assert 8001 <= 8192
    assert 8001 * 8001 > 64_000_000
    with pytest.raises(AdmitError) as exc_info:
        extract_upload("huge.png", data)
    assert str(exc_info.value) == MSG_TYPE


def _biff_record(opcode: int, payload: bytes) -> bytes:
    return struct.pack("<HH", opcode, len(payload)) + payload


def _biff_bof(stream_type: int) -> bytes:
    payload = struct.pack("<HHHH", 0x0600, stream_type, 0x0DBB, 1996) + b"\x00" * 8
    return _biff_record(0x0809, payload)


def _biff_boundsheet(offset: int, name: bytes = b"S") -> bytes:
    payload = struct.pack("<iBB", offset, 0, 0) + bytes([len(name), 0]) + name
    return _biff_record(0x0085, payload)


def _minimal_xls() -> bytes:
    empty_sheet = _biff_boundsheet(0)
    sheet_at = len(_biff_bof(0x0005)) + len(empty_sheet) + len(_biff_record(0x000A, b""))
    label = _biff_record(
        0x0204,
        struct.pack("<HHH", 0, 0, 0) + struct.pack("<H", 1) + bytes([0]) + b"n",
    )
    number = _biff_record(0x0203, struct.pack("<HHHd", 1, 0, 0, 42.0))
    sheet = _biff_bof(0x0010) + label + number + _biff_record(0x000A, b"")
    return (
        _biff_bof(0x0005)
        + _biff_boundsheet(sheet_at)
        + _biff_record(0x000A, b"")
        + sheet
    )


def test_minimal_xls_extracts_one_cell():
    result = extract_upload("book.xls", _minimal_xls())
    assert result.unreadable is None
    assert result.sheets[0].name == "S"
    assert result.sheets[0].columns == ["n"]
    assert result.sheets[0].rows == [["42"]]


def test_truncated_ole_xls_is_unreadable_without_raising():
    data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    result = extract_upload("bad.xls", data)
    assert result.unreadable == UNREADABLE


def test_truncated_pdf_is_unreadable_without_raising():
    result = extract_upload("broken.pdf", b"%PDF-1.4\n" + b"garbage")
    assert result.unreadable == UNREADABLE
