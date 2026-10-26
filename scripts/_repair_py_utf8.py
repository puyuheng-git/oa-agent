"""Repair PowerShell-corrupted Python: ``\\ufffd?`` ate the last char + closing quote."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    "backend/oa_agent/runtime/graphs/travel_query.py",
    "backend/oa_agent/chat/service.py",
    "backend/oa_agent/admin/catalog_api.py",
    "backend/oa_agent/admin/employees_api.py",
    "backend/oa_agent/runtime/engine.py",
    "backend/oa_agent/runtime/releases.py",
    "backend/tests/test_apipost_import.py",
    "backend/tests/test_catalog.py",
    "backend/tests/test_outbound_mcp.py",
    "backend/tests/test_runtime.py",
    "backend/tests/test_skill_visibility.py",
    "backend/tests/test_upstreams.py",
]


def repair_text(text: str) -> str:
    # Primary corruption: last UTF-8 char + closing " became U+FFFD + ?
    text = text.replace("\ufffd?", '"')
    # leftover replacement chars
    text = text.replace("\ufffd", "")
    return text


def main() -> int:
    fail = 0
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        text = repair_text(raw.decode("utf-8"))
        try:
            ast.parse(text)
            p.write_text(text, encoding="utf-8", newline="\n")
            sys.stdout.buffer.write(f"OK\t{rel}\n".encode())
        except SyntaxError as e:
            fail += 1
            # still write repaired attempt for inspection
            p.write_text(text, encoding="utf-8", newline="\n")
            sys.stdout.buffer.write(f"FAIL\t{rel}\tline {e.lineno}: {e.msg}\n".encode())
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
