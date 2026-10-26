# 前后端对接缺口表（2026-10-22）

对照方式：读代码契约（方案 1）；联调补充标「手工/外部依赖」。

对照依据：`docs/superpowers/specs/2026-10-22-frontend-backend-wiring-design.md` §2 / §4 / §5；前端调用点与后端路由。

判定约定：

- `ok`：method/path 一致，且前端 TypeScript / 页面所用字段可被后端 `_view` / 返回 dict 覆盖（允许前端多声明未用字段；允许后端多返回未用字段）。
- `mismatch`：缺字段导致页面崩溃、写请求未走 `http.ts`、权限点不一致、或明显 404。
- `fe_only` / `be_only`：仅一侧存在。
- `out_of_scope`：C 类本轮不做。

## 管理端

| priority | area | method path | fe 调用点 | be 路由 | status | note | fix_in |
|----------|------|-------------|-----------|---------|--------|------|--------|
| P0 | 鉴权壳 | `POST /v1/admin/auth/login` | `auth.ts` `login` | `auth/admin.py` `login` → `_me` | ok | Cookie + `csrf_token` / `user` / `roles` / `perms` 对齐 | |
| P0 | 鉴权壳 | `GET /v1/admin/auth/me` | `auth.ts` `loadMe` | `auth/admin.py` `me` | ok | 同 `_me`；Layout 据此设 CSRF | |
| P0 | 鉴权壳 | `POST /v1/admin/auth/logout` | `auth.ts` `logout` | `auth/admin.py` `logout` | ok | 经 `http.ts`（CSRF + Idempotency-Key） | |
| P0 | 鉴权壳 | `POST /v1/admin/auth/password` | `LayoutView.vue` | `auth/admin.py` `change_password` | ok | body `old_password` / `new_password` | |
| P0 | 就绪 | `GET /readyz` | `console/telemetry.ts` `fetchReady`；`HomeView` | `main.py` `readyz` | ok | 故意裸 `fetch`：503 仍可读 body；非管理写链 | |
| P1 | 运行 | `GET /v1/admin/runs/stats` | `LayoutView` / `OverviewWings` | `runs_api.stats` | ok | `RunStats` 与 `compute_stats` + `observability` 对齐 | |
| P1 | 运行 | `GET /v1/admin/runs/errors/top` | `OverviewWings` | `runs_api.top` | ok | `{ items, range }` | |
| P1 | 运行 | `GET /v1/admin/runs` | `RunsView` | `runs_api.list` | ok | `RunItem` ↔ `_run_view` | |
| P1 | 运行 | `GET /v1/admin/runs/{run_id}` | `RunDetailView` | `runs_api.run_detail` | ok | 含 `can_cancel` / `can_retry` / `waiting_human` | |
| P1 | 运行 | `GET /v1/admin/runs/{run_id}/events` | `RunDetailView` | `runs_api.run_events` | ok | `RunEvent` ↔ `EVENT_FIELDS`；`has_more` | |
| P1 | 运行 | `POST /v1/admin/runs/{run_id}/cancel` | `RunDetailView` | `runs_api.cancel` | ok | 写链经 `http.ts`；权限 `ops.run.operate` 与按钮 `can(...)` 一致 | |
| P1 | 运行 | `POST /v1/admin/runs/{run_id}/retry` | `RunDetailView` | `runs_api.retry` | ok | 返回 `new_run_id` / `new_run_status` | |
| P1 | 介入 | `GET /v1/admin/interventions` | `InterventionsView`；Layout badge | `interventions_api.list_tasks` | ok | `items` / `total` / `pending_count`；`InterventionTask` ↔ `_view` | |
| P1 | 介入 | `GET /v1/admin/interventions/{task_id}` | `InterventionsView` | `interventions_api.task_detail` | ok | `resumable` / `terminable` | |
| P1 | 介入 | `POST /v1/admin/interventions/{task_id}/resume` | `InterventionsView` `act('resume')` | `interventions_api.resume` | ok | body `reason`+`version`；`user_confirm` → 403；权限 `ops.intervention.handle` | |
| P1 | 介入 | `POST /v1/admin/interventions/{task_id}/terminate` | `InterventionsView` `act('terminate')` | `interventions_api.terminate` | ok | 同上 | |
| P1 | 设置 | `GET /v1/admin/settings` | `SettingsView` | `settings_api.list_groups` | ok | `groups` / `redis_status` / `wecom_status` | |
| P1 | 设置 | `PUT /v1/admin/settings/{group}` | `SettingsView` `save` | `settings_api.update_group` | ok | 密钥只写；`list` 字段后端可接受逗号字符串；返回 `changed`/`group` | |
| P1 | 设置 | `POST /v1/admin/settings/{group}/test` | `SettingsView` `test` | `settings_api.test_group` | ok | 目前仅 redis 可测；其它组 400 `NOT_TESTABLE`（页面按 `testable` 显按钮） | |
| P1 | 设置 | `GET /v1/admin/settings/database` | `SettingsView` | `settings_api.get_database` | ok | `values` + 密码掩码 | |
| P1 | 设置 | `POST /v1/admin/settings/database/test` | `SettingsView` | `settings_api.test_database` | ok | | |
| P1 | 设置 | `PUT /v1/admin/settings/database` | `SettingsView` | `settings_api.update_database` | ok | | |
| P1 | 设置 | `GET /v1/admin/settings/{group}` | — | `settings_api.get_group` | be_only | 前端只拉列表；非闭环必须 | |
| P1 | LLM | `GET /v1/admin/llm/providers` | `LlmView` | `llm_api.list_providers` | ok | `items`；密钥 `vault.describe` 掩码 | |
| P1 | LLM | `POST /v1/admin/llm/providers` | `LlmView` `save` | `llm_api.create_provider` | ok | 写权限 `sys.setting.edit`；经 `http.ts` | |
| P1 | LLM | `PUT /v1/admin/llm/providers/{id}` | `LlmView` `save` | `llm_api.update_provider` | ok | 密钥只写；留空不改 | |
| P1 | LLM | `DELETE /v1/admin/llm/providers/{id}` | `LlmView` | `llm_api.delete_provider` | ok | | |
| P1 | LLM | `POST /v1/admin/llm/providers/{id}/test` | `LlmView` `test` | `llm_api.test_provider` | ok | | |
| P1 | LLM | `GET /v1/admin/llm/models` | `LlmView` | `llm_api.list_models` | ok | `items`；`purpose_tags` 数组 | |
| P1 | LLM | `POST /v1/admin/llm/models` | `LlmView` `save` | `llm_api.create_model` | ok | FE 表单逗号拆分 → 数组 | |
| P1 | LLM | `PUT /v1/admin/llm/models/{id}` | `LlmView` `save` | `llm_api.update_model` | ok | 同上 | |
| P1 | LLM | `DELETE /v1/admin/llm/models/{id}` | `LlmView` | `llm_api.delete_model` | ok | | |
| P1 | LLM | `POST /v1/admin/llm/models/{id}/test` | `LlmView` `test` | `llm_api.test_model` | ok | | |
| P2 | Tool | `GET /v1/admin/tools` | `ToolsView`；`SkillsView` 下拉 | `catalog_api.list_tools` | ok | `items` + `upstreams`；`ToolItem` ↔ `_tool_view` | |
| P2 | Tool | `GET /v1/admin/tools/{name}` | `ToolsView` | `catalog_api.tool_detail` | ok | `versions` / `current_schema` | |
| P2 | Tool | `GET /v1/admin/tools/{name}/diff` | `ToolsView` | `catalog_api.tool_diff` | ok | `changes[].field/change/old/new/breaking` 与 FE `DiffChange` 一致 | |
| P2 | Tool | `POST /v1/admin/tools/sync` | `ToolsView` | `catalog_api.sync_tools` | ok | `{ files, tools }` | |
| P2 | Tool | `POST /v1/admin/tools/import/apipost` | `ToolsView` | `catalog_api.import_apipost` | ok | `{ drafts, errors }` | |
| P2 | Tool | `POST /v1/admin/tools` | `ToolsView` `save` | `catalog_api.create_tool` | ok | 返回 `result`/`version_no`/`tool`；FE 用前两字段 | |
| P2 | Tool | `PUT /v1/admin/tools/{name}` | `ToolsView` `save` | `catalog_api.update_tool` | ok | 同上 | |
| P2 | Tool | `POST /v1/admin/tools/{name}/enable` | `ToolsView` | `catalog_api.enable_tool` | ok | body `{ reason }` | |
| P2 | Tool | `POST /v1/admin/tools/{name}/disable` | `ToolsView` | `catalog_api.disable_tool` | ok | body `{ reason }` | |
| P2 | Tool | `POST /v1/admin/tools/{name}/activate` | `ToolsView` | `catalog_api.activate_tool_version` | ok | | |
| P2 | Tool | `GET /v1/admin/tools/{name}/versions/{version_no}` | — | `catalog_api.tool_version` | be_only | 详情已带 versions；非闭环必须 | |
| P2 | Skill | `GET /v1/admin/skills` | `SkillsView` | `catalog_api.list_skills` | ok | `SkillItem` ↔ `_skill_view` | |
| P2 | Skill | `POST /v1/admin/skills/sync` | `SkillsView` | `catalog_api.sync_skills` | ok | 读 `files[].ok/errors` | |
| P2 | Skill | `POST /v1/admin/skills` | `SkillsView`；`ToolsView` 配套创建 | `catalog_api.create_skill` | ok | 返回完整 `_skill_view` | |
| P2 | Skill | `PUT /v1/admin/skills/{name}` | `SkillsView` `save` | `catalog_api.update_skill` | ok | 同上 | |
| P2 | Skill | `POST /v1/admin/skills/{name}/enable` | `SkillsView` | `catalog_api.enable_skill` | ok | body `{ reason }` | |
| P2 | Skill | `POST /v1/admin/skills/{name}/disable` | `SkillsView` | `catalog_api.disable_skill` | ok | body `{ reason }` | |
| P2 | Skill | `GET /v1/admin/skills/{name}` | — | `catalog_api.skill_detail` | be_only | 列表已够用；非闭环必须 | |
| P2 | Workflow | `GET /v1/admin/workflows/travel_query` | `WorkflowsView` 常量 `WF` | `workflows_api.workflow_detail` | ok | 写死 `travel_query`；**决策 `keep_travel_query`**：契约已对齐、无 mismatch，列表选择属 C 类非必须 | |
| P2 | Workflow | `GET /v1/admin/workflows/travel_query/schema` | `WorkflowsView` | `workflows_api.workflow_schema` | ok | `WorkflowSchema` 对齐 | |
| P2 | Workflow | `GET /v1/admin/workflows/travel_query/diff` | `WorkflowsView` `showDiff` | `workflows_api.workflow_diff` | ok | `changes[].key/old/new` | |
| P2 | Workflow | `PUT /v1/admin/workflows/travel_query/draft` | `WorkflowsView` | `workflows_api.save_draft` | ok | 权限 `ops.config.edit`；body `{ content }` | |
| P2 | Workflow | `DELETE /v1/admin/workflows/travel_query/draft` | `WorkflowsView` | `workflows_api.discard_draft` | ok | 权限 `ops.config.edit` | |
| P2 | Workflow | `POST /v1/admin/workflows/travel_query/draft/validate` | `WorkflowsView` | `workflows_api.validate_draft` | ok | 权限 `ops.config.edit`；读 `validation.ok/errors` | |
| P2 | Workflow | `POST /v1/admin/workflows/travel_query/publish` | `WorkflowsView` | `workflows_api.publish` | ok | 权限 `ops.config.publish`；与按钮 `can(...)` 一致 | |
| P2 | Workflow | `POST /v1/admin/workflows/travel_query/rollback` | `WorkflowsView` | `workflows_api.rollback` | ok | 权限 `ops.config.rollback`；与按钮 `can(...)` 一致 | |
| P2 | Workflow | `GET /v1/admin/workflows` | — | `workflows_api.list_workflows` | be_only | 列表可用；FE 未接；**决策 `keep_travel_query`**（不接 `list_select`） | |
| P2 | 账号 | `GET /v1/admin/accounts` | `AccountsView` | `accounts_api.list_accounts` | ok | `_user_view`；`sys.account.manage`；分页 `page`/`page_size` | |
| P2 | 账号 | `POST /v1/admin/accounts` | `AccountsView` | `accounts_api.create_account` | ok | 经 `http.ts` | |
| P2 | 账号 | `PUT /v1/admin/accounts/{id}` | `AccountsView` | `accounts_api.update_account` | ok | | |
| P2 | 账号 | `POST /v1/admin/accounts/{id}/reset-password` | `AccountsView` | `accounts_api.reset_password` | ok | | |
| P2 | 账号 | `POST /v1/admin/accounts/{id}/unlock` | `AccountsView` | `accounts_api.unlock_account` | ok | | |
| P2 | 角色 | `GET /v1/admin/roles` | `RolesView`；`AccountsView` 下拉 | `accounts_api.list_roles` | ok | `items` | |
| P2 | 角色 | `POST /v1/admin/roles` | `RolesView` | `accounts_api.create_role` | ok | | |
| P2 | 角色 | `PUT /v1/admin/roles/{id}` | `RolesView` | `accounts_api.update_role` | ok | PUT 忽略改 `code`（BE 只改 name/desc/perms） | |
| P2 | 角色 | `DELETE /v1/admin/roles/{id}` | `RolesView` | `accounts_api.delete_role` | ok | | |
| P2 | 角色 | `GET /v1/admin/perms` | `RolesView` | `accounts_api.list_perms` | ok | `{ code, label }` | |
| P2 | 审计 | `GET /v1/admin/audit` | `AuditView` | `audit_api.query_audit` | ok | `ops.audit.view`；`items/total` | |
| P2 | 对话审计 | `GET /v1/admin/conversations` | `ConversationsView` | `conversations_api.list_threads` | ok | `ops.run.view_sensitive`；列表字段对齐 | |
| P2 | 对话审计 | `GET /v1/admin/conversations/{thread_id}` | `ConversationsView` | `conversations_api.thread_detail` | ok | `ThreadDetail` ↔ messages/model_calls/run_status | |
| P2 | 对话审计 | `GET /v1/admin/conversations/export` | `ConversationsView` `exportJsonl` | `conversations_api.export` | ok | Cookie GET 特例（设计允许）；权限 `ops.conversation.export`；错误体可读 | |

## Chat

| priority | area | method path | fe 调用点 | be 路由 | status | note | fix_in |
|----------|------|-------------|-----------|---------|--------|------|--------|
| P0 | 会话 | `POST /v1/chat/session` | `api.ts` `openSession`；`App.vue` | `chat/router.create_session` | ok | `ticket`/`expires_in`/`display_name`/`thread_id` + `_session_extras`（skills/chat/字数/轮询） | |
| P0 | 会话 | `POST /v1/chat/session/refresh` | `api.ts` `refreshSession`；`App.vue` 定时 | `chat/router.refresh` | ok | `{ expires_in }` | |
| P0 | 流式 | `POST /v1/chat/messages/stream` | `api.ts` `sendMessageStream`；`App.vue` 默认路径 | `chat/router.post_message_stream` | ok | SSE：`delta.text`；`done`=完整 MessageResult；`error.code/message`；校验失败仍 JSON 错误。裸 `fetch` 因 SSE（员工 Bearer + body `client_msg_id`） | |
| P0 | 轮询 | `GET /v1/chat/runs/{run_id}` | `api.ts` `getRun`；`App.vue` `pollRun` | `chat/router.get_run` | ok | `run_id`/`run_status`/`done`/`reply` ↔ `RunResult` | |
| P1 | 同步消息 | `POST /v1/chat/messages` | `api.ts` `sendMessage`（封装存在） | `chat/router.post_message` | ok | UI 主路径不用（走 stream）；形状与 stream `done` 同形 | |
| P1 | 会话查询 | `GET /v1/chat/session` | — | `chat/router.get_session` | be_only | 后端有、前端未用；非闭环必须 | |
| P1 | OA mint | `POST /v1/chat/launch` | —（OA 宿主） | `chat/router.launch` | be_only | 员工 SPA 不调；由 OA 服务端 mint `launch_code` | |

> 注：`App.vue` / `Composer` 仍保留 `task_demo` / Mock 入口；默认 `workMode='chat'` 走真实 stream，Mock 不抢主路径（后续 Task 可再弱化）。非 Chat API 契约行，故不列入上表。

## 本轮不做（C / out_of_scope）

| item | reason |
|------|--------|
| `task_demo` / Mock UI 入口弱化 | 非 API；默认已走真实 chat；本轮不改入口（见 Chat 节注） |
| 附件上传 | C；Composer 本地附件仅提示「尚未接入」，只发文本 |
| `/v1/chat/approvals` | C；员工确认另议；`agent/adapter.ts` 明确抛错，禁止接 `/v1/admin/interventions` |
| 侧栏 workspace/documents/knowledge/tools/settings | C；占位「尚未接入」 |
| 多会话服务端持久化 | C；`/v1/chat/threads*` 不接；侧栏会话仅本地内存 |
| 文档预览 / 知识库业务模块 | C |
| 新业务 workflow 图 / 多 workflow 选择（非极小改动） | C；本轮保持 `travel_query` |
| 企微通道改造、多实例部署改造 | C |

## P0/P1：无 mismatch

Task 3（按缺口表修补 P0/P1 mismatch）筛选条件：`priority in (P0, P1)` 且 `status=mismatch`。

结果：**列表为空**。上表管理端 P0/P1 与 Chat P0/P1 行均为 `ok` 或 `be_only`，无 `mismatch`，故无需 Steps 2–4（TDD / 实现 / 改行状态）。若后续同源联调（方案 2）发现环境或字段问题，再回填 `mismatch` 与 `fix_in`。

## P2：无 mismatch + Workflow 决策

Task 4（按缺口表修补 P2 mismatch + Workflow 策略）筛选条件：`priority=P2` 且 `status=mismatch`。

结果：**列表为空**（Tool / Skill / Workflow / 账号 / 角色 / 审计 / 对话审计均为 `ok` 或 `be_only`），无需 TDD / 实现 / 改行状态。

**Workflow 最终决策：`keep_travel_query`**（非 `list_select`）。

原因：`WorkflowsView` 写死 `const WF = '/v1/admin/workflows/travel_query'` 与后端 `workflow_detail` 等路由契约一致，无 mismatch；`GET /v1/admin/workflows` 为 `be_only` 且「本轮不做」已将多 workflow 选择标为 C；Task 1 亦未发现 P2 契约断裂。故不改 `WorkflowsView`，不接入列表选 id。

## 自检摘要

- 无空 `status`。
- 本表**无** `mismatch` 行（代码契约对照未发现 path/method/关键字段/写链/权限点断裂）；若同源联调（方案 2）发现环境或字段问题，再回填并填 `fix_in`。
- C 类均在「本轮不做」，未标入 mismatch。
- 写操作：管理端经 `frontend/src/shared/http.ts`；对话 export / readyz / SSE stream 的裸 `fetch` 为已确认特例。
- 联调状态：本任务为读代码契约；**手工 / 外部依赖（OA launch、office-api、LLM）未验证**。
