"""模型上下文预算：估算 Token、计算可用输入、超限时按优先级压缩 messages。

约定（grill-me / OpenSpec model-context-budget）：
- max_input_tokens 来自模型 params_json，未配置默认 100_000
- 可用输入 = max_input_tokens - max(max_tokens, MIN_OUTPUT_RESERVE)
- 估算：chars ≈ tokens × CHARS_PER_TOKEN（默认 2），不引入 tiktoken
- 压缩顺序：丢最旧历史 → 缩短历史/记忆 → 尽量保留 system → 最后截本条 human
"""

from __future__ import annotations

from typing import Any

DEFAULT_MAX_INPUT_TOKENS = 100_000
FALLBACK_MAX_MESSAGE_CHARS = 100_000
CHARS_PER_TOKEN = 2
MIN_OUTPUT_RESERVE = 256
USER_TRUNCATED_SUFFIX = "\n\n…（上下文过长，本条输入已截断）"
COMPRESSED_NOTE = "（上下文已按模型窗口压缩）"


def estimate_tokens(text: str | None) -> int:
    """按字符粗估 token 数；空串为 0。"""
    if not text:
        return 0
    # 向上取整：len/2，至少 1
    return max(1, (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN)


def tokens_to_chars(tokens: int) -> int:
    return max(0, int(tokens)) * CHARS_PER_TOKEN


def max_input_tokens(params: dict[str, Any] | None) -> int:
    raw = (params or {}).get("max_input_tokens")
    if raw is None or raw == "":
        return DEFAULT_MAX_INPUT_TOKENS
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_INPUT_TOKENS


def output_reserve_tokens(params: dict[str, Any] | None) -> int:
    raw = (params or {}).get("max_tokens")
    if raw is None or raw == "":
        return MIN_OUTPUT_RESERVE
    try:
        return max(MIN_OUTPUT_RESERVE, int(raw))
    except (TypeError, ValueError):
        return MIN_OUTPUT_RESERVE


def input_budget_tokens(params: dict[str, Any] | None) -> int:
    """可供 prompt（含 system/history/user）使用的 token 上限。"""
    return max(1, max_input_tokens(params) - output_reserve_tokens(params))


def entry_max_chars(params: dict[str, Any] | None = None) -> int:
    """入口层滥用上限：模型预算字符数与 FALLBACK 取较小者；无模型时用 FALLBACK。"""
    if params is None:
        return FALLBACK_MAX_MESSAGE_CHARS
    budget_chars = tokens_to_chars(input_budget_tokens(params))
    return min(FALLBACK_MAX_MESSAGE_CHARS, max(1, budget_chars))


def messages_tokens(messages: list[tuple[str, str]]) -> int:
    return sum(estimate_tokens(content) for _, content in messages)


def _shrink_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1] + "…"


def _history_role_char_limit(role: str, history_message_chars: int, ai_history_chars: int) -> int:
    """历史消息按角色选用字数上限：助手可用更大明细预算。"""
    if role in ("ai", "assistant"):
        return ai_history_chars
    return history_message_chars


def _tokens_after_role_history_limits(
    messages: list[tuple[str, str]],
    *,
    history_message_chars: int,
    ai_history_chars: int,
) -> int:
    """估算按角色上限缩短历史后的 token（保留 system 头与末条 human）。"""
    n = len(messages)
    total = 0
    for idx, (role, content) in enumerate(messages):
        is_tail_human = idx == n - 1 and role == "human"
        is_head_system = idx == 0 and role == "system"
        if is_tail_human or is_head_system:
            total += estimate_tokens(content)
            continue
        limit = _history_role_char_limit(role, history_message_chars, ai_history_chars)
        total += estimate_tokens(_shrink_text(content, limit))
    return total


def fit_messages(
    messages: list[tuple[str, str]],
    *,
    budget_tokens: int,
    history_message_chars: int = 600,
    compress_truncate_chars: int = 80,
    assistant_message_chars: int | None = None,
) -> tuple[list[tuple[str, str]], bool, bool]:
    """将 messages 压入预算。

    messages 约定：若干 (role, content)，通常以 system 开头、以当前 human 结尾；
    中间为历史 human/ai。

    assistant_message_chars：助手历史明细上限（可选）；未传则与 history_message_chars 相同。

    返回 (新 messages, 是否发生压缩, 是否截断了末条用户输入)。
    """
    if budget_tokens <= 0:
        budget_tokens = 1
    out = [(role, str(content or "")) for role, content in messages]
    compressed = False
    user_truncated = False
    # 助手侧可用更大明细预算；未配置时与员工历史上限一致
    ai_history_chars = assistant_message_chars if assistant_message_chars is not None else history_message_chars

    def total() -> int:
        return messages_tokens(out)

    if total() <= budget_tokens:
        return out, False, False

    # 1) 丢最旧的历史（保留首条 system 与末条 human）；
    #    若仅按角色缩短即可入预算，则停丢、交给 step-2，避免整段丢掉助手明细
    while total() > budget_tokens and len(out) > 2:
        shrunk_tokens = _tokens_after_role_history_limits(
            out,
            history_message_chars=history_message_chars,
            ai_history_chars=ai_history_chars,
        )
        if shrunk_tokens <= budget_tokens:
            break
        # 找第一条非 system、且不是最后一条的历史
        drop_at = None
        for i in range(len(out) - 1):
            if out[i][0] == "system" and i == 0:
                continue
            if i == 0 and out[i][0] == "system":
                continue
            # 跳过唯一 system 头
            if out[i][0] == "system":
                continue
            drop_at = i
            break
        if drop_at is None:
            break
        del out[drop_at]
        compressed = True

    if total() <= budget_tokens:
        return out, compressed, user_truncated

    # 2) 按角色缩短历史：human→history_message_chars，ai→assistant_message_chars；
    #    仍超预算再统一压到 compress_truncate_chars
    for fallback_limit in (None, compress_truncate_chars):
        if total() <= budget_tokens:
            break
        new_out: list[tuple[str, str]] = []
        for idx, (role, content) in enumerate(out):
            is_tail_human = idx == len(out) - 1 and role == "human"
            is_head_system = idx == 0 and role == "system"
            if is_tail_human or is_head_system:
                new_out.append((role, content))
            else:
                # 首轮按角色分上限；次轮双方都压到 compress_truncate_chars
                if fallback_limit is not None:
                    limit = fallback_limit
                else:
                    limit = _history_role_char_limit(role, history_message_chars, ai_history_chars)
                shrunk = _shrink_text(content, limit)
                if shrunk != content:
                    compressed = True
                new_out.append((role, shrunk))
        out = new_out

    if total() <= budget_tokens:
        return out, compressed, user_truncated

    # 3) 压缩 system 中偏长的尾部（尽量保留前部规则）；仍超则继续
    if out and out[0][0] == "system" and total() > budget_tokens:
        role, sys_text = out[0]
        # 给尾部 human 预留至少一部分字符
        other = messages_tokens(out[1:])
        remain = max(64, budget_tokens - other)
        max_sys_chars = tokens_to_chars(remain)
        if len(sys_text) > max_sys_chars:
            out[0] = (role, _shrink_text(sys_text, max_sys_chars))
            compressed = True

    if total() <= budget_tokens:
        return out, compressed, user_truncated

    # 4) 最后截断本条用户输入
    if out and out[-1][0] == "human" and total() > budget_tokens:
        role, user_text = out[-1]
        other = messages_tokens(out[:-1])
        remain = max(16, budget_tokens - other)
        max_user_chars = tokens_to_chars(remain)
        suffix = USER_TRUNCATED_SUFFIX
        body_budget = max(0, max_user_chars - len(suffix))
        new_user = _shrink_text(user_text, body_budget) + suffix
        out[-1] = (role, new_user)
        compressed = True
        user_truncated = True

    return out, compressed, user_truncated
