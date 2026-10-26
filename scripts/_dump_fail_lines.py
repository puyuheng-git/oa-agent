from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
files = [
    "backend/oa_agent/runtime/graphs/travel_query.py",
    "backend/oa_agent/chat/service.py",
    "backend/oa_agent/admin/catalog_api.py",
    "backend/oa_agent/admin/employees_api.py",
    "backend/oa_agent/runtime/engine.py",
    "backend/oa_agent/runtime/releases.py",
    "backend/tests/test_apipost_import.py",
    "backend/tests/test_catalog.py",
    "backend/tests/test_runtime.py",
    "backend/tests/test_skill_visibility.py",
    "backend/tests/test_upstreams.py",
]
out = []
for rel in files:
    p = ROOT / rel
    text = p.read_text(encoding="utf-8")
    try:
        ast.parse(text)
        out.append(f"=== {rel} OK ===")
        continue
    except SyntaxError as e:
        lines = text.splitlines()
        ln = e.lineno or 1
        out.append(f"=== {rel} ERR line {ln}: {e.msg} ===")
        for i in range(max(1, ln - 2), min(len(lines), ln + 3) + 1):
            out.append(f"{i}|{lines[i-1]}")
(ROOT / "scripts/_fail_dump.txt").write_text("\n".join(out), encoding="utf-8")
print("wrote", len(out))
