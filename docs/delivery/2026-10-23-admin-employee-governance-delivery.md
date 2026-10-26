# 后台员工治理（Admin Employee Governance）交付（2026-10-23）

| 项 | 内容 |
|----|------|
| 范围 | 平台路线图 **E / C / A** 的管理端统一运营（Task G1–G7） |
| Spec | `docs/superpowers/specs/2026-10-23-admin-employee-governance-design.md` |
| Plan | `docs/superpowers/plans/2026-10-23-admin-employee-governance.md` |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md` §9 权限表、§12 API 表已补充 employees |

## 功能

- **权限**：`ops.employee.view` / `ops.employee.sensitive` / `ops.employee.manage` 注册于 `perms.py`；超级管理员自动拥有全部。
- **员工目录**：本租户 `agent_chat_thread` / `agent_employee_memory` / `agent_run` 的 `oa` 并集；摘要含最近活跃、会话数、记忆 active 数；`q` 前缀或精确匹配；无痕迹 oa 可空壳进详情。
- **会话 Tab**：列表含软删线程；消息读需 sensitive + 审计；manage 改标题/归档/软删/恢复/batch（仅元数据，**不写 Checkpoint**）。
- **记忆 Tab**：列表默认无正文；`include_text=1` 需 sensitive + 审计；manage 代写/PATCH/软删/restore/清空（敏感校验与员工侧一致）。
- **可见性 Tab**：预览 visible/hidden；按 oa 追加/删除 grant 与 batch grant；Skill 级全量规则仍在 `PUT /v1/admin/skills/{name}/visibility`。
- **管理前端**：菜单「员工治理」→ 目录 + 详情三 Tab（会话 / 记忆 / 可见性）。

## 文件清单

| 类别 | 路径 | 说明 |
|------|------|------|
| 设计 | `docs/design/2026-10-09-oa-langgraph-design.md` | §9、§12 更新 |
| 交付 | `docs/delivery/2026-10-23-admin-employee-governance-delivery.md` | 本文 |
| 权限 | `backend/oa_agent/auth/perms.py` | 三点 employee 权限 |
| API | `backend/oa_agent/admin/employees_api.py` | 目录 + 三 Tab |
| 注册 | `backend/oa_agent/main.py` | `employees_api.router` |
| 可见性 | `backend/oa_agent/mcp/visibility.py` | `add_oa_grant` / `remove_oa_grant` |
| 会话 | `backend/oa_agent/chat/threads.py` | `restore_thread` |
| 记忆 | `backend/oa_agent/chat/memory_store.py` | `list_by_status` / `update_memory` 等 |
| 后端测试 | `backend/tests/test_admin_employees.py` | G1–G5 API（19 用例） |
| 路由/菜单 | `frontend/src/admin/router.ts` | 员工治理入口 |
| 客户端 | `frontend/src/admin/employees.ts`、`employees.spec.ts` | Admin HTTP 映射 |
| 页面 | `frontend/src/admin/views/EmployeesView.vue`、`EmployeeDetailView.vue` | 目录 + 详情 |

## 迁移说明

1. **无新 Alembic 迁移**；复用 E/C/A 已有表与 `agent_skill_visibility_rule`。
2. 部署后需在角色管理中为运营账号勾选 `ops.employee.*`（超管无需改）。
3. 管理前端变更需 `cd frontend && npm run build` 后重启后端以加载静态资源（若同源托管）。

## API 说明

鉴权：管理 session + RBAC；写操作另需 CSRF + `Idempotency-Key` + 审计（审计失败则操作失败）。

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/v1/admin/employees` | view | `q`、`page`、`page_size`（≤100） |
| GET | `/v1/admin/employees/{oa}/threads` | view | Query `status` 含 `deleted` |
| GET | `/v1/admin/employees/{oa}/threads/{thread_id}/messages` | sensitive | 审计 `employee.sensitive.read` |
| PATCH | `/v1/admin/employees/{oa}/threads/{thread_id}` | manage | 标题或 `active`/`archived` |
| DELETE | `/v1/admin/employees/{oa}/threads/{thread_id}` | manage | 软删 + reason |
| POST | `/v1/admin/employees/{oa}/threads/{thread_id}/restore` | manage | 元数据恢复 |
| POST | `/v1/admin/employees/{oa}/threads/batch` | manage | `archive` / `soft_delete` |
| GET | `/v1/admin/employees/{oa}/memory` | view；`include_text=1` → sensitive | 默认 `text: null` |
| POST/PATCH/DELETE | `/v1/admin/employees/{oa}/memory*` | manage | 与 spec §6 一致 |
| GET | `/v1/admin/employees/{oa}/visibility` | view | visible / hidden 预览 |
| POST/DELETE | `/v1/admin/employees/{oa}/visibility/grants` | manage | 单 skill oa 规则 |
| POST | `/v1/admin/employees/{oa}/visibility/grants/batch` | manage | 多 skill 同 effect |

路径 `{oa}` 须与资源行一致；跨 oa 误路径返回 404。

## 权限与安全

- 管理员与员工主体分离；**禁止**写 Checkpoint / LangGraph 状态 / Run 篡改；不访问 `td_oa`。
- sensitive 读成功即审计；manage 写同事务审计；日志/审计不写 office_token、master key；记忆/消息正文默认不进审计 after 全文。
- 可见性 grant 仅追加/删除 `principal_type=oa` 行，避免员工详情页误清空 Skill 全量规则。
- 恢复软删会话 UI 明示 Checkpoint 可能不可续聊。

## 测试结果

| 项 | 结果 | 标注 |
|----|------|------|
| backend `pytest -q`（全量） | **244** collected，exit 0 | **自动化通过** |
| backend `tests/test_admin_employees.py` | **19** 用例 | **自动化通过**（SQLite 内存库 + 管理 session 替身） |
| frontend `npm test`（vitest） | **15** files / **87** tests passed | **自动化通过** |
| frontend `npx vue-tsc --noEmit` | exit 0 | **自动化通过** |
| 手工：浏览器目录 → 详情三 Tab 点通 | 未开浏览器对接真实后端 | **未执行** |
| 手工：OA iframe 员工侧不受管理写影响 | 未接 OA 全链路 | **未执行**（外部依赖未验证） |
| 手工：grant deny 后员工对话 Skill 列表变化 | 未接 OA + 真 LLM | **未执行**（外部依赖未验证） |

禁止将未执行项标为通过。

## 未完成项

- 会话 Tab **改标题** 的管理 UI（API 已有，G6 可选未做）。
- 可见性 **batch grant** 独立按钮（API 已有，前端可用多次单 grant 替代）。
- Profile / 人事 office-api 注入；跨 oa 批量规则；物理删消息行；代员工发消息。
- 与「对话导出」「Skill 管理」页的深链互跳（可后续 UX 抛光）。

## 下一阶段

按 `docs/superpowers/plans/2026-10-23-platform-next-roadmap.md`：**子系统 D**（固定 Workflow：注册表、触发、与 P5 发布配置衔接等）。亦可按需做「治理增强」（导出按 oa、审计筛选 `employee.*` 等），不阻塞 D。

员工治理验收 1–5 建议在真实 OA + 管理账号 + LLM 环境联调并回填上表手工项。
