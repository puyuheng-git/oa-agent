import binascii
import io
import struct
import zipfile

import pytest

from oa_agent.chat.attachment_admit import MSG_TYPE, AdmitError, admit_batch

# MSG_TYPE 含 TXT；断言仍用「只能上传」前缀匹配

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def test_png_and_pdf_pass():
    rows = admit_batch([("shot.png", PNG), ("a.pdf", PDF)])
    assert [r.media_kind for r in rows] == ["image", "document"]


def test_one_bad_rejects_batch():
    with pytest.raises(AdmitError, match="\u53ea\u80fd\u4e0a\u4f20"):
        admit_batch([("shot.png", PNG), ("a.exe", b"MZ")])


def test_empty_file():
    with pytest.raises(AdmitError, match="\u6587\u4ef6\u662f\u7a7a\u7684"):
        admit_batch([("a.csv", b"")])


def test_too_many():
    with pytest.raises(AdmitError, match="\u4e00\u6b21\u6700\u591a 5 \u4e2a\u6587\u4ef6"):
        admit_batch([(f"{i}.csv", b"a") for i in range(6)])


def test_csv_with_nul_rejected():
    with pytest.raises(AdmitError, match="\u53ea\u80fd\u4e0a\u4f20"):
        admit_batch([("a.csv", b"a\x00b")])


def test_renamed_png_as_pdf_rejected():
    with pytest.raises(AdmitError, match="\u53ea\u80fd\u4e0a\u4f20"):
        admit_batch([("a.pdf", PNG)])


def test_over_20mb_rejected():
    with pytest.raises(AdmitError, match="\u5355\u4e2a\u6587\u4ef6\u4e0d\u80fd\u8d85\u8fc7 20MB"):
        admit_batch([("a.csv", b"x" * (20 * 1024 * 1024 + 1))])


def test_xlsm_rejected():
    with pytest.raises(AdmitError, match="\u53ea\u80fd\u4e0a\u4f20"):
        admit_batch([("book.xlsm", b"PK\x03\x04")])


def test_doc_rejected():
    with pytest.raises(AdmitError, match="\u53ea\u80fd\u4e0a\u4f20"):
        admit_batch([("old.doc", b"\xd0\xcf\x11\xe0" + b"\x00" * 12)])


def test_valid_csv_passes():
    rows = admit_batch([("data.csv", b"a,b\n1,2")])
    assert len(rows) == 1
    assert rows[0].media_kind == "document"
    assert rows[0].extension == "csv"


def test_utf8_markdown_passes():
    rows = admit_batch([("notes.md", b"# Title\n\nHello")])
    assert len(rows) == 1
    assert rows[0].media_kind == "document"
    assert rows[0].extension == "md"


def test_utf8_txt_passes():
    rows = admit_batch([("memo.txt", "你好\n第二行".encode("utf-8"))])
    assert len(rows) == 1
    assert rows[0].media_kind == "document"
    assert rows[0].extension == "txt"
    assert rows[0].content_type == "text/plain"
    assert "TXT" in MSG_TYPE


def _xlsx_zip_with_entry_count(count: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("xl/workbook.xml", "<workbook/>")
        for i in range(count - 1):
            zf.writestr(f"xl/extra/{i}.txt", "a")
    return buf.getvalue()


def _xlsx_zip_uncompressed_over_50mb() -> bytes:
    """Zip with xl/ prefix; central directory reports >50MB uncompressed total."""
    over = 50 * 1024 * 1024 + 1
    filename = b"xl/workbook.xml"
    data = b"<workbook/>"
    crc = binascii.crc32(data) & 0xFFFFFFFF

    def u16(value: int) -> bytes:
        return struct.pack("<H", value)

    def u32(value: int) -> bytes:
        return struct.pack("<I", value)

    local = (
        u32(0x04034B50)
        + u16(20)
        + u16(0)
        + u16(0)
        + u16(0)
        + u16(0)
        + u32(crc)
        + u32(len(data))
        + u32(len(data))
        + u16(len(filename))
        + u16(0)
        + filename
        + data
    )
    cd = (
        u32(0x02014B50)
        + u16(20)
        + u16(20)
        + u16(0)
        + u16(0)
        + u16(0)
        + u16(0)
        + u32(crc)
        + u32(len(data))
        + u32(over)
        + u16(len(filename))
        + u16(0)
        + u16(0)
        + u16(0)
        + u16(0)
        + u32(0)
        + u32(0)
        + filename
    )
    cd_offset = len(local)
    eocd = (
        u32(0x06054B50)
        + u16(0)
        + u16(0)
        + u16(1)
        + u16(1)
        + u32(len(cd))
        + u32(cd_offset)
        + u16(0)
    )
    return local + cd + eocd


def _minimal_xlsx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        zf.writestr("xl/workbook.xml", "<workbook/>")
    return buf.getvalue()


def test_xlsx_zip_over_2000_entries_rejected():
    data = _xlsx_zip_with_entry_count(2001)
    with pytest.raises(AdmitError) as exc_info:
        admit_batch([("big.xlsx", data)])
    assert exc_info.value.message == MSG_TYPE


def test_xlsx_zip_uncompressed_over_50mb_rejected():
    data = _xlsx_zip_uncompressed_over_50mb()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        total = sum(info.file_size for info in zf.infolist())
        assert total > 50 * 1024 * 1024
    with pytest.raises(AdmitError) as exc_info:
        admit_batch([("huge.xlsx", data)])
    assert exc_info.value.message == MSG_TYPE
    assert "BadZipFile" not in exc_info.value.message
    assert "zipfile" not in exc_info.value.message.lower()


def test_truncated_docx_hides_zip_internals():
    truncated = b"PK\x03\x04" + b"\x00" * 12
    with pytest.raises(AdmitError) as exc_info:
        admit_batch([("broken.docx", truncated)])
    assert exc_info.value.message == MSG_TYPE
    assert "BadZipFile" not in exc_info.value.message
    assert "zipfile" not in exc_info.value.message.lower()


def test_filename_strips_path_prefix():
    rows = admit_batch([("C:\\temp\\shot.png", PNG)])
    assert rows[0].filename == "shot.png"
    rows = admit_batch([("dir/shot.png", PNG)])
    assert rows[0].filename == "shot.png"


def test_minimal_xlsx_accepted():
    rows = admit_batch([("book.xlsx", _minimal_xlsx())])
    assert len(rows) == 1
    assert rows[0].media_kind == "document"
    assert rows[0].extension == "xlsx"


def test_gbk_csv_accepted():
    text = "\u59d3\u540d,\u503c\n\u5f20\u4e09,1"
    data = text.encode("gbk")
    with pytest.raises(UnicodeDecodeError):
        data.decode("utf-8")
    rows = admit_batch([("gb.csv", data)])
    assert len(rows) == 1
    assert rows[0].media_kind == "document"
    assert rows[0].extension == "csv"
