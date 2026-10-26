from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TQ = ROOT / "backend/oa_agent/runtime/graphs/travel_query.py"

PATCHES: dict[int, str] = {
    484: "# 模型把提示词/格式要求说出来时，不能当成给员工的回复",
    485: "_META_LEAK = re.compile(",
    486: '    r"(?is)(we\\s+need|json\\s+only|system\\s+says|only\\s+output|action\\s*[:=]|"',
    487: '    r"\\"reply\\"\\s*:|思考过程|让我(先)?(想|分析)|根据(系统|提示词))",',
    488: ")",
    492: '    """有的模型闲聊时不按 JSON 回答：不含花括号的纯文本视为聊天回复；疑似残缺 JSON 或思考泄漏仍按无效输出处理。"""',
    531: (
        '    return f"  返回：{\'列表 list\' if spec.result_kind == \'list\' else \'单条记录\'}，字段 {fields}"'
    ),
    789: '    """多步查询：说明查询顺序；中途取不到引用值时说明在哪一步停止"""',
    796: (
        '        note = (f"> 已查询「{\'」→「\'.join(done)}」，但上一步没有返回可用于继续查询「{_title(tools, stop.get(\'tool\'))}"'
    ),
    797: '                f"」的数据，已停止后续查询。")',
    799: '        note = f"> 已依次查询：「{\'」→「\'.join(done)}」，以下是最终结果"',
    804: '    """查询结果只给模型摘要（工具、条件、条数、记录 ID），不含业务明细，模型不能据此复述业务数据"""',
    810: (
        "    chain = (f\"多步查询，先后调用 {'、'.join(s.get('tool') or '' for s in steps)}；最终\" if len(steps) > 1 else \"\")"
    ),
    811: "    head = f\"[{chain}已调用工具 {data.get('tool')}，条件 {json.dumps(params, ensure_ascii=False)}\"",
    814: '        return head + (f"，返回记录 ID {item_id}" if item_id not in (None, "") else "，返回 1 条记录") + "。明细已展示给员工]"',
    816: '    shown = "，".join(str(i) for i in ids[:ctx.num("history_ref_ids")])',
    817: '    return (head + f"，共 {data.get(\'total\')} 条" + (f"，按显示顺序的记录 ID：{shown}" if shown else "")',
    818: '            + "。明细已展示给员工]")',
    854: '        parts = [f"{params[\'date_gte\']} 至 {params[\'date_lte\']}"]',
    862: '        parts.append(f"{rule.get(\'label\') or key}：{_value_text(rule, value)}")',
    867: '    """有数据时把业务系统的提示语附在回复末尾；notice 字段供前端单独展示"""',
    870: '    return {**reply, "content": f"{reply[\'content\']}\\n\\n> 业务系统提示：{notice}", "notice": notice}',
    878: '    scope = f"按条件（{cond}）" if cond else ""',
    879: '    if not rows:',
    880: '        return {"type": "markdown", "content": notice or f"{scope}没有查到{title}记录。", "data": None}',
    881: '    cols = list(spec.columns())',
    882: '    lines = [f"{scope}共查到 **{total}** 条{title}记录"',
    883: '             + (f"（显示前 {len(rows)} 条）" if isinstance(total, int) and total > len(rows) else "") + "", "",',
    884: '             "| " + " | ".join(_cell(spec.label(c)) for c in cols) + " |", "|" + "---|" * len(cols)]',
    885: '    lines += ["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows]',
    894: '        return {"type": "markdown", "content": notice or f"没有查到相关的{title}记录（或该记录不属于你）。",',
    899: '    lines += [f"- {spec.label(f)}：{_cell(data[f])}" for f in fields]',
}


def main() -> None:
    lines = TQ.read_text(encoding="utf-8").splitlines()
    for ln, content in PATCHES.items():
        lines[ln - 1] = content
    text = "\n".join(lines) + "\n"
    TQ.write_text(text, encoding="utf-8", newline="\n")
    try:
        ast.parse(text)
        print("OK travel_query")
    except SyntaxError as e:
        print("FAIL", e.lineno, e.msg)
        print(lines[e.lineno - 1][:200])


if __name__ == "__main__":
    main()
