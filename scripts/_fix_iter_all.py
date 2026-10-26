"""Iteratively repair PowerShell-corrupted Python sources using pyc string tables."""
from __future__ import annotations

import ast
import marshal
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS = [
    ROOT / "backend/oa_agent/runtime/graphs/travel_query.py",
    ROOT / "backend/oa_agent/chat/service.py",
    ROOT / "backend/oa_agent/runtime/engine.py",
    ROOT / "backend/oa_agent/runtime/releases.py",
]

STR_TABLE = {
    TARGETS[0]: ROOT / "scripts/_tq_all_strs.txt",
    TARGETS[1]: ROOT / "scripts/_consts_service.txt",
    TARGETS[2]: ROOT / "scripts/_consts_engine.txt",
    TARGETS[3]: ROOT / "scripts/_consts_releases.txt",
}

# Known exact line replacements (1-based), applied before the parse loop.
PRE_PATCHES: dict[Path, dict[int, str]] = {
    TARGETS[0]: {
        356: "# 显式记忆口令（设计 D9）：不依赖模型是否输出 memory_write；口语「记住…」也要能落库",
        357: "_MEMORY_WRITE_RE = re.compile(",
        358: (
            r'    r"^(?:请)?(?:帮我)?记住(?:一下)?(?:着)?(?:：|:|，|,|吧)?\s*(?P<body>.+)$"'
        ),
        359: (
            r'    r"|^(?:请)?记一下(?:：|:|，|,)?\s*(?P<body2>.+)$",'
        ),
        360: "    re.DOTALL,",
        361: ")",
        362: "_MEMORY_FORGET_RE = re.compile(",
        363: (
            r'    r"^(?:请)?(?:帮我)?(?:忘掉|忘记|别再记住?)(?:：|:|，|,|吧|了)?\s*(?P<body>.+)$",'
        ),
        364: "    re.DOTALL,",
        365: ")",
    },
    TARGETS[1]: {
        251: (
            "        return None, None, ("
        ),
        252: (
            '            f"运行上下文已过期（超过 {setting(rt, \'chat\', \'run_context_ttl_hours\')} 小时）"'
        ),
        253: '            "或缓存已清空），无法恢复")',
        255: '        return None, ctx, "员工会话已过期，无法以员工身份继续执行"',
    },
    TARGETS[2]: {
        128: '                log.warning("巡检到 %d 个介入任务过期", expired)',
        139: '                    log.info("巡检：清理过期事件 %d 条", purged)',
    },
    TARGETS[3]: {
        57: (
            '     "help": "提示词开头的身份描述，决定助手的自称和语气，如「你是 XX 公司的行政小助手『小 O』」。'
        ),
        58: (
            '             "输出格式与安全规则（不编造业务数据、不代办业务、身份由系统注入）固定在代码中，这里无法修改。留空恢复默认"},'
        ),
    },
}


def load_str_table(path: Path) -> list[str]:
    if path.name == "_tq_all_strs.txt":
        parts = path.read_text(encoding="utf-8").split("====\n")
        return [p.strip("\n") for p in parts if p.strip("\n")]
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln != "---"]


def load_pyc_strings(pyc: Path) -> list[str]:
    data = pyc.read_bytes()
    # skip header (16 bytes for 3.7+)
    code = marshal.loads(data[16:])
    out: list[str] = []

    def walk(co: types.CodeType) -> None:
        for c in co.co_consts:
            if isinstance(c, str):
                out.append(c)
            elif isinstance(c, types.CodeType):
                walk(c)

    walk(code)
    return out


def repair_encoding(text: str) -> str:
    text = text.replace("\ufffd?", '"')
    text = text.replace("\ufffd", "")
    return text


def apply_line_patches(text: str, patches: dict[int, str]) -> str:
    if not patches:
        return text
    lines = text.splitlines()
    for ln, content in patches.items():
        while len(lines) < ln:
            lines.append("")
        lines[ln - 1] = content
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "\n")


def try_fix_line(line: str, table: list[str]) -> str | None:
    """Heuristic: find a table string that matches line prefix/suffix after removing stray quotes."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    # Broken f-string / log: `"巡检"d` -> use table entry containing % or full Chinese sentence
    if "log." in stripped or stripped.startswith('"') or stripped.startswith("'"):
        for s in table:
            if len(s) < 8:
                continue
            if s in stripped:
                continue
            # log.warning("...", arg) pattern
            if "log." in stripped and s.startswith("巡检"):
                if "warning" in stripped:
                    if "%d" in s or "{" in s:
                        indent = line[: len(line) - len(line.lstrip())]
                        if "介入任务" in s:
                            return indent + f'log.warning("{s}", expired)'
                        if "运行超时" in s:
                            return indent + f'log.warning("{s}", n)'
                if "info" in stripped and "清理" in s:
                    return indent + f'log.info("{s}", purged)'
    return None


def fix_releases_bulk(text: str, table: list[str]) -> str:
    """Replace known broken help strings in releases.py using const table."""
    by_key: dict[str, str] = {}
    i = 0
    while i < len(table):
        key = table[i]
        if key in {
            "assistant_persona",
            "history_turns",
            "history_ref_ids",
            "history_compress_mode",
            "max_tool_steps",
            "chat_reply_max_chars",
            "stream_output",
        }:
            # help text usually follows label/kind entries; grab next long string
            for j in range(i + 1, min(i + 6, len(table))):
                if len(table[j]) > 40 and "help" not in table[j]:
                    by_key[key] = table[j]
                    break
        i += 1

    # Full help from table (line 82 in _consts_releases.txt)
    persona_help = next(
        (s for s in table if "行政小助手" in s and "输出格式" in s),
        by_key.get("assistant_persona", ""),
    )
    if persona_help:
        text = re.sub(
            r'"help": "提示词开头的身份描述[^"]*"\s*\n\s*"[^"]*留空恢复默认"\},',
            '"help": "' + persona_help + '"},',
            text,
            count=1,
        )

    # Fix stray `"` inside strings: `"你"XX` patterns — use table strings where possible
    fixes = [
        (
            r'"help": "模型能看到本会话最近几轮对话[^"]*"\s*\n\s*"[^"]*"\s*\n\s*"查询结果',
            None,
        ),
    ]
    history_turns_help = next(
        (s for s in table if s.startswith("模型能看到本会话最近几轮对话")),
        "",
    )
    if history_turns_help:
        # split long help across two physical lines like original source
        mid = history_turns_help.find("。轮数越多")
        if mid == -1:
            mid = len(history_turns_help) // 2
        a, b = history_turns_help[:mid], history_turns_help[mid:].lstrip("。")
        repl = (
            f'     "help": "{a}"\n'
            f'             "{b}"'
        )
        text = re.sub(
            r'     "help": "模型能看到本会话最近几轮对话[^\n]*\n\s+"[^\n]*\n\s+"查询结果',
            repl + '\n             "查询结果',
            text,
            count=1,
        )

    return text


def parse_loop(path: Path, table: list[str], max_rounds: int = 200) -> tuple[bool, str]:
    text = repair_encoding(path.read_text(encoding="utf-8"))
    text = apply_line_patches(text, PRE_PATCHES.get(path, {}))
    if path.name == "releases.py":
        text = fix_releases_bulk(text, table)

    for _ in range(max_rounds):
        try:
            ast.parse(text)
            path.write_text(text, encoding="utf-8", newline="\n")
            return True, text
        except SyntaxError as e:
            if e.lineno is None:
                return False, text
            lines = text.splitlines()
            ln = e.lineno
            if ln < 1 or ln > len(lines):
                return False, text
            bad = lines[ln - 1]
            fixed = try_fix_line(bad, table)
            if fixed is None:
                # try matching full string literal from table for broken "help" lines
                for s in table:
                    if len(s) > 30 and bad.strip().startswith('"') and s[:12] in bad:
                        indent = bad[: len(bad) - len(bad.lstrip())]
                        lines[ln - 1] = indent + f'"{s}",'
                        fixed = lines[ln - 1]
                        break
            if fixed is None:
                return False, text
            lines[ln - 1] = fixed
            text = "\n".join(lines) + "\n"
    return False, text


def main() -> int:
    failed: list[str] = []
    for path in TARGETS:
        table = load_str_table(STR_TABLE[path])
        ok, _ = parse_loop(path, table)
        rel = path.relative_to(ROOT).as_posix()
        if ok:
            print(f"OK {rel}")
        else:
            failed.append(rel)
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as e:
                print(f"FAIL {rel} line {e.lineno}: {e.msg}")
            else:
                print(f"FAIL {rel}")
    if not failed and all(
        ast.parse(p.read_text(encoding="utf-8")) or True for p in TARGETS
    ):
        print("ALL PARSE OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
