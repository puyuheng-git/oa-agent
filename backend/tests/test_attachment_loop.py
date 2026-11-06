import re

from oa_agent.chat.attachment_extract import UNREADABLE, Extracted, Sheet, extract_upload
from oa_agent.chat.attachment_loop import (
    IMAGE_BUDGET,
    MAX_PAGES,
    MAX_READS,
    MAX_ROWS,
    MAX_SLICE_CHARS,
    TEXT_BUDGET,
    LoadedFile,
    ReadArgs,
    project,
    read_slice,
    run_loop,
)

NO_MORE = "\u6ca1\u6709\u66f4\u591a\u53ef\u8bfb\u5185\u5bb9"
NOTE_ROWS = "\u5df2\u8bfb\u8fc7\uff1a\u8d26\uff0c\u7b2c1\u884c\u5230\u7b2c2\u884c"
NOTE_PAGES = "\u5df2\u8bfb\u8fc7\uff1a\u7b2c1\u9875\u5230\u7b2c3\u9875"
NOTE_TABLE = "\u5df2\u8bfb\u8fc7\uff1a\u6570\u636e\uff0c\u7b2c1\u884c\u5230\u7b2c200\u884c"
SHEET_SALES = "\u8868\u540d\uff1a\u9500\u552e"
SECOND = "\u7b2c\u4e8c\u53e5\u7ed3\u8bba"


def test_limits_match_brief():
    assert TEXT_BUDGET == 30_000
    assert IMAGE_BUDGET == 8
    assert MAX_READS == 20
    assert MAX_ROWS == 200
    assert MAX_PAGES == 3
    assert MAX_SLICE_CHARS == 8000


def _extracted(**kwargs) -> Extracted:
    blank = dict(
        text="",
        profile="",
        sheets=[],
        pages=[],
        width=0,
        height=0,
        image_png=None,
        unreadable=None,
    )
    blank.update(kwargs)
    return Extracted(**blank)


def _file(
    extracted: Extracted,
    file_id: str = "f1",
    filename: str = "note.csv",
    media_kind: str = "csv",
    size_bytes: int = 10,
    sha256: str = "0123456789abcdef",
) -> LoadedFile:
    return LoadedFile(
        file_id=file_id,
        filename=filename,
        media_kind=media_kind,
        size_bytes=size_bytes,
        sha256=sha256,
        extracted=extracted,
    )


def _read(file_id: str = "f1", **kwargs) -> dict:
    body = {
        "action": "read",
        "file_id": file_id,
        "sheet": "",
        "row_offset": 0,
        "page_from": 0,
        "char_offset": 0,
    }
    body.update(kwargs)
    return body


def _message_text(messages) -> str:
    parts: list[str] = []
    for item in messages:
        if isinstance(item, dict):
            parts.append(str(item.get("content", "")))
        else:
            parts.append(str(item))
    return "\n".join(parts)


def _assert_model_text_clean(text: str) -> None:
    assert "object_key" not in text
    assert "http" not in text.lower()
    assert re.search(r"[A-Za-z]:[\\/]", text) is None


def test_ten_char_csv_is_full_and_keeps_body():
    raw = "ab,cd\n1,2\n"
    assert len(raw) == 10
    extracted = extract_upload("book.csv", raw.encode("utf-8"))
    projection = project([_file(extracted, filename="book.csv")])
    assert projection.mode == "full"
    assert "ab,cd" in projection.full_text
    assert "1,2" in projection.full_text


def test_text_over_budget_is_catalog_and_names_the_sheet():
    extracted = _extracted(
        text="\u9500" * (TEXT_BUDGET + 1),
        profile=SHEET_SALES + "\n\u884c\u6570\uff1a1",
        sheets=[Sheet("\u9500\u552e", ["\u91d1\u989d"], [["1"]], "")],
    )
    projection = project([_file(extracted, filename="sales.xlsx", media_kind="xlsx")])
    assert projection.mode == "catalog"
    assert "\u9500\u552e" in projection.catalog_text
    assert projection.full_text == ""
    assert projection.images == []


def test_table_slice_from_zero_has_two_hundred_rows():
    rows = [[f"row-{index:03d}"] for index in range(250)]
    extracted = _extracted(sheets=[Sheet("\u6570\u636e", ["n"], rows, "")])
    text = read_slice(
        _file(extracted, media_kind="xlsx"),
        ReadArgs(file_id="f1", sheet="\u6570\u636e", row_offset=0, page_from=0, char_offset=0),
    )
    body = [line for line in text.splitlines() if line.startswith("row-")]
    assert body == [f"row-{index:03d}" for index in range(200)]
    assert "row-200" not in text


def test_read_then_answer_keeps_second_sentence_and_range():
    extracted = _extracted(
        text="short",
        profile="\u8868\u540d\uff1a\u8d26\n\u884c\u6570\uff1a2",
        sheets=[Sheet("\u8d26", ["\u9879"], [["\u7532"], ["\u4e59"]], "")],
    )
    seen: list[str] = []

    def ask(messages):
        seen.append(_message_text(messages))
        if len(seen) == 1:
            return _read(sheet="\u8d26")
        return {"action": "answer", "answer": SECOND}

    result = run_loop([_file(extracted, filename="book.xlsx", media_kind="xlsx")], ask)
    assert result.kind == "answer"
    assert SECOND in result.answer
    assert result.read_note == NOTE_ROWS
    assert "\u7532" in seen[1]
    assert seen[0].index("\u8868\u540d") < seen[0].index("short")


def test_twenty_reads_do_not_call_ask_again_and_answer_is_nonempty():
    rows = [[f"row-{index:03d}"] for index in range(250)]
    extracted = _extracted(sheets=[Sheet("\u6570\u636e", ["n"], rows, "")])
    calls = {"n": 0}

    def ask(messages):
        calls["n"] += 1
        if calls["n"] > MAX_READS:
            raise AssertionError("ask called after 20 reads")
        return _read(sheet="\u6570\u636e", row_offset=0)

    result = run_loop([_file(extracted, media_kind="xlsx")], ask)
    assert calls["n"] == 20
    assert result.kind == "answer"
    assert result.answer
    assert NOTE_TABLE in result.answer
    assert NOTE_TABLE in result.read_note


def test_tool_before_any_read_delegates_and_asks_once():
    extracted = _extracted(text="hello", profile="\u8868\u540d\uff1aCSV")
    calls = {"n": 0}

    def ask(messages):
        calls["n"] += 1
        return {"action": "tool", "steps": [{"tool": "builtin.export", "args": {}}]}

    result = run_loop([_file(extracted)], ask)
    assert calls["n"] == 1
    assert result.kind == "delegate"
    assert result.steps == [{"tool": "builtin.export", "args": {}}]


def test_encrypted_file_is_listed_and_read_without_raising():
    assert UNREADABLE == "\u5df2\u52a0\u5bc6\uff0c\u65e0\u6cd5\u8bfb\u53d6"
    extracted = _extracted(unreadable=UNREADABLE)
    loaded = _file(extracted, filename="secret.xlsx", media_kind="xlsx")
    projection = project([loaded])
    assert UNREADABLE in projection.catalog_text
    text = read_slice(loaded, ReadArgs("f1", sheet="", row_offset=0, page_from=0, char_offset=0))
    assert text == UNREADABLE


def test_pdf_slice_is_three_pages_from_page_from():
    extracted = _extracted(pages=[f"P{number}" for number in range(1, 6)])
    loaded = _file(extracted, filename="a.pdf", media_kind="pdf")
    first = read_slice(loaded, ReadArgs("f1", sheet="", row_offset=0, page_from=1, char_offset=0))
    assert "P1" in first and "P2" in first and "P3" in first
    assert "P4" not in first
    later = read_slice(loaded, ReadArgs("f1", sheet="", row_offset=0, page_from=4, char_offset=0))
    assert "P4" in later and "P5" in later
    assert "P3" not in later
    assert read_slice(loaded, ReadArgs("f1", page_from=6)) == NO_MORE


def test_text_slice_is_8000_chars_and_out_of_range_stops():
    extracted = _extracted(text="a" * 9000)
    loaded = _file(extracted, filename="note.md", media_kind="md")
    assert read_slice(loaded, ReadArgs("f1", char_offset=0)) == "a" * MAX_SLICE_CHARS
    assert read_slice(loaded, ReadArgs("f1", char_offset=8000)) == "a" * 1000
    assert read_slice(loaded, ReadArgs("f1", char_offset=9000)) == NO_MORE


def test_table_past_the_end_has_no_more_rows():
    rows = [[f"row-{index:03d}"] for index in range(250)]
    extracted = _extracted(sheets=[Sheet("\u6570\u636e", ["n"], rows, "")])
    loaded = _file(extracted, media_kind="xlsx")
    tail = read_slice(loaded, ReadArgs("f1", sheet="\u6570\u636e", row_offset=200))
    body = [line for line in tail.splitlines() if line.startswith("row-")]
    assert body == [f"row-{index:03d}" for index in range(200, 250)]
    assert read_slice(loaded, ReadArgs("f1", sheet="\u6570\u636e", row_offset=250)) == NO_MORE


def test_nine_images_drop_to_catalog_and_eight_stay_full():
    png = b"png-bytes"

    def images(count: int):
        return [
            _file(
                _extracted(text="x", image_png=png, width=2, height=3),
                file_id=f"img{index}",
                filename=f"{index}.png",
                media_kind="png",
            )
            for index in range(count)
        ]

    over = project(images(IMAGE_BUDGET + 1))
    assert over.mode == "catalog"
    assert over.full_text == ""
    assert over.images == []
    fits = project(images(IMAGE_BUDGET))
    assert fits.mode == "full"
    assert fits.images == [(f"img{index}", png) for index in range(IMAGE_BUDGET)]


def test_model_text_has_file_id_and_size_but_not_secrets_or_image_bytes():
    marker = b"MARKER-http://png-object_key-C:\\drive"
    extracted = _extracted(
        text="visit http://example.com and D:\\secret object_key tail",
        profile="object_key http://catalog E:\\data \u5bbd\uff1a2",
        width=2,
        height=4,
        image_png=marker,
    )
    loaded = _file(
        extracted,
        file_id="img9",
        filename="C:\\temp\\http://evil\\shot.png",
        media_kind="png",
        sha256="abcdef1234567890",
    )
    projection = project([loaded])
    assert projection.mode == "full"
    assert projection.images == [("img9", marker)]
    _assert_model_text_clean(projection.catalog_text)
    _assert_model_text_clean(projection.full_text)
    assert "img9" in projection.catalog_text
    assert "shot.png" in projection.catalog_text
    assert "abcdef12" in projection.catalog_text
    assert "\u5bbd\uff1a2" in projection.catalog_text or "\u5bbd\uff1a2" in projection.catalog_text
    assert "\u9ad8\uff1a4" in projection.catalog_text
    assert "visit" in projection.full_text
    assert "tail" in projection.full_text
    assert b"MARKER-http" not in projection.catalog_text.encode("utf-8")
    assert b"MARKER-http" not in projection.full_text.encode("utf-8")

    seen: list[str] = []

    def ask(messages):
        seen.append(_message_text(messages))
        return {"action": "answer", "answer": "\u770b\u89c1\u56fe\u4e86"}

    result = run_loop([loaded], ask)
    assert result.answer == "\u770b\u89c1\u56fe\u4e86"
    _assert_model_text_clean(seen[0])
    assert "MARKER-http" not in seen[0]
    assert seen[0].index("img9") < seen[0].index("visit")


def test_page_read_note_records_pages():
    extracted = _extracted(pages=[f"P{number}" for number in range(1, 6)])

    def ask(messages):
        if not hasattr(ask, "done"):
            ask.done = True
            return _read(page_from=1)
        return {"action": "answer", "answer": "\u9875\u9762\u7ed3\u8bba"}

    result = run_loop([_file(extracted, filename="a.pdf", media_kind="pdf")], ask)
    assert result.read_note == NOTE_PAGES
    assert "\u9875\u9762\u7ed3\u8bba" in result.answer


def test_earlier_slices_collapse_to_notes_after_30k():
    extracted = _extracted(text="Z" * 40_000, profile="\u5927\u7eb2")
    offsets = [0, 8000, 16_000, 24_000]
    seen: list[str] = []

    def ask(messages):
        seen.append(_message_text(messages))
        if len(seen) <= len(offsets):
            return _read(char_offset=offsets[len(seen) - 1])
        return {"action": "answer", "answer": "\u6536\u53e3"}

    result = run_loop([_file(extracted, filename="note.md", media_kind="md")], ask)
    assert result.answer == "\u6536\u53e3"
    assert seen[3].count("Z") == 24_000
    assert seen[4].count("Z") == MAX_SLICE_CHARS
    assert seen[4].count("\u5df2\u8bfb\u8fc7") >= 3


def test_no_more_content_still_returns_nonempty_answer():
    extracted = _extracted(text="only")
    calls = {"n": 0}

    def ask(messages):
        calls["n"] += 1
        if calls["n"] > 4:
            raise AssertionError("ask kept going after the file ended")
        if calls["n"] == 1:
            return _read(char_offset=0)
        if calls["n"] == 2:
            return _read(char_offset=4)
        return {"action": "answer", "answer": "\u53ea\u80fd\u6839\u636e\u5df2\u8bfb\u5185\u5bb9"}

    result = run_loop([_file(extracted, filename="note.md", media_kind="md")], ask)
    assert calls["n"] <= 3
    assert result.kind == "answer"
    assert result.answer
