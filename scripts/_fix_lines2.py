from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIXES: dict[str, list[tuple[int, str]]] = {
    "backend/oa_agent/runtime/graphs/travel_query.py": [
        (
            135,
            'NO_TOOLS = "## 可用工具\\n当前没有开放任何查询工具，只能直接回答（action 只能为 \\"chat\\"）"',
        ),
    ],
    "backend/oa_agent/chat/service.py": [
        (
            238,
            "    except Exception:  # noqa: BLE001 — 回复缓存失败只影响员工轮询看到结果，不影响运行本身",
        ),
        (239, '        log.exception("缓存运行回复失败 run_id=%s", run_id)'),
    ],
    "backend/oa_agent/admin/catalog_api.py": [
        (
            257,
            '                d["warnings"].append("未配置 LLM：名称、用途说明与配套 Skill 需手工填写")',
        ),
    ],
    "backend/oa_agent/admin/employees_api.py": [
        (366, '            raise AppError(422, "VALIDATION_ERROR", "至少提供 title 或 status")'),
    ],
    "backend/oa_agent/runtime/engine.py": [
        (95, '            log.exception("初始化 Workflow 发布失败")'),
    ],
    "backend/oa_agent/runtime/releases.py": [
        (
            41,
            '     "unit": "", "help": "员工没说要看几条时，列表查询默认返回的条数；员工明确说了（如「最近 3 笔」）以员工为准，"',
        ),
        (42, '                         "且不超过 Tool 参数规则里的上限"},'),
    ],
    "backend/tests/test_apipost_import.py": [
        (82, '    for p in ("ht_bh", "run_id"):  # 管理员检查后改为非必填'),
        (
            84,
            '    assert admin.post("/v1/admin/tools", json={**form, "reason": "从 Apipost 导入"}).status_code == 200',
        ),
        (
            85,
            '    skill = admin.post("/v1/admin/skills", json={**draft["skill"], "reason": "从 Apipost 导入"})',
        ),
    ],
    "backend/tests/test_runtime.py": [
        (113, '    ("本周的行程", ("2026-10-05", "2026-10-09")),'),
        (115, '    ("最近7天的行程", ("2026-10-03", "2026-10-09")),'),
    ],
}


def main() -> None:
    for rel, lines in FIXES.items():
        p = ROOT / rel
        text_lines = p.read_text(encoding="utf-8").splitlines()
        for lineno, content in lines:
            text_lines[lineno - 1] = content
        text = "\n".join(text_lines) + "\n"
        try:
            ast.parse(text)
            p.write_text(text, encoding="utf-8", newline="\n")
            print("OK", rel)
        except SyntaxError as e:
            p.write_text(text, encoding="utf-8", newline="\n")
            print("FAIL", rel, e.lineno, e.msg)


if __name__ == "__main__":
    main()
