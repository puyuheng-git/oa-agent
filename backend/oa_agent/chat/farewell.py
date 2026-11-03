"""`/chat` 迁移提示页（STD-009：员工对话 UI 迁至独立静态仓库）。"""

from __future__ import annotations

import html


def build_farewell_html(chat_ui_base_url: str | None) -> str:
    """生成中文迁移说明 HTML（内联样式，无外部依赖）。"""
    url = (chat_ui_base_url or "").strip().rstrip("/")
    if url:
        safe_href = html.escape(url, quote=True)
        safe_text = html.escape(url)
        entry = (
            f"<p>员工对话页已迁至独立站点，请使用新地址打开：</p>"
            f'<p><a class="link" href="{safe_href}/" rel="noopener noreferrer">{safe_text}/</a></p>'
            "<p>若从 OA 进入，请让 OA 宿主页指向上述地址（或联系管理员更新「员工对话页地址」）。</p>"
        )
    else:
        entry = (
            "<p>员工对话界面已迁出本服务，本地址不再提供对话功能。</p>"
            "<p>请从 <strong>OA 工作台</strong> 中的智能助手入口重新进入；"
            "OA 宿主页会完成身份校验并打开新的对话页。</p>"
            "<p>独立前端仓库：<code>puyuheng-git/oa-agent-chat</code>（由运维部署静态站点）。</p>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>对话页已迁移</title>
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
    .link {{ color: #0068e6; word-break: break-all; }}
    code {{ font-size: 0.9em; background: #eef2f7; padding: 0.1em 0.35em; border-radius: 4px; }}
  </style>
</head>
<body>
  <main class="card">
    <h1>员工对话页已迁移</h1>
    {entry}
  </main>
</body>
</html>"""
