"""会话压缩：超出「带给模型的历史轮数」的旧对话合并为一段「记忆」，随 Checkpoint 按会话线程保存。

三种方式（发布配置 history_compress_mode）：
- truncate 截断压缩：每条旧消息截成一行短摘录，按时间顺序追加；超出记忆上限时丢最早的行。不调用模型、零成本。
- summary 滚动摘要：模型把「已有摘要 + 新移出的对话」改写成一段新摘要。每次压缩多一次模型调用。
- facts 要点提取：模型从旧对话中提取要点（偏好、查询条件、记录 ID、未完成的请求），与已有要点合并去重。

模型方式失败（未配置模型、调用失败、输出无效）时回退为截断压缩，不影响本次回复。
记忆只来自员工原话与助手回复（查询结果在历史里只有工具、条件和记录 ID），注入提示词时标注为「仅供理解上下文」。
"""

from __future__ import annotations

import re

from oa_agent.observability.events import RunRecorder
from oa_agent.runtime.llm import ModelCallError, ModelConfig, invoke_json, invoke_text

TRUNCATE, SUMMARY, FACTS = "truncate", "summary", "facts"
MODES = (TRUNCATE, SUMMARY, FACTS)
FACT_CHARS = 80
NODE = "remember"

SUMMARY_PROMPT = """你负责维护员工与 OA 助手之间对话的「滚动摘要」，供助手在后续对话中理解上下文。
把【已有摘要】和【新移出的对话】合并为一段新的摘要，只输出摘要正文，不要输出其他文字。
要求：
- 不超过 {limit} 字，用简体中文，按时间顺序概括。
- 保留：员工关心的话题、表达过的偏好与习惯、查询过的功能和条件（时间范围、状态等）、提到的记录 ID、尚未完成的请求。
- 删除寒暄、重复和已无意义的内容；新信息与旧信息冲突时以新的为准。
- 只根据给出的内容概括，不要编造，不要补充对话中没有的数据。"""

FACTS_PROMPT = """你负责从员工与 OA 助手的对话中提取「要点」，供助手在后续对话中理解上下文。
把【已有要点】和【新移出的对话】合并，输出一个 JSON 对象，不要输出其他文字：
{{"facts": ["要点1", "要点2"]}}
要求：
- 只提取后续对话可能用到的信息：员工的偏好与习惯、查询过的功能和条件（时间范围、状态等）、提到的记录 ID、尚未完成的请求、已确认的结论。
- 每条不超过 {fact_chars} 字，合计不超过 {limit} 字；去掉重复，新信息与旧要点冲突时保留新的。
- 只根据给出的内容提取，不要编造。"""


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _transcript(turns: list[dict], message_chars: int) -> str:
    lines = []
    for item in turns:
        content = _flat(item.get("content"))[:message_chars]
        if content:
            lines.append(("员工：" if item.get("role") == "user" else "助手：") + content)
    return "\n".join(lines)


def _fit(lines: list[str], limit: int) -> str:
    """保留最新的若干行，使总长度不超过 limit。"""
    kept: list[str] = []
    size = 0
    for line in reversed([x for x in lines if x.strip()]):
        if size + len(line) + 1 > limit:
            break
        kept.append(line)
        size += len(line) + 1
    return "\n".join(reversed(kept))


def truncate(memory: str, overflow: list[dict], limit: int, line_chars: int) -> str:
    lines = memory.splitlines() if memory else []
    for item in overflow:
        content = _flat(item.get("content"))
        if not content:
            continue
        if len(content) > line_chars:
            content = content[:line_chars] + "…"
        lines.append(("员工：" if item.get("role") == "user" else "助手：") + content)
    return _fit(lines, limit)


def _summary(memory: str, overflow: list[dict], limit: int, message_chars: int,
             model: tuple[object, ModelConfig], rec: RunRecorder) -> str:
    chat_model, cfg = model
    human = f"【已有摘要】\n{memory or '（无）'}\n\n【新移出的对话】\n{_transcript(overflow, message_chars)}"
    text = invoke_text(chat_model, cfg, [("system", SUMMARY_PROMPT.format(limit=limit)), ("human", human)],
                       rec, NODE)
    return text[:limit]


def _facts(memory: str, overflow: list[dict], limit: int, message_chars: int,
           model: tuple[object, ModelConfig], rec: RunRecorder) -> str:
    chat_model, cfg = model
    human = f"【已有要点】\n{memory or '（无）'}\n\n【新移出的对话】\n{_transcript(overflow, message_chars)}"
    out = invoke_json(chat_model, cfg, [("system", FACTS_PROMPT.format(limit=limit, fact_chars=FACT_CHARS)),
                                        ("human", human)], rec, NODE)
    facts = [_flat(f)[:FACT_CHARS] for f in (out.get("facts") or []) if isinstance(f, str) and _flat(f)]
    if not facts:
        raise ModelCallError("要点提取没有输出要点")
    return _fit([f"- {f}" for f in facts], limit)


def compress(mode: str, memory: str, overflow: list[dict], *, limit: int, line_chars: int, message_chars: int,
             model: tuple[object, ModelConfig] | None, rec: RunRecorder) -> tuple[str, str]:
    """返回 (新记忆, 实际使用的方式)。"""
    if mode in (SUMMARY, FACTS) and model is not None:
        try:
            fn = _summary if mode == SUMMARY else _facts
            return fn(memory, overflow, limit, message_chars, model, rec), mode
        except ModelCallError:
            pass
    return truncate(memory, overflow, limit, line_chars), TRUNCATE
