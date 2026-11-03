"""`/chat` 迁移提示页（STD-009：员工对话 UI 迁至独立静态仓库）。"""

from __future__ import annotations

import html

_BACK_SCRIPT = """
<script>
function goBackToOa() {
  if (window.history.length > 1) {
    history.back();
    return;
  }
  window.close();
  var el = document.getElementById("back-fallback");
  if (el) el.hidden = false;
}
</script>
"""


def build_farewell_html(
    chat_ui_base_url: str | None,
    *,
    oa_entry_url: str | None = None,
) -> str:
    """生成中文迁移说明 HTML（内联样式，无外部依赖）。

    ``chat_ui_base_url`` 保留供调用方签名稳定；告别页不渲染指向独立 UI 根路径的按钮。
    """
    del chat_ui_base_url
    oa_href_raw = (oa_entry_url or "").strip()
    if oa_href_raw:
        safe_oa = html.escape(oa_href_raw, quote=True)
        oa_btn = f'<a class="btn btn-primary" href="{safe_oa}">回 OA 打开助手</a>'
    else:
        oa_btn = (
            '<a class="btn btn-primary" href="#" onclick="goBackToOa(); return false;">'
            "回 OA 打开助手</a>"
        )
    back_fallback = (
        '<p id="back-fallback" class="hint" hidden>'
        "无法自动返回时，请关闭本窗口或标签页，从 OA 工作台中的智能助手入口重新进入。"
        "</p>"
    )
    body = "<p>请从 OA 工作台的智能助手入口重新进入。</p>"
    entry = (
        f"{body}"
        '<div class="actions">'
        f"{oa_btn}"
        "</div>"
        f"{back_fallback}"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>问答页已迁移</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: #f4f6f9; color: #1a2332;
    }}
    .card {{
      max-width: 32rem; padding: 1.75rem 2rem; background: #fff; border-radius: 12px;
      box-shadow: 0 8px 32px rgba(15, 23, 42, 0.08); line-height: 1.65;
    }}
    h1 {{ font-size: 1.25rem; margin: 0 0 1rem; }}
    .hint {{ font-size: 0.92rem; color: #4a5568; margin-top: 0.75rem; }}
    .actions {{
      display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 1.25rem 0 0.5rem;
    }}
    .btn {{
      display: inline-block; padding: 0.55rem 1.15rem; border-radius: 8px;
      font-size: 0.95rem; font-weight: 500; text-decoration: none; cursor: pointer;
      border: none; line-height: 1.4;
    }}
    .btn-primary {{
      background: #0068e6; color: #fff;
    }}
    .btn-primary:hover {{ background: #0052b8; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>问答页已迁移</h1>
    {entry}
  </main>
{_BACK_SCRIPT}
</body>
</html>"""
