"""`/chat` 迁移告别页 HTML 文案与交互元素。"""

from oa_agent.chat.farewell import build_farewell_html

_REPO_SNIPPET = "puyuheng-git/oa-agent-chat"


def test_farewell_without_ui_url_has_back_action_and_no_repo():
    html = build_farewell_html(None)
    assert _REPO_SNIPPET not in html
    assert "返回 OA" in html
    assert "goBackToOa" in html
    assert 'id="back-fallback"' in html
    assert "打开新对话" not in html


def test_farewell_without_ui_url_empty_string_same_as_none():
    html = build_farewell_html("   ")
    assert _REPO_SNIPPET not in html
    assert "返回 OA" in html


def test_farewell_with_ui_url_primary_link_and_back():
    html = build_farewell_html("https://chat.example.com")
    assert _REPO_SNIPPET not in html
    assert 'href="https://chat.example.com/"' in html
    assert "打开新对话" in html
    assert "返回 OA" in html
    assert "goBackToOa" in html


def test_farewell_strips_trailing_slash_on_base_url():
    html = build_farewell_html("https://chat.example.com/")
    assert 'href="https://chat.example.com/"' in html
    assert "https://chat.example.com//" not in html
