"""`/chat` 迁移告别页 HTML 文案与交互元素。"""

from oa_agent.chat.farewell import build_farewell_html

_REPO_SNIPPET = "puyuheng-git/oa-agent-chat"


def test_farewell_without_ui_url_has_back_action_and_no_repo():
    html = build_farewell_html(None)
    assert _REPO_SNIPPET not in html
    assert "问答页已迁移" in html
    assert "请从 OA 工作台的智能助手入口重新进入。" in html
    assert "回 OA 打开助手" in html
    assert 'href="#"' in html
    assert "goBackToOa" in html
    assert 'id="back-fallback"' in html
    assert "打开新对话" not in html


def test_farewell_without_ui_url_empty_string_same_as_none():
    html = build_farewell_html("   ")
    assert _REPO_SNIPPET not in html
    assert "回 OA 打开助手" in html


def test_farewell_with_ui_url_does_not_render_secondary_chat_link():
    html = build_farewell_html("https://chat.example.com")
    assert _REPO_SNIPPET not in html
    assert "chat.example.com" not in html
    assert "打开新对话" not in html
    assert "btn-secondary" not in html
    assert "回 OA 打开助手" in html
    assert "goBackToOa" in html


def test_farewell_with_ui_url_trailing_slash_still_no_chat_cta():
    html = build_farewell_html("https://chat.example.com/")
    assert "chat.example.com" not in html
    assert "打开新对话" not in html


def test_farewell_uses_configured_oa_entry_href():
    html = build_farewell_html(None, oa_entry_url="https://oa.example.com/general/ds/agent/")
    assert 'href="https://oa.example.com/general/ds/agent/"' in html
    assert "回 OA 打开助手" in html
    assert 'href="#"' not in html


def test_launch_bridge_error_html_mentions_config():
    from oa_agent.chat.farewell import build_launch_bridge_error_html

    html = build_launch_bridge_error_html()
    assert "无法打开对话页" in html
    assert "chat_ui_base_url" in html
    assert "问答页已迁移" not in html
