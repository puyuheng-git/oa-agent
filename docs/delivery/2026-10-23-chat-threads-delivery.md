# 员工历史会话（Chat Threads）交付（2026-10-23）

| 项 | 内容 |
|----|------|
| 范围 | 平台路线图 **E**（Chat Threads）Task 1–8 |
| Spec | `docs/superpowers/specs/2026-10-23-chat-threads-design.md` |
| Plan | `docs/superpowers/plans/2026-10-23-chat-threads.md` |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md` §12 已补充 threads 路径 |

## 功能

- **数据层**：新表 `agent_chat_thread`（迁移 `0008`）；可选从 `agent_conversation_message` 回填历史线程元数据。
- **领域层**：`chat/threads.py` — 创建、列表（按 `oa` 隔离）、归属校验、重命名/归档、软删、发消息 touch（标题截断 40 字、`last_message_at` / 渠道）。
- **HTTP**：员工 Bearer ticket 下 `/v1/chat/threads*`、`POST /v1/chat/session/switch`；`POST /v1/chat/session` 可选 `thread_id` 续聊；发消息仍用 session 当前 `thread_id`。
- **运行时**：同 `thread_id` 续聊承接 LangGraph Checkpoint（集成测试覆盖）。
- **渠道**：网页 session 与企微首聊均 `ensure_thread` 写线程行；**网页与企微共用同一 `oa` 列表**（D2=A）。
- **前端**：Chat 侧栏对接服务端线程（列表、新建、切换、历史、重命名、软删）；默认 launch 仍为新会话欢迎态（D3=A）。

## 文件清单

| 类别 | 路径 | 说明 |
|------|------|------|
| 设计 | `docs/design/2026-10-09-oa-langgraph-design.md` | §12 API 表增加 threads / switch |
| 交付 | `docs/delivery/2026-10-23-chat-threads-delivery.md` | 本文 |
| ORM | `backend/oa_agent/db/models.py` | `ChatThread` |
| 迁移 | `backend/migrations/versions/0008_chat_thread.py` | 建表 + 可选回填 |
| 领域 | `backend/oa_agent/chat/threads.py` | 线程 CRUD / touch |
| 路由 | `backend/oa_agent/chat/router.py` | threads API、session `thread_id`、switch |
| 发消息 | `backend/oa_agent/chat/service.py` | `touch_on_user_message` |
| 企微 | `backend/oa_agent/channels/wecom.py` | 新建 session 时 `ensure_thread` |
| 后端测试 | `backend/tests/test_chat_threads.py` | 领域 + HTTP + checkpoint 续聊 |
| 企微测试 | `backend/tests/test_wecom.py` | 断言 `ChatThread` 行 |
| Chat API | `frontend/src/chat/api.ts` | threads / switch 客户端 |
| Chat 测试 | `frontend/src/chat/api.spec.ts` | API 映射与辅助函数 |
| Chat 页 | `frontend/src/chat/App.vue` | 侧栏与服务端线程集成 |
| 侧栏 | `frontend/src/chat/components/ConversationSidebar.vue` | 标题、渠道、相对时间 |
| 类型 | `frontend/src/chat/types.ts` | `LocalConversation` 对齐 |
| HTTP | `frontend/src/shared/http.ts` | `PATCH` 方法 |

## 迁移说明

1. 部署后端前执行 Alembic 升级至 **`0008_chat_thread`**（在既有 `0007_conversation_log` 之后）。
2. 升级会从消息表**可选回填**已有 `thread_id` 的线程行；空库或无历史消息时跳过，不失败。
3. **无 Redis / 前端构建变更要求**；若同源托管 Chat，建议 `cd frontend && npm run build` 后重启后端以加载新静态资源。
4. 软删仅改 `status=deleted`，不物理删消息与 Checkpoint。

## API 说明

鉴权：与现网一致，`Authorization: Bearer`（chat ticket）；身份仅来自服务端 session，**不信任**客户端自报 `oa`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/chat/threads` | Query：`status`（`active`/`archived`，默认 active）、`page`、`page_size`（≤100） |
| POST | `/v1/chat/threads` | 新建线程；session 当前 `thread_id` 切到新线程 |
| GET | `/v1/chat/threads/{thread_id}/messages` | 消息分页（本人且未 deleted） |
| PATCH | `/v1/chat/threads/{thread_id}` | `title`、`status`（`active`↔`archived`） |
| DELETE | `/v1/chat/threads/{thread_id}` | 软删，`{"ok": true}` |
| POST | `/v1/chat/session/switch` | body `{ "thread_id" }`，校验归属后更新 Redis session |
| POST | `/v1/chat/session` | 可选 body `thread_id` 续聊；省略则新建线程行（D3=A） |

错误：`THREAD_NOT_FOUND` → 404（不存在、非本人、已 deleted）。

## 权限与安全

- 列表与读写均 **`session.oa == thread.oa`**（及 `tenant_id`）；泄露 `thread_id` 无 ticket 仍不可读。
- 软删对员工不可见；管理员对话导出/审计仍可见历史消息（若原通道已记录）。
- 无新管理端写接口；不修改 Checkpoint 管理 UI；密钥与 launch 流程不变。
- 发消息前 `guard_message` 校验当前 `thread_id` 归属且未 deleted；`touch` 的 `THREAD_NOT_FOUND` 向上抛出，不与 DB 故障混吞。其它 touch/元数据异常仅记日志，不阻断对话（与 spec 一致）。
- `ensure_thread` 对已 deleted 行同样 opaque 404，不复活。

## 测试结果

| 项 | 结果 | 标注 |
|----|------|------|
| backend `pytest -q`（全量） | **198** collected，exit 0（含软删发消息 / ensure_thread deleted 闭合） | **自动化通过** |
| frontend `npm test`（vitest） | **15** files / **84** tests passed | **自动化通过**（Task 8） |
| frontend `npx vue-tsc --noEmit` | exit 0 | **自动化通过**（Task 8） |
| 手工：OA launch → 侧栏多会话 → SSE 续聊 | 未接 OA / LLM / office-api | **未执行**（外部依赖未验证） |
| 手工：企微发消息后网页侧栏可见同 oa 线程 | 未接企微长连接 | **未执行**（外部依赖未验证） |
| 手工：同源 build 后 Chat 侧栏 UI | 未开浏览器 | **未执行** |
| touch DB 失败时对话仍成功 | 未 mock 故障 | **未执行** |

禁止将未执行项标为通过。

## 未完成项

- **企微侧历史会话列表 UI**（spec §7：企微可无完整侧栏；后端已写线程，网页可见企微来源标签）。
- 侧栏**归档筛选** UI（API 支持 `status=archived`，前端当前默认 active 列表）。
- 侧栏列表**分页加载**（前端 `page_size=50` 单页）；超长消息历史**游标翻页** UI。
- 切换线程时的全局 loading / 骨架（现防重复点击，无显式 loading）。
- 附件、审批、侧栏 workspace 等 wiring 交付中的 **C 类**（见 `docs/delivery/2026-10-22-wiring-delivery.md`）。

## 下一阶段（C）

按 `docs/superpowers/plans/2026-10-23-platform-next-roadmap.md`：**子系统 C**（MCP / Skill 可见权限、多 Domain 等）。Chat Threads 验收项 1–3 建议在真实 OA + LLM + office-api（及可选企微）环境做方案 2 联调并回填上表手工项。
