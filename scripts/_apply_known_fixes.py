from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fix_travel_query(text: str) -> str:
    reps = [
        (
            "return f\"  返回（{'列表 list' if spec.result_kind == 'list' else '单条记录'}，字段\"{fields}\"",
            "return f\"  返回：{'列表 list' if spec.result_kind == 'list' else '单条记录'}，字段 {fields}\"",
        ),
        (
            'parts.append(f"最大"{rule[\'maximum\']}")',
            'parts.append(f"最大 {rule[\'maximum\']}")',
        ),
        (
            "return f\"  - {name}（{kind}，{flag}）：{'\".join(parts) or '\"\"}",
            "return f\"  - {name}（{kind}，{flag}）：{'；'.join(parts) or '—'}\"",
        ),
    ]
    for a, b in reps:
        if a in text:
            text = text.replace(a, b)
    return text


def fix_engine(text: str) -> str:
    reps = [
        (
            'raise AppError(503, "SKILL_DISABLED", f"没有可用"Skill（{why}）")',
            'raise AppError(503, "SKILL_DISABLED", f"没有可用的 Skill（{why}）")',
        ),
        (
            """why = "".join(f"{s.name}：{'已停" if not s.enabled else '".join(s.errors) or '校验未通过'}"
                           for s in self.skill_states.values()) or "未配置任"Skill\"""",
            """why = "；".join(
                f"{s.name}：{'已停用' if not s.enabled else '；'.join(s.errors) or '校验未通过'}"
                for s in self.skill_states.values()
            ) or "未配置任何 Skill\"""",
        ),
    ]
    for a, b in reps:
        if a in text:
            text = text.replace(a, b)
    # fallback partial
    text = text.replace('f"没有可用"Skill（{why}）"', 'f"没有可用的 Skill（{why}）"')
    if '已停"' in text and 'why = "' in text:
        text = text.replace(
            "why = \"\".join(f\"{s.name}：{'已停\" if not s.enabled else '\".join(s.errors) or '校验未通过'}\""
            " for s in self.skill_states.values()) or \"未配置任\"Skill\"",
            "why = \"；\".join(f\"{s.name}：{'已停用' if not s.enabled else '；'.join(s.errors) or '校验未通过'}\""
            " for s in self.skill_states.values()) or \"未配置任何 Skill\"",
        )
    return text


def fix_releases(text: str) -> str:
    reps = [
        (
            '"help": "列表查询后，历史里按显示顺序记下"N 条记录的 ID，员工说「第 3 条的详情」时模型据此"ID"\n'
            '             "0 = 不记"ID（这类追问将无法理解）"',
            '"help": "列表查询后，历史里按显示顺序记下前 N 条记录的 ID，员工说「第 3 条的详情」时模型据此选 ID。"\n'
            '             "0 = 不记 ID（这类追问将无法理解）"',
        ),
        (
            '"滚动摘要：每次有对话移出时，模型把「已有摘"+ 移出的对话」改写成一段新摘要；语义保留最好，"',
            '"滚动摘要：每次有对话移出时，模型把「已有摘要 + 移出的对话」改写成一段新摘要；语义保留最好，"',
        ),
    ]
    for a, b in reps:
        text = text.replace(a, b)
    return text


def process(rel: str, fixer) -> bool:
    path = ROOT / rel
    text = fixer(path.read_text(encoding="utf-8"))
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        ast.parse(text)
        print("OK", rel)
        return True
    except SyntaxError as e:
        lines = text.splitlines()
        ctx = lines[(e.lineno or 1) - 1] if e.lineno else ""
        print("FAIL", rel, e.lineno, e.msg)
        print(" ", ctx[:200])
        return False


def main() -> None:
    process("backend/oa_agent/runtime/graphs/travel_query.py", fix_travel_query)
    process("backend/oa_agent/runtime/engine.py", fix_engine)
    process("backend/oa_agent/runtime/releases.py", fix_releases)


if __name__ == "__main__":
    main()
