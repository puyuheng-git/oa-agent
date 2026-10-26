"""Iteratively patch known remaining syntax breaks after encoding salvage."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Exact line replacements (1-based). Prefer recovering from pyc string table.
PATCHES: dict[str, dict[int, str]] = {
    "backend/oa_agent/runtime/graphs/travel_query.py": {
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
    },
    "backend/oa_agent/chat/service.py": {
        248: '    """重验身份：运行上下文存在、会话仍有效、且会话员工与运行员工一致。返回 (会话, 上下文)；不可用时原因。"""',
        251: (
            '        return None, None, (f"运行上下文已过期（超过 {setting(rt, \'chat\', \'run_context_ttl_hours\')} 小时）")'
        ),
    },
    "backend/oa_agent/runtime/engine.py": {
        121: '                log.warning("巡检到 %d 个运行超时，标记为 timed_out", n)',
    },
    "backend/oa_agent/runtime/releases.py": {
        45: '                 {"value": "handoff", "label": "转人工介入（管理员决定重试或终止）"}],',
        46: '     "help": "office-api 超时、不可达或返回 5xx 时的处理。转人工后运行挂起，在「人工介入」页处理；"',
        47: '             "业务校验失败（4xx）不会转人工，直接把业务系统的提示告诉员工"},',
        49: '     "help": "员工问「你能做什么」或问题无法处理时的回复。留空则按可用 Skill 的名称、说明和示例问题自动生成（推荐）；"',
    },
    "backend/tests/test_apipost_import.py": {
        100: '    assert params["user_id"] == "zhangsan", "身份参数由服务端注入，模型给的 lisi 被覆盖"',
    },
    "backend/tests/test_runtime.py": {
        125: '    assert intent_rules.parse("本月未报销的行程", TODAY)["params"]["status"] == 0',
        126: '    assert intent_rules.parse("查看报销单 12345 详情", TODAY) == {"intent": "detail", "params": {"id": 12345}}',
        127: '    assert intent_rules.parse("今天天气怎么样", TODAY)["intent"] == "help"',
    },
}


def apply() -> None:
    for rel, mapping in PATCHES.items():
        p = ROOT / rel
        lines = p.read_text(encoding="utf-8").splitlines()
        for ln, content in mapping.items():
            if ln <= len(lines):
                lines[ln - 1] = content
        text = "\n".join(lines) + "\n"
        p.write_text(text, encoding="utf-8", newline="\n")
        try:
            ast.parse(text)
            print("OK", rel)
        except SyntaxError as e:
            print("FAIL", rel, e.lineno, e.msg)


if __name__ == "__main__":
    apply()
