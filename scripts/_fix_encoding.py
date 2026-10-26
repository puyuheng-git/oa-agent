"""One-shot: mcp shims + report syntax errors (run then delete)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def make_shims() -> None:
    mcp = BACKEND / "oa_agent" / "mcp"
    for m in ("apipost", "catalog", "executor", "outbound", "registry", "tags", "visibility"):
        (mcp / f"{m}.py").write_text(
            f'"""兼容转发：请改用 oa_agent.executor.{m}。"""\n'
            f"from oa_agent.executor.{m} import *  # noqa: F403\n",
            encoding="utf-8",
            newline="\n",
        )
        print("shim", m)


def check_syntax() -> list[tuple[str, str]]:
    bad: list[tuple[str, str]] = []
    for p in BACKEND.rglob("*.py"):
        raw = p.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
            p.write_bytes(raw)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            bad.append((str(p.relative_to(ROOT)), f"decode: {e}"))
            continue
        # strip replacement-char spam in report
        try:
            ast.parse(text)
        except SyntaxError as e:
            bad.append((str(p.relative_to(ROOT)), f"line {e.lineno}: {e.msg}"))
    return bad


if __name__ == "__main__":
    make_shims()
    bad = check_syntax()
    print("syntax_errors", len(bad))
    for path, msg in bad:
        sys.stdout.buffer.write(f"{path}\t{msg}\n".encode("utf-8", errors="replace"))
