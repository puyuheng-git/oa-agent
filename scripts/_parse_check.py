import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = [
    "backend/oa_agent/runtime/graphs/travel_query.py",
    "backend/oa_agent/chat/service.py",
    "backend/oa_agent/runtime/engine.py",
    "backend/oa_agent/runtime/releases.py",
]
failed = []
for f in files:
    p = ROOT / f
    try:
        ast.parse(p.read_text(encoding="utf-8"))
        print("OK", f)
    except SyntaxError as e:
        failed.append(f)
        lines = p.read_text(encoding="utf-8").splitlines()
        ln = e.lineno or 0
        ctx = lines[ln - 1] if 0 < ln <= len(lines) else ""
        print("FAIL", f, "line", ln, e.msg)
        print(" ", ctx[:200])
if not failed:
    print("ALL OK")
