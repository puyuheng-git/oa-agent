"""Batch-fix stray double-quotes from PowerShell corruption (syntax-breaking only)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ROOT / "backend/oa_agent/runtime/graphs/travel_query.py",
    ROOT / "backend/oa_agent/runtime/engine.py",
    ROOT / "backend/oa_agent/runtime/releases.py",
]

# (regex on whole file, replacement) — order matters
GLOBAL: list[tuple[str, str]] = [
    # f-string / join breaks
    (r"\{'\"\.join\(parts\) or '\"\"'", "{'；'.join(parts) or '—'"),
    (r"f\"最大\"\{", 'f"最大 {'),
    (r'log\.info\("巡检：清理过期事件 %d 条"', 'log.info("巡检：清理过期事件 %d 条"'),  # noop anchor
    (r'log\.info\("巡检：清理过期事"%d ', 'log.info("巡检：清理过期事件 %d '),
    # engine skill error message
    (
        r"why = \"\"\.join\(f\"\{s\.name\}：\{'已停\" if not s\.enabled else '\"\.join\(s\.errors\) or '校验未通过'\}\"\s*for s in self\.skill_states\.values\(\)\) or \"未配置任\"Skill\"",
        "why = \"；\".join(f\"{s.name}：{'已停用' if not s.enabled else '；'.join(s.errors) or '校验未通过'}\""
        " for s in self.skill_states.values()) or \"未配置任何 Skill\"",
    ),
    # releases history_ref_ids help
    (
        r'"help": "列表查询后，历史里按显示顺序记下"N 条记录的 ID，员工说「第 3 条的详情」时模型据此"ID"\s*\n\s*"0 = 不记"ID（这类追问将无法理解）"',
        '"help": "列表查询后，历史里按显示顺序记下前 N 条记录的 ID，员工说「第 3 条的详情」时模型据此选 ID。"'
        '\n             "0 = 不记 ID（这类追问将无法理解）"',
    ),
    (
        r'"help": "一个问题需要先"A 再用 A 的结果查 B 时',
        '"help": "一个问题需要先用 A 再用 A 的结果查 B 时',
    ),
    (
        r'"help": "模型直接回答（非查询）时回复的最大字数，超出部分截掉。需要更长回答时同时调大模型"max_tokens"',
        '"help": "模型直接回答（非查询）时回复的最大字数，超出部分截掉。需要更长回答时同时调大模型的 max_tokens"',
    ),
    (
        r'企业微信按「企业微""流式刷新间隔」',
        '企业微信按「企业微信流式刷新间隔」',
    ),
    (
        r'"help": "滚动摘要：每次有对话移出时，模型把「已有摘"\+ 移出的对话」',
        '"help": "滚动摘要：每次有对话移出时，模型把「已有摘要 + 移出的对话」',
    ),
    (
        r'（增加"1" 秒和相应 Token）',
        '（增加约 1 秒和相应 Token）',
    ),
    (
        r'查询条件、记"ID、未完成',
        '查询条件、记录 ID、未完成',
    ),
    (
        r'f"\{label\}必须"\{f\[\'min\'\]\}',
        'f"{label}必须在 {f[\'min\']}',
    ),
    (
        r'f"\{label\}只能"\{\' / \'\.join\(allowed\)\}"',
        'f"{label}只能是 {\' / \'.join(allowed)}"',
    ),
    (
        r'f"运行绑定的发"\{release_id\} 不存"',
        'f"运行绑定的发布 {release_id} 不存在"',
    ),
    (
        r'f"已发布版"v\{version_no\} 不存"',
        'f"已发布版本 v{version_no} 不存在"',
    ),
    (
        r'"指定模型必须是模"ID 或留"',
        '"指定模型必须是模型 ID 或留空"',
    ),
    (
        r'raise AppError\(503, "SKILL_DISABLED", f"没有可用"Skill（\{why\}\)"\)',
        'raise AppError(503, "SKILL_DISABLED", f"没有可用的 Skill（{why}）")',
    ),
]

LINE_FIXES: dict[str, dict[int, str]] = {
    "backend/oa_agent/runtime/graphs/travel_query.py": {
        522: '        parts.append(f"最大 {rule[\'maximum\']}")',
        523: '    flag = "必填" if rule.get("required") else "可选"',
        524: '    return f"  - {name}（{kind}，{flag}）：{\'；\'.join(parts) or \'—\'}"',
    },
}


def apply_line_fixes(text: str, rel: str) -> str:
    fixes = LINE_FIXES.get(rel)
    if not fixes:
        return text
    lines = text.splitlines()
    for ln, content in fixes.items():
        if ln <= len(lines):
            lines[ln - 1] = content
    return "\n".join(lines) + "\n"


def main() -> None:
    failed: list[str] = []
    for path in TARGETS:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for pat, rep in GLOBAL:
            text = re.sub(pat, rep, text)
        text = apply_line_fixes(text, rel)
        path.write_text(text, encoding="utf-8", newline="\n")
        try:
            ast.parse(text)
            print("OK", rel)
        except SyntaxError as e:
            failed.append(rel)
            lines = text.splitlines()
            ctx = lines[(e.lineno or 1) - 1] if e.lineno else ""
            print("FAIL", rel, e.lineno, e.msg)
            print(" ", ctx[:180])
    return failed


if __name__ == "__main__":
    fails = main()
    if not fails:
        print("ALL OK")
