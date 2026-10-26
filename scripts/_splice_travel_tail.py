from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TQ = ROOT / "backend/oa_agent/runtime/graphs/travel_query.py"

BLOCK = r'''
def _with_notice(reply: dict, notice: str) -> dict:
    """有数据时把业务系统的提示语附在回复末尾；notice 字段供前端单独展示"""
    if not notice:
        return reply
    return {**reply, "content": f"{reply['content']}\n\n> 业务系统提示：{notice}", "notice": notice}


def _list_reply(spec: ToolSpec, title: str, data: dict, params: dict, notice: str = "",
                max_rows: int = DEFAULT_CONFIG["max_table_rows"]) -> dict:
    rows = (data.get("list") or [])[:max_rows]
    total = data.get("total", len(rows))
    cond = _conditions(spec, params)
    scope = f"按条件（{cond}）" if cond else ""
    if not rows:
        return {"type": "markdown", "content": notice or f"{scope}没有查到{title}记录。", "data": None}
    cols = list(spec.columns())
    lines = [f"{scope}共查到 **{total}** 条{title}记录"
             + (f"（显示前 {len(rows)} 条）" if isinstance(total, int) and total > len(rows) else "") + "", "",
             "| " + " | ".join(_cell(spec.label(c)) for c in cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows]
    return _with_notice({"type": "markdown", "content": "\n".join(lines),
                         "data": {"kind": "table", "tool": spec.name, "title": title,
                                  "columns": [{"key": c, "label": spec.label(c)} for c in cols],
                                  "items": rows, "total": total}}, notice)


def _record_reply(spec: ToolSpec, title: str, data: dict, params: dict, notice: str = "") -> dict:
    if not data:
        return {"type": "markdown", "content": notice or f"没有查到相关的{title}记录（或该记录不属于你）。",
                "data": None}
    shown = [f for f in spec.result_fields if f in spec.result_labels] or list(spec.result_fields)
    fields = [f for f in shown if data.get(f) not in (None, "")]
    lines = [f"**{title}**" + (f" {data['id']}" if data.get("id") not in (None, "") else ""), ""]
    lines += [f"- {spec.label(f)}：{_cell(data[f])}" for f in fields]
    return _with_notice({"type": "markdown", "content": "\n".join(lines),
                         "data": {"kind": "record", "tool": spec.name, "title": title,
                                  "fields": [{"key": f, "label": spec.label(f)} for f in fields], "item": data}},
                        notice)

'''.lstrip("\n")


def main() -> None:
    lines = TQ.read_text(encoding="utf-8").splitlines()
    # keep through _conditions / before broken _with_notice
    start = next(i for i, l in enumerate(lines) if l.startswith("def _with_notice"))
    end = next(i for i, l in enumerate(lines) if l.startswith("def _route"))
    new_lines = lines[:start] + BLOCK.splitlines() + lines[end:]
    text = "\n".join(new_lines) + "\n"
    TQ.write_text(text, encoding="utf-8", newline="\n")
    ast.parse(text)
    print("OK travel_query splice")


if __name__ == "__main__":
    main()
