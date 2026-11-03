# STD-009 编排侧：员工对话 UI 外置

**日期：** 2026-11-03  
**范围：** 本仓库（oa-langGraph）仅保留编排与 `/v1/chat/*`；员工 Q&A 静态 UI 迁至 `puyuheng-git/oa-agent-chat`。

## 变更摘要

| 项 | 说明 |
|----|------|
| `/chat`、`/chat/` | 不再挂载 chat SPA；返回中文**迁移提示页**（非 404、非重定向进旧壳） |
| `SPA_ENTRIES` | 仅 `setup`、`admin`；`embed.js` 与 `/assets` 不变 |
| CORS | 环境变量 `OA_AGENT_CHAT_CORS_ORIGINS`（逗号分隔 Origin），作用于 `/v1/chat/*`，支持 `Authorization: Bearer` 与 SSE |
| 后台配置 | OA 组新增 `chat_ui_base_url`（员工对话页地址）；留空时提示页只说明从 OA 入口进入 |
| `/v1/chat/*` | 契约与业务语义未改；launch / session / messages / stream / threads / memory 等保持 |

## 配置键

| 键 | 位置 | 说明 |
|----|------|------|
| `OA_AGENT_CHAT_CORS_ORIGINS` | 进程环境（`AppSettings.chat_cors_origins`） | 例：`https://chat.example.com,https://chat-staging.example.com` |
| `chat_ui_base_url` | 管理后台 → 业务上游 / OA 组 | 独立静态站基址；OA iframe 应指向此外部 URL |
| `allowed_frame_origins` | 同上（原有） | 仍用于 `/chat` 迁移页的 `frame-ancestors`（若 OA 仍嵌入本机 `/chat` 提示页） |

## 验证步骤

1. **迁移页：** 启动已安装实例，`GET /chat/` 应见「员工对话页已迁移」文案；即使 `frontend/dist/chat/index.html` 存在也不应返回旧 SPA。
2. **API：** `POST /v1/chat/launch` → `POST /v1/chat/session` → 带 `Authorization: Bearer <ticket>` 调 `/v1/chat/session` 等，行为与改前一致（自动化：`backend/tests/test_chat*.py`）。
3. **CORS：** 设置 `OA_AGENT_CHAT_CORS_ORIGINS=https://<静态站 origin>`，从该 Origin 对 `/v1/chat/*` 发 `OPTIONS` 预检应 204 并带 `Access-Control-Allow-Origin`；未列入的 Origin 预检 403。
4. **Admin/Setup：** `/admin/`、`/setup/` 仍正常挂载；未改 WeCom 渠道逻辑。

## 测试结果

| 类型 | 结果 |
|------|------|
| 自动化 | `uv run pytest backend/tests/test_chat.py backend/tests/test_chat_cors.py`（本交付执行） |
| 与独立静态站联调 | 未执行（依赖 `oa-agent-chat` 部署与 OA 宿主页改 URL） |

## 未完成 / 后续

- OA 宿主页 / 挂件 iframe 改指向 `chat_ui_base_url` 或静态站 URL（OA 侧，非本切片）。
- 前端源码从本仓库 `frontend/src/chat` 迁出至 `oa-agent-chat`（并行任务）。
