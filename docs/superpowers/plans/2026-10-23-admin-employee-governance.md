# 后台员工治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理端按 `oa` 统一查看/调控员工会话元数据、长期记忆与 Skill 可见性；敏感读审计；不写 Checkpoint。

**Architecture:** 新权限三点 + `/v1/admin/employees*` 路由模块；目录聚合本库痕迹；详情三 Tab API；可见性用「按 oa 追加/删除 grant」避免误清空 Skill 全量规则。管理前端新菜单「员工治理」。

**Tech Stack:** FastAPI、SQLAlchemy 2、既有 admin RBAC、Vue 3 + Element Plus、pytest / vitest。

**Spec:** `docs/superpowers/specs/2026-10-23-admin-employee-governance-design.md`

## Global Constraints

- 与 OA 只走 HTTP；不访问 `td_oa`。
- 禁止读写 Checkpoint / 图状态；恢复软删会话仅改 `agent_chat_thread.status`。
- 管理写 = 权限点 + CSRF + `Idempotency-Key` + 审计；审计失败则失败。
- 敏感读（消息原文、记忆正文）= `ops.employee.sensitive` + 访问即审计。
- 密钥只写不读；审计 after 不落消息/记忆全文（只 id + 操作类型）。
- 回复与文档中文；代码标识符英文。
- 测试不得把未执行说成通过。
- 无 git 时跳过 Commit。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/oa_agent/auth/perms.py` | 注册三权限点 |
| `backend/oa_agent/admin/employees_api.py` | 目录 + 三 Tab API（新建） |
| `backend/oa_agent/main.py` | include router |
| `backend/oa_agent/chat/threads.py` / `memory_store.py` / `mcp/visibility.py` | 复用或薄封装 admin 安全写 |
| `backend/tests/test_admin_employees.py` | API 自动化 |
| `frontend/src/admin/router.ts` + menu | 「员工治理」入口 |
| `frontend/src/admin/employees.ts` + `employees.spec.ts` | API 客户端 |
| `frontend/src/admin/views/EmployeesView.vue` | 目录 |
| `frontend/src/admin/views/EmployeeDetailView.vue` | 三 Tab |
| `docs/design/...` §9/§12；`docs/delivery/2026-10-23-admin-employee-governance-delivery.md` | 文档 |

---

### Task 1: 权限点注册

**Files:**
- Modify: `backend/oa_agent/auth/perms.py`
- Modify: 若有权限列表测试则更新（如 `test_hardening` / accounts）
- Test: `backend/tests/test_admin_employees.py`（本 Task 先测 PERMISSIONS 含新码；或挂到现有 perms 测）

**Interfaces:**
- Produces keys（文案中文）:
  - `ops.employee.view` = `"员工治理：目录与摘要"`
  - `ops.employee.sensitive` = `"员工治理：会话原文与记忆正文（访问即审计）"`
  - `ops.employee.manage` = `"员工治理：写操作"`

- [ ] **Step 1: 写断言 PERMISSIONS 含三键的失败测试 → 追加到 perms.py → PASS**

- [ ] **Step 2: Commit（无 git 跳过）**

说明：`super_admin` 已自动拥有全部 PERMISSIONS；无需迁库。若角色 UI 从 PERMISSIONS 动态渲染，新点会自动出现。

---

### Task 2: 员工目录 API

**Files:**
- Create: `backend/oa_agent/admin/employees_api.py`（先只做 list）
- Modify: `backend/oa_agent/main.py` include
- Test: `backend/tests/test_admin_employees.py`

**Interfaces:**
- `GET /v1/admin/employees?q=&page=&page_size=` → `admin_read("ops.employee.view")`
- 聚合 SQL：union distinct oa from ChatThread / EmployeeMemory / Run（字段名以 models 为准）
- `q`：空=全量分页；非空= `oa.startswith(q)` 或精确（实现选 `like q%`，文档写清）
- 每项：`{oa, last_active_at, thread_count, memory_active_count}`

- [ ] **Step 1: 失败测试（插 thread+memory 后 list 含该 oa）→ 实现 → PASS**

- [ ] **Step 2: Commit（无 git 跳过）**

---

### Task 3: 会话 Tab API

**Files:**
- Modify: `employees_api.py`
- Reuse: `chat/threads.py` 逻辑或 admin 专用函数（必须允许 status=deleted 列表）
- Test: `test_admin_employees.py`

**Interfaces:**
- `GET /{oa}/threads` view；含 deleted
- `GET /{oa}/threads/{thread_id}/messages` **sensitive** + `_audit_sensitive(...)`
- `PATCH /{oa}/threads/{thread_id}` manage：title / status active|archived
- `DELETE /{oa}/threads/{thread_id}` manage：软删
- `POST /{oa}/threads/{thread_id}/restore` manage：body `{status?: "active"|"archived", reason}`
- `POST /{oa}/threads/batch` manage：同 oa 多 id archive|soft_delete
- 所有写：`reason` 必填（≥2 字）；校验 thread.oa == path oa

- [ ] **Step 1: 测试** 无 sensitive 读消息 403；有权限读写审计；restore 后 status=active；**不**调用 checkpointer 写（可用 mock 断言）

- [ ] **Step 2: 实现 → PASS → Commit（跳过若无 git）**

---

### Task 4: 记忆 Tab API

**Files:**
- Modify: `employees_api.py`
- Reuse: `memory_store`（add / soft_delete / clear / reject_sensitive）；admin PATCH 可在 store 增 `update_memory` 或 API 内改字段再校验
- Test: `test_admin_employees.py`

**Interfaces:**
- `GET /{oa}/memory` view：默认无 `text` 或 `text: null`；`?include_text=1` 需 sensitive + 审计
- `POST /{oa}/memory` manage：代写
- `PATCH /{oa}/memory/{memory_id}` manage：kind/text
- `DELETE /{oa}/memory/{memory_id}` manage
- `POST /{oa}/memory/{memory_id}/restore` manage
- `DELETE /{oa}/memory` manage：`{"confirm": true, "reason"}` 清空 active

- [ ] **Step 1: 测试** view 列表无正文；include_text 无敏感权限 403；编辑身份证号拒 422

- [ ] **Step 2: 实现 → PASS → Commit（跳过若无 git）**

---

### Task 5: 可见性预览 + oa grant

**Files:**
- Modify: `employees_api.py`；可选 `visibility.py` 增加 `add_oa_grant` / `remove_oa_grant`
- Test: `test_admin_employees.py`

**Interfaces:**
- `GET /{oa}/visibility` view → `{visible:[{name,display_name}], hidden:[{name,reason}]}`
- `POST /{oa}/visibility/grants` manage `{skill_name, effect, reason}` 幂等追加
- `DELETE /{oa}/visibility/grants` manage `{skill_name, effect?, reason}` 删该 oa 行
- `POST /{oa}/visibility/grants/batch` manage `{skill_names, effect, reason}`
- **禁止**在此路径全量 replace 某 skill 全部规则

- [ ] **Step 1: 测试** grant deny 后 preview 进 hidden；另一 oa 不受影响

- [ ] **Step 2: 实现 → PASS → Commit（跳过若无 git）**

---

### Task 6: 管理前端

**Files:**
- Modify: `frontend/src/admin/router.ts`（及菜单数据源，与 Conversations 同模式）
- Create: `employees.ts`、`employees.spec.ts`、`EmployeesView.vue`、`EmployeeDetailView.vue`
- 入口 perm：目录用 `ops.employee.view`；写按钮按 `manage`；看正文按 `sensitive`（无权限显示「无权限」不假数据）

**UI 要点：**
- 目录：搜索 + 表格；点行进详情
- 详情 Tabs：会话（含已删标记、恢复确认文案）、记忆（正文按权加载）、可见性（预览 + 快捷 allow/deny）
- 恢复会话对话框提示 Checkpoint 不保证

- [ ] **Step 1: vitest 覆盖 employees.ts 请求形状 → 实现页面 → `npm test` + `vue-tsc --noEmit`**

- [ ] **Step 2: Commit（跳过若无 git）**

---

### Task 7: 文档 + 全量测试

**Files:**
- Modify: `docs/design/2026-10-09-oa-langgraph-design.md` §9 权限表 + §12 API
- Create: `docs/delivery/2026-10-23-admin-employee-governance-delivery.md`

- [ ] **Step 1: 写交付（诚实分类；下一阶段可写路线图 D 或「治理增强」）**

- [ ] **Step 2:**

```bash
cd backend && .venv\Scripts\python -m pytest -q
cd frontend && npm test && npx vue-tsc --noEmit
```

- [ ] **Step 3: Commit（跳过若无 git）**

---

## Spec coverage

| Spec | Task |
|------|------|
| 三权限点 | 1 |
| 目录聚合 | 2 |
| 会话读写/恢复/批量 | 3 |
| 记忆读写/敏感 | 4 |
| 可见性 preview + grant | 5 |
| 管理 UI | 6 |
| 文档与全量 | 7 |
| Checkpoint 禁写 | 3 测试断言 + Global |

## Self-review

- 跨 oa 批量明确不做。
- grant API 不替代 Skill 级 PUT。
- 无 TBD。
