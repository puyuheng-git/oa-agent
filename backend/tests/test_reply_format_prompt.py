"""员工可见回复的排版提示：常量内容，以及拼进 allow_chat 系统提示。"""
from oa_agent.runtime.graphs import oa_assistant as m


def test_reply_format_prompt_mentions_mermaid_and_math():
    text = m.REPLY_FORMAT_PROMPT
    assert "mermaid" in text.lower()
    assert "mindmap" in text.lower()
    assert "$" in text or "公式" in text
    assert ":::" in text or "tip" in text.lower()


def test_reply_format_wired_into_oa_assistant_source():
    src = open(m.__file__, encoding="utf-8").read()
    # allow_chat 组装 AGENT_PROMPT 之后必须把排版段拼进 system prompt
    assert "prompt += REPLY_FORMAT_PROMPT" in src
    assert "回复排版" in m.REPLY_FORMAT_PROMPT
