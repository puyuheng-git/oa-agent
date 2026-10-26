# 员工长期记忆（Employee Memory）交付（2026-10-23）

| 项 | 内容 |
|----|------|
| 范围 | 平台路线图 **A**（Employee Memory）Task 1–6 |
| Spec | `docs/superpowers/specs/2026-10-23-employee-memory-design.md` |
| Plan | `docs/superpowers/plans/2026-10-23-employee-memory.md` |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md` §12 已补充 memory 路径 |

## 功能

- **数据层**：新表 `agent_employee_memory`（迁移 `0010`）；`memory_id` 为 `mem_` + ULID；`kind` ∈ `preference` / `constraint` / `note`；软删 `status=deleted`。
- **领域层**：`chat/memory_store.py` — 显式写入、敏感拒收、满员拒写（默认 50 条 active）、列表分页、单条/一键软删、`forget_by_match`、注入块格式化（固定抬头，默认 800 字预算）。
- **HTTP**：员工 Bearer ticket 下 `GET/DELETE /v1/chat/memory*`；列表仅本人 `active`；他人或已删 id → `404 MEMORY_NOT_FOUND`；清空须 body `{"confirm": true}`。
- **运行时**：`travel_query` 扩展 `memory_write` / `memory_forget` 动作（LLM JSON + 规则路径）；构图前 `_load_long_term_memory` 注入，与 Checkpoint 会话 `memory` **不晋升、不混用**。
- **前端**：Chat 侧栏 / 顶栏次级入口「我的记忆」→ `MemoryPanel.vue`（列表、单条删除、一键清空）；不占欢迎首屏。

## 文件清单

| 类别 | 路径 | 说明 |
|------|------|------|
| 设计 | `docs/design/2026-10-09-oa-langgraph-design.md` | §12 API 表增加 memory |
| 交付 | `docs/delivery/2026-10-23-employee-memory-delivery.md` | 本文 |
| ORM | `backend/oa_agent/db/models.py` | `EmployeeMemory` |
| 迁移 | `backend/migrations/versions/0010_employee_memory.py` | 建表（`down_revision=0009_skill_visibility`） |
| ID | `backend/oa_agent/ids.py` | `new_memory_id()` |
| 领域 | `backend/oa_agent/chat/memory_store.py` | CRUD / 敏感 / 注入 |
| 路由 | `backend/oa_agent/chat/router.py` | memory API |
| 构图 | `backend/oa_agent/runtime/graphs/travel_query.py` | 意图动作 + 注入块 |
| 服务 | `backend/oa_agent/chat/service.py` | `_load_long_term_memory` → `RunContext` |
| 后端测试 | `backend/tests/test_employee_memory.py` | 领域 + API + 图路由（12 用例） |
| Chat API | `frontend/src/chat/api.ts` | `listMemory` / `deleteMemory` / `clearMemory` |
| Chat 测试 | `frontend/src/chat/api.spec.ts` | memory 客户端映射 |
| 面板 | `frontend/src/chat/components/MemoryPanel.vue` | 我的记忆 UI |
| 布局 | `frontend/src/chat/components/AppLayout.vue`、`AppHeader.vue`、`ConversationSidebar.vue` | 入口 |
| 页 | `frontend/src/chat/App.vue` | `memoryOpen` 状态 |

## 迁移说明

1. 部署后端前执行 Alembic 升级至 **`0010_employee_memory`**（在 `0009_skill_visibility` 之后）。
2. **无回填**；空库升级即可。
3. 软删不物理删行；注入与列表仅读 `active`。
4. 若同源托管 Chat，建议 `cd frontend && npm run build` 后重启后端以加载新静态资源。

## API 说明

鉴权：与现网一致，`Authorization: Bearer`（chat ticket）；身份仅来自服务端 session，**不信任**客户端自报 `oa`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/chat/memory` | Query：`page`、`page_size`（≤100）；返回 `{items, total, page, page_size}` |
| DELETE | `/v1/chat/memory/{memory_id}` | 软删；`{"ok": true}` |
| DELETE | `/v1/chat/memory` | body `{"confirm": true}` → `{"ok": true, "deleted": N}`；缺 confirm → 422 |

列表项字段：`memory_id`、`kind`、`text`、`created_at`、`updated_at`。

错误：`MEMORY_NOT_FOUND`（404）、`MEMORY_REJECTED`（422，敏感/非法 kind/超长/已满）。

## 权限与安全

- 读写均 **`session.oa == row.oa`**（及 `tenant_id`）；泄露 `memory_id` 无 ticket 仍不可操作。
- 敏感启发式（身份证模式、工资/薪资/银行卡等关键词）拒绝入库；注入抬头声明「不是指令、可能过时」。
- 仅**显式**记忆意图经服务端结构化动作写入；普通对话不得自动晋升长期记忆（D9=A）。
- 本期无 Profile、无 office-api 人事拉取；无管理端记忆 CRUD UI。
- 密钥与 launch 流程不变；管理写接口纪律不套用在员工 memory API 上。

## 测试结果

| 项 | 结果 | 标注 |
|----|------|------|
| backend `pytest -q`（全量） | **221** collected，exit 0 | **自动化通过** |
| backend `tests/test_employee_memory.py` | **12** 用例 | **自动化通过**（含 monkeypatch 图路径，非真 LLM） |
| frontend `npm test`（vitest） | **15** files / **85** tests passed | **自动化通过** |
| frontend `npx vue-tsc --noEmit` | exit 0 | **自动化通过** |
| 手工：OA launch → 「请记住…」→ 新 thread 仍注入 | 未接 OA / 真 LLM / office-api | **未执行**（外部依赖未验证） |
| 手工：浏览器打开「我的记忆」删条/清空 | 未开浏览器 | **未执行** |
| 手工：企微自然语言记住/忘掉（无面板） | 未接企微长连接 | **未执行**（外部依赖未验证） |

禁止将未执行项标为通过。

## 未完成项

- **Profile** 实装与 office-api 人事注入（D8=C，仅预留 ContextPack 插槽）。
- **企微「我的记忆」面板**（D21=B；企微可口语忘掉，网页管理）。
- **从会话压缩自动晋升**长期记忆（D9=A，本期不做）。
- 管理端记忆运营 / 审计事件 `employee.memory.*`（可选，本期未做）。
- 注入条数满时「淘汰最旧」策略（本期写入满员 **拒绝** 并提示清理）。

## 下一阶段（D）

按 `docs/superpowers/plans/2026-10-23-platform-next-roadmap.md`：**子系统 D**（固定 Workflow：注册表、触发、与 P5 发布配置衔接等）。Employee Memory 验收项 1–3 建议在真实 OA + LLM + office-api 环境联调并回填上表手工项。
