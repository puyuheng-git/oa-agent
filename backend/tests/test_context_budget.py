"""context_budget：估算、预算与压缩优先级。"""

from oa_agent.runtime.context_budget import (
    DEFAULT_MAX_INPUT_TOKENS,
    FALLBACK_MAX_MESSAGE_CHARS,
    MIN_OUTPUT_RESERVE,
    USER_TRUNCATED_SUFFIX,
    entry_max_chars,
    estimate_tokens,
    fit_messages,
    input_budget_tokens,
    max_input_tokens,
    messages_tokens,
    output_reserve_tokens,
    tokens_to_chars,
)


def test_estimate_and_defaults():
    assert estimate_tokens("") == 0
    assert estimate_tokens("ab") == 1
    assert estimate_tokens("abcd") == 2
    assert max_input_tokens(None) == DEFAULT_MAX_INPUT_TOKENS
    assert max_input_tokens({}) == DEFAULT_MAX_INPUT_TOKENS
    assert max_input_tokens({"max_input_tokens": 128000}) == 128000
    assert output_reserve_tokens({}) == MIN_OUTPUT_RESERVE
    assert output_reserve_tokens({"max_tokens": 2000}) == 2000
    assert input_budget_tokens({"max_input_tokens": 10000, "max_tokens": 2000}) == 8000
    assert tokens_to_chars(3) == 6
    assert entry_max_chars(None) == FALLBACK_MAX_MESSAGE_CHARS
    assert entry_max_chars({"max_input_tokens": 1000, "max_tokens": 256}) == tokens_to_chars(1000 - 256)


def test_fit_drops_history_before_user():
    messages = [
        ("system", "SYS" * 100),
        ("human", "old-user-" + ("x" * 200)),
        ("ai", "old-ai-" + ("y" * 200)),
        ("human", "CURRENT-USER-" + ("z" * 200)),
    ]
    # 预算只够 system + 当前用户的一小部分 → 应先丢掉历史
    budget = messages_tokens([messages[0], messages[-1]]) - 5
    out, compressed, user_cut = fit_messages(
        messages, budget_tokens=max(20, budget), history_message_chars=50, compress_truncate_chars=20,
    )
    assert compressed
    roles = [r for r, _ in out]
    assert roles[0] == "system"
    assert roles[-1] == "human"
    assert "CURRENT-USER" in out[-1][1] or USER_TRUNCATED_SUFFIX in out[-1][1]
    # 历史应被删掉或大幅缩短
    assert len(out) <= 3


def test_fit_truncates_user_last_with_suffix():
    messages = [
        ("system", "S" * 400),
        ("human", "U" * 400),
    ]
    out, compressed, user_cut = fit_messages(
        messages, budget_tokens=50, history_message_chars=100, compress_truncate_chars=40,
    )
    assert compressed
    assert user_cut
    assert out[-1][1].endswith(USER_TRUNCATED_SUFFIX.strip()) or USER_TRUNCATED_SUFFIX in out[-1][1]
    assert messages_tokens(out) <= 50 or len(out[-1][1]) < 400


def test_fit_step2_uses_assistant_message_chars():
    """step-2 缩短历史时：ai 用 assistant_message_chars，旧 human 仍用 history_message_chars。"""
    ai_body = "A" * 1500
    human_body = "H" * 200
    messages = [
        ("system", "SYS"),
        ("human", human_body),
        ("ai", ai_body),
        ("human", "current"),
    ]
    # 全量 ~856 tokens；按角色缩短后 human≤50 + ai≤1500 约 781，取中间预算迫使只走 step-2
    budget = 820
    out, compressed, user_cut = fit_messages(
        messages,
        budget_tokens=budget,
        history_message_chars=50,
        compress_truncate_chars=20,
        assistant_message_chars=1500,
    )
    assert compressed
    assert not user_cut
    assert len(out) == 4  # 未整段丢历史
    older_human = next(c for r, c in out[:-1] if r == "human")
    ai_text = next(c for r, c in out if r == "ai")
    assert len(older_human) <= 51
    assert len(ai_text) > 50
    assert len(ai_text) <= 1500
