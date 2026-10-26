from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ROOT / "backend/oa_agent/runtime/graphs/travel_query.py",
    ROOT / "backend/oa_agent/runtime/engine.py",
]


def fix_text(text: str) -> str:
    lines = text.splitlines()
    out = []
    for line in lines:
        if "return f" in line and "{fields}" in line and '字段"' in line:
            line = re.sub(r'字段"\{fields\}"\s*$', "字段 {fields}\"", line)
        if "return f" in line and "{fields}" in line:
            line = re.sub(r'，字段"\{fields\}"', "，字段 {fields}\"", line)
        if 'SKILL_DISABLED' in line and '"Skill' in line:
            line = re.sub(
                r'f"没有可用"Skill（\{why\}）"',
                'f"没有可用的 Skill（{why}）"',
                line,
            )
            line = re.sub(
                r'f"[^"]*"Skill（\{why\}）"',
                'f"没有可用的 Skill（{why}）"',
                line,
            )
        out.append(line)
    text = "\n".join(out) + "\n"
    # whole-file patterns
    text = re.sub(
        r"why = \"\"\.join\(f\"\{s\.name\}：\{'已停\" if not s\.enabled else '\"\.join\(s\.errors\) or '校验未通过'\}\""
        r" for s in self\.skill_states\.values\(\)\) or \"未配置任\"Skill\"",
        "why = \"；\".join(f\"{s.name}：{'已停用' if not s.enabled else '；'.join(s.errors) or '校验未通过'}\""
        " for s in self.skill_states.values()) or \"未配置任何 Skill\"",
        text,
    )
    return text


def main() -> None:
    for path in FILES:
        text = fix_text(path.read_text(encoding="utf-8"))
        for _ in range(100):
            try:
                ast.parse(text)
                break
            except SyntaxError as e:
                if not e.lineno:
                    break
                lines = text.splitlines()
                bad = lines[e.lineno - 1]
                new = bad
                # generic: `"Word（` inside f-string literal
                new2 = re.sub(
                    r'(f"[^"]*)"([A-Za-z_][A-Za-z0-9_]*)([（(])',
                    r"\1的 \2\3",
                    new,
                    count=1,
                )
                if new2 != new:
                    lines[e.lineno - 1] = new2
                    text = "\n".join(lines) + "\n"
                    continue
                # `"` before `{var}` at end of f-string piece
                new2 = re.sub(r'"(\{[a-zA-Z_][^}]*\})"', r" \1", new)
                if new2 != new:
                    lines[e.lineno - 1] = new2
                    text = "\n".join(lines) + "\n"
                    continue
                print("STUCK", path.name, e.lineno, e.msg, repr(bad[:120]))
                break
        path.write_text(text, encoding="utf-8", newline="\n")
        try:
            ast.parse(text)
            print("OK", path.relative_to(ROOT))
        except SyntaxError as e:
            print("FAIL", path.relative_to(ROOT), e.lineno, e.msg)


if __name__ == "__main__":
    main()
