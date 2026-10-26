"""Fix PowerShell corruption until ast.parse succeeds."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = {
    "backend/oa_agent/runtime/graphs/travel_query.py": ROOT / "scripts/_tq_all_strs.txt",
    "backend/oa_agent/runtime/engine.py": ROOT / "scripts/_consts_engine.txt",
    "backend/oa_agent/runtime/releases.py": ROOT / "scripts/_consts_releases.txt",
}


def load_table(path: Path) -> list[str]:
    if path.name == "_tq_all_strs.txt":
        return [p.strip("\n") for p in path.read_text(encoding="utf-8").split("====\n") if p.strip("\n")]
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln != "---"]


def global_fixes(text: str) -> str:
    # Stray quote before join / format placeholders inside f-strings and logs
    subs = [
        (r"f\"最大\"\{", 'f"最大 {'),
        (r"\{'\"\.join\(parts\)", "{'；'.join(parts)"),
        (r"or '\"\"\"", "or '—'"),
        (r'log\.info\("巡检：清理过期事"%d ', 'log.info("巡检：清理过期事件 %d '),
        (r'flag = "必填" if rule\.get\("required"\) else "可"', 'flag = "必填" if rule.get("required") else "可选"'),
    ]
    for pat, rep in subs:
        text = re.sub(pat, rep, text)
    return text


def fix_line(line: str, table: list[str]) -> str | None:
    s = line
    if 'log.info("巡检：清理过期事"%d' in s:
        return s.replace('"巡检：清理过期事"%d ', '"巡检：清理过期事件 %d ')
    if "parts.append(f" in s and "maximum" in s:
        return '        parts.append(f"最大 {rule[\'maximum\']}")'
    if "return f" in s and "join(parts)" in s and "'\"." in s:
        return re.sub(
            r"\{'\"\.join\(parts\) or '.*",
            "{'；'.join(parts) or '—'}",
            s.split("return f")[0]
            + "return f"
            + re.split(r"return f", s, maxsplit=1)[1].split("}")[0]
            + "}",
            count=1,
        )
    if '" = ' in s and '"help"' in s:
        # releases history_turns help — replace whole broken segment via table
        full = next((t for t in table if t.startswith("模型能看到本会话最近几轮对话")), "")
        if full and s.strip().startswith('"轮数越多'):
            return f'             "{full.split("。轮数越多", 1)[1].lstrip("。")}"'
    if s.strip().startswith('"help": "模型能看到'):
        full = next((t for t in table if t.startswith("模型能看到本会话最近几轮对话")), "")
        if full:
            a, rest = full.split("。", 1)
            return f'     "help": "{a}。"'
    if s.strip().startswith('"轮数越多') and full := next(
        (t for t in table if t.startswith("模型能看到本会话最近几轮对话")), ""
    ):
        parts = full.split("。")
        mid = "。".join(parts[1:-1]) + "。" if len(parts) > 2 else parts[1]
        return f'             "{mid}"'
    if '"history_ref_ids"' in s or (s.strip().startswith('"0 = 不记"')):
        pass
    # Generic: `"` breaking f-string before `{`
    if re.search(r'f"[^"]*"[^"]*\{', s):
        s2 = re.sub(r'f"([^"]*?)"(\{)', r'f"\1 \2', s)
        if s2 != s:
            return s2
    # `"` before %d in log calls
    m = re.search(r'log\.(warning|info|error)\("([^"]*?)"(%|\{)', s)
    if m:
        msg = m.group(2)
        for t in table:
            if "%d" in t and msg[:4] in t:
                indent = s[: len(s) - len(s.lstrip())]
                rest = s[m.end(2) :]
                if "warning" in s:
                    return indent + f'log.warning("{t}",' + rest.split(",", 1)[1]
                if "info" in s:
                    return indent + f'log.info("{t}",' + rest.split(",", 1)[1]
    return None


def repair_file(rel: str, table_path: Path) -> bool:
    path = ROOT / rel
    table = load_table(table_path)
    text = global_fixes(path.read_text(encoding="utf-8"))
    for _ in range(500):
        try:
            ast.parse(text)
            path.write_text(text, encoding="utf-8", newline="\n")
            return True
        except SyntaxError as e:
            if not e.lineno:
                break
            lines = text.splitlines()
            ln = e.lineno
            old = lines[ln - 1]
            new = fix_line(old, table)
            if new is None:
                print(f"STUCK {rel}:{ln} {e.msg}\n  {old[:160]}")
                path.write_text(text, encoding="utf-8", newline="\n")
                return False
            lines[ln - 1] = new
            text = "\n".join(lines) + "\n"
    return False


def main() -> None:
    failed = []
    for rel, tp in FILES.items():
        ok = repair_file(rel, tp)
        print("OK" if ok else "FAIL", rel)
        if not ok:
            failed.append(rel)
    if not failed:
        print("ALL OK")


if __name__ == "__main__":
    main()
