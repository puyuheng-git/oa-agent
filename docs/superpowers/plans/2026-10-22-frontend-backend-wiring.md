# 前后端对接闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在同源托管下验通并修补管理端契约 + 员工 Chat 真实流式主路径，达到 spec 验收；不实现 C 类扩展。

**Architecture:** 以契约对照为主：对照前端调用与后端路由/响应形状，优先改前端适配；Chat 默认 `workMode=chat` 走 `sendMessageStream`，Mock 仅限 `task_demo`；管理写请求统一走 `shared/http.ts`。卡壳时同源联调（方案 2）。

**Tech Stack:** Vue 3 + Element Plus + Vitest；FastAPI `oa_agent` + pytest；前端构建产物 `frontend/dist` 由后端静态托管。

**Spec:** `docs/superpowers/specs/2026-10-22-frontend-backend-wiring-design.md`

## Global Constraints

- 权威设计：`docs/design/2026-10-09-oa-langgraph-design.md`；冲突以该文档为准。
- 不做 C 类：附件上传、员工审批 API、多会话持久化、侧栏业务模块、企微改造。
- 管理员与员工两套主体：禁止把 `/v1/admin/interventions` 接到员工批准按钮。
- 密钥只写不读；无数据「暂无数据 / 未检测」；不伪造指标。
- 管理写：权限 + CSRF + `Idempotency-Key` + 审计。
- 测试结果必须区分：自动化通过 / 手工 / 未执行 / 外部依赖未验证。
- 提交：仅在用户明确要求时 `git commit`（计划中的 Commit 步骤执行前须确认）；默认可暂存改动不提交。
- 验收路径：只起后端，打开同源 `/admin/`、`/chat/?launch=`。

## File map（预期触及）

| 路径 | 职责 |
|------|------|
| `docs/delivery/2026-10-22-wiring-gap-table.md` | 缺口表（本轮产出） |
| `docs/delivery/2026-10-22-wiring-delivery.md` | 交付说明 |
| `frontend/src/chat/App.vue` | 默认真实发送路径；Mock 门控 |
| `frontend/src/chat/workMode.ts` | 纯函数：是否走 Mock（可单测） |
| `frontend/src/chat/workMode.spec.ts` | 门控单测 |
| `frontend/src/chat/components/Composer.vue` | 模式文案 |
| `frontend/src/chat/components/ConversationSidebar.vue` | 本地会话提示 |
| `frontend/src/chat/api.ts` / `api.spec.ts` | 契约字段与 SSE；仅在缺口时改 |
| `frontend/src/admin/views/*.vue` / `admin/*.ts` | 仅在缺口表标明 mismatch 时改 |
| `backend/oa_agent/**` | 仅薄修复（字段/错误码/SSE）；不扩功能 |
| `frontend/dist/**` | `npm run build` 产物 |

---

### Task 1: 产出缺口表（契约对照）

**Files:**
- Create: `docs/delivery/2026-10-22-wiring-gap-table.md`
- Read: `frontend/src/admin/**/*.vue`、`frontend/src/admin/*.ts`、`frontend/src/chat/api.ts`、`frontend/src/shared/http.ts`
- Read: `backend/oa_agent/main.py`、`backend/oa_agent/admin/*_api.py`、`backend/oa_agent/chat/router.py`

**Interfaces:**
- Consumes: spec §4 矩阵、§5 Chat 主路径
- Produces: 缺口表，每行含 `priority` / `area` / `fe` / `be` / `status`（`ok` \| `mismatch` \| `fe_only` \| `be_only` \| `out_of_scope`）/ `note` / `fix_in`

- [ ] **Step 1: 创建缺口表骨架**

写入 `docs/delivery/2026-10-22-wiring-gap-table.md`，至少包含下列章节与表头：

```markdown
# 前后端对接缺口表（2026-10-22）

对照方式：读代码契约（方案 1）；联调补充标「手工/外部依赖」。

## 管理端

| priority | area | method path | fe 调用点 | be 路由 | status | note | fix_in |
|----------|------|-------------|-----------|---------|--------|------|--------|

## Chat

| priority | area | method path | fe 调用点 | be 路由 | status | note | fix_in |
|----------|------|-------------|-----------|---------|--------|------|--------|

## 本轮不做（C / out_of_scope）

| item | reason |
|------|--------|
| 附件上传 | C |
| /v1/chat/approvals | C；员工确认另议 |
| 侧栏 workspace/documents/knowledge/tools/settings | C |
| 多会话服务端持久化 | C |
```

- [ ] **Step 2: 填管理端行**

按 spec §4.1 为每条 API 填一行。`status=ok` 当：前端 path/method 与后端路由一致，且 TypeScript 接口字段能被后端 `_view` / 返回 dict 覆盖（允许前端多声明未用字段）。`mismatch` 当：缺字段导致页面崩溃、写请求未走 `http.ts`、权限点不一致、或明显 404。`fe_only` / `be_only` 按字面。Workflow 写死 `travel_query`：若后端 `GET /v1/admin/workflows` 可用，标 `ok` 并 note「可后续改列表选择，本轮非必须」；不要标成阻塞 mismatch。

- [ ] **Step 3: 填 Chat 行**

至少覆盖：

| method path | 期望 fe |
|-------------|---------|
| `POST /v1/chat/session` | `openSession` |
| `POST /v1/chat/session/refresh` | `refreshSession` |
| `POST /v1/chat/messages/stream` | `sendMessageStream` |
| `GET /v1/chat/runs/{run_id}` | `getRun` |
| `POST /v1/chat/messages` | 封装存在、UI 主路径不用 → `ok` + note |
| `GET /v1/chat/session` | 后端有、前端未用 → `be_only` 或 `ok`+note「非闭环必须」 |

对照 `ChatSessionInfo` / `MessageResult` / `RunResult` 与 `chat/router.py` 返回键；SSE：`delta.text`、`done`=完整结果、`error.code/message`。

- [ ] **Step 4: 自检缺口表**

确认无空 `status`；每个 `mismatch` 有 `fix_in` 指向具体文件；C 类不进 mismatch。

- [ ] **Step 5: Commit（仅用户要求时）**

```bash
git add docs/delivery/2026-10-22-wiring-gap-table.md
git commit -m "$(cat <<'EOF'
docs: add frontend-backend wiring gap table

EOF
)"
```

---

### Task 2: Chat 主路径门控（Mock 不抢默认）

**Files:**
- Create: `frontend/src/chat/workMode.ts`
- Create: `frontend/src/chat/workMode.spec.ts`
- Modify: `frontend/src/chat/App.vue`
- Modify: `frontend/src/chat/components/Composer.vue`
- Modify: `frontend/src/chat/components/ConversationSidebar.vue`

**Interfaces:**
- Consumes: `WorkMode` from `frontend/src/chat/types.ts`（`'chat' | 'task_demo'`）
- Produces:
  - `export function usesMockAgent(mode: WorkMode): boolean` — `true` 仅当 `mode === 'task_demo'`
  - `export function usesLiveStream(mode: WorkMode): boolean` — `true` 当 `mode === 'chat'`

- [ ] **Step 1: 写失败单测**

创建 `frontend/src/chat/workMode.spec.ts`：

```typescript
import { describe, expect, it } from 'vitest'
import { usesLiveStream, usesMockAgent } from './workMode'

describe('workMode', () => {
  it('chat 走真实流式，不走 Mock', () => {
    expect(usesLiveStream('chat')).toBe(true)
    expect(usesMockAgent('chat')).toBe(false)
  })
  it('task_demo 走 Mock，不要求真实流式门控为假时仍可本地演示', () => {
    expect(usesMockAgent('task_demo')).toBe(true)
    expect(usesLiveStream('task_demo')).toBe(false)
  })
})
```

- [ ] **Step 2: 跑测确认失败**

Run: `cd frontend && npm run test -- src/chat/workMode.spec.ts`  
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `workMode.ts`**

```typescript
import type { WorkMode } from './types'

export function usesMockAgent(mode: WorkMode): boolean {
  return mode === 'task_demo'
}

export function usesLiveStream(mode: WorkMode): boolean {
  return mode === 'chat'
}
```

- [ ] **Step 4: 跑测确认通过**

Run: `cd frontend && npm run test -- src/chat/workMode.spec.ts`  
Expected: PASS

- [ ] **Step 5: 改 `App.vue` 发送路径**

在 `App.vue` 增加：

```typescript
import { usesLiveStream, usesMockAgent } from './workMode'
```

在 `send()` 内，将：

```typescript
if (workMode.value === 'task_demo') mockAdapter.startFromUserMessage(message)
else mockAdapter.syncLiveStatus('running', message.slice(0, 28))
```

改为：

```typescript
if (usesMockAgent(workMode.value)) {
  mockAdapter.startFromUserMessage(message)
} else {
  mockAdapter.syncLiveStatus('running', message.slice(0, 28))
}
```

将实际请求包在：

```typescript
if (usesLiveStream(workMode.value)) {
  // 现有 sendMessageStream(...) 整段保留在此分支
} else {
  // task_demo：不调用 sendMessageStream；仅 Mock（已 startFromUserMessage）
  sending.value = false
  abortCtrl = null
  return
}
```

注意：`task_demo` 分支不要调用 `sendMessageStream`（避免演示模式打到真实后端）。若当前实现是「演示仍发真实请求」，按 spec 改为演示不发；若产品曾依赖「双轨」，以 **spec §5.2** 为准：默认 chat 真实，task_demo 仅演示。

同步把所有 `workMode.value === 'task_demo'` / `!== 'task_demo'` 判断改为 `usesMockAgent` / `usesLiveStream`，避免散落魔法字符串。

- [ ] **Step 6: Composer 文案**

`Composer.vue` 中模式 tooltip 与 option 保持清晰，例如：

```vue
<el-tooltip content="问答：真实 OA 对话（SSE）；任务演示：仅本地 Mock，不调用后端" placement="top">
...
  <el-option label="问答" value="chat" />
  <el-option label="任务演示（非真实）" value="task_demo" />
```

- [ ] **Step 7: 侧栏标明本地会话**

在 `ConversationSidebar.vue` 会话列表标题附近增加一句静态提示（非假数据），例如：

```vue
<p v-if="!collapsed" class="local-hint">会话列表仅保存在本页，刷新后清空</p>
```

样式用现有侧栏字色/字号变量，勿引入演示数字。

- [ ] **Step 8: 跑 Chat 相关单测**

Run: `cd frontend && npm run test -- src/chat/`  
Expected: 既有 `api.spec` / `delivery.spec` + 新 `workMode.spec` 全部 PASS

- [ ] **Step 9: Commit（仅用户要求时）**

```bash
git add frontend/src/chat/workMode.ts frontend/src/chat/workMode.spec.ts \
  frontend/src/chat/App.vue frontend/src/chat/components/Composer.vue \
  frontend/src/chat/components/ConversationSidebar.vue
git commit -m "$(cat <<'EOF'
fix(chat): gate mock agent to task_demo only

EOF
)"
```

---

### Task 3: 按缺口表修补 P0/P1 mismatch

**Files:**
- Modify: 以 `docs/delivery/2026-10-22-wiring-gap-table.md` 中 `status=mismatch` 且 `priority` 为 P0/P1 的 `fix_in` 列为准
- Test: 优先扩展已有 `frontend/src/admin/*.spec.ts`、`frontend/src/chat/api.spec.ts` 或 `backend/tests/test_*.py`

**Interfaces:**
- Consumes: Task 1 缺口表
- Produces: 每个 P0/P1 mismatch 变为 `ok` 或降级说明写入缺口表 `note`

- [ ] **Step 1: 列出本 Task 工作项**

从缺口表筛选 `priority in (P0,P1) and status=mismatch`，按 `fix_in` 分组。若列表为空：在缺口表加一节「P0/P1：无 mismatch」，直接进入 Step 5。

- [ ] **Step 2: 对每个 mismatch 先写/扩失败测试（TDD）**

规则：

- **字段形状**：在对应 `*.spec.ts` 用夹具断言「后端样例 JSON 可赋给前端类型/映射函数」。
- **错误文案**：`errorMessage(new ApiError(403,'FORBIDDEN','...'))` 含「无权限」。
- **后端薄修复**：只在前端无法适配且违反设计契约时改 `oa_agent`；先加 pytest，再改实现。

示例（仅当 runs 列表缺字段映射时使用；无此缺口则不要添加）：

```typescript
// frontend/src/admin/runs.spec.ts 追加
it('maps suspected_stuck from list item', () => {
  const item = { run_id: 'run_x', suspected_stuck: true, run_status: 'running' }
  expect(item.suspected_stuck).toBe(true)
})
```

- [ ] **Step 3: 最小实现使测试通过**

优先改前端；保持 CSRF/幂等封装；密钥掩码逻辑不动。

- [ ] **Step 4: 更新缺口表行**

将该行 `status` 改为 `ok`，`note` 简述修复。

- [ ] **Step 5: 跑相关自动化**

```bash
cd frontend && npm run test
cd backend && uv run pytest -q --tb=line
```

Expected: 与本 Task 相关的失败已消除；无关的既有失败记入交付「未修复/已知」，不得标为本轮通过。

- [ ] **Step 6: Commit（仅用户要求时）**

```bash
git add docs/delivery/2026-10-22-wiring-gap-table.md frontend backend
git commit -m "$(cat <<'EOF'
fix: resolve P0/P1 frontend-backend contract mismatches

EOF
)"
```

---

### Task 4: 按缺口表修补 P2（可选小改）+ Workflow 策略

**Files:**
- Modify: 缺口表中 P2 `mismatch` 的 `fix_in`
- Optional Modify: `frontend/src/admin/views/WorkflowsView.vue` — **仅当**缺口表 note 要求且改动 ≤ 约 30 行时，改为先 `GET /v1/admin/workflows` 再选 id；否则保持：

```typescript
const WF = '/v1/admin/workflows/travel_query'
```

**Interfaces:**
- Consumes: `GET /v1/admin/workflows` 返回形如 `{ items: { id: string, ... }[] }`（以实现为准；实现前先读 `workflows_api.list_workflows`）
- Produces: P2 mismatch 清零或明确推迟 note

- [ ] **Step 1: 处理 P2 mismatch**

同 Task 3 的 TDD 节奏；无 P2 mismatch 则跳过实现。

- [ ] **Step 2: Workflow 决策落盘**

在缺口表写明最终决策：`keep_travel_query` 或 `list_select`，并写原因。

- [ ] **Step 3: 跑前端测试**

Run: `cd frontend && npm run test`  
Expected: PASS（或仅记录与本 Task 无关的既有失败）

- [ ] **Step 4: Commit（仅用户要求时）**

```bash
git add docs/delivery/2026-10-22-wiring-gap-table.md frontend/src/admin
git commit -m "$(cat <<'EOF'
fix(admin): close P2 wiring gaps where needed

EOF
)"
```

---

### Task 5: 构建 dist + 同源冒烟清单

**Files:**
- Modify: `frontend/dist/**`（build 生成）
- Create/Update: `docs/delivery/2026-10-22-wiring-delivery.md` 中的「手工验收」一节

- [ ] **Step 1: 构建前端**

```bash
cd frontend && npm run build
```

Expected: `vue-tsc` 无错误，`dist/` 更新（含 `admin`/`chat`/`setup` 资源）。

- [ ] **Step 2: 确认后端会挂载 dist**

确认 `backend/oa_agent/main.py` 的 `_mount_frontend` 指向的 `dist` 即本次构建目录（通常为仓库 `frontend/dist`）。若环境变量可覆盖路径，在交付文档写明。

- [ ] **Step 3: 写入手工冒烟清单（尚未执行也要列出）**

在交付文档中加入：

```markdown
## 手工验收清单

| # | 步骤 | 结果（通过/失败/未执行/外部依赖未验证） | 备注 |
|---|------|------------------------------------------|------|
| 1 | 启动后端，打开 /admin/ 登录 | 未执行 | |
| 2 | 指挥舱 /readyz 与 stats 非伪造空态 | 未执行 | |
| 3 | Runs 列表可打开 | 未执行 | |
| 4 | Settings 一组保存（若有权限） | 未执行 | |
| 5 | Tools 列表可打开 | 未执行 | |
| 6 | 无权限账号见「无权限」 | 未执行 | |
| 7 | /chat/?launch=真实码 → session | 未执行 | 需 OA |
| 8 | 问答模式 SSE 出字或明确错误 | 未执行 | 需 LLM/office |
| 9 | pending 时 runs 轮询 | 未执行 | 视业务 |
| 10 | 任务演示不打 stream（Network 无 messages/stream） | 未执行 | |
```

- [ ] **Step 4: 若环境可用则执行方案 2 冒烟并回填表格**

不可用则保持「未执行 / 外部依赖未验证」，禁止改成「通过」。

- [ ] **Step 5: Commit（仅用户要求时）**

```bash
git add frontend/dist docs/delivery/2026-10-22-wiring-delivery.md
git commit -m "$(cat <<'EOF'
build: refresh dist for wiring closed loop

EOF
)"
```

---

### Task 6: 交付说明

**Files:**
- Create: `docs/delivery/2026-10-22-wiring-delivery.md`（若 Task 5 已创建则补全其余章节）

**Interfaces:**
- Consumes: 缺口表终态、测试命令输出、手工表
- Produces: 完整交付文档

- [ ] **Step 1: 写交付文档全文结构**

```markdown
# 前后端对接闭环交付（2026-10-22）

## 功能
- …

## 文件清单
- …

## 迁移说明
- 需重新 `npm run build` 并重启后端以加载新 dist。
- 无 DB 迁移（除非本轮后端薄修复引入；有则列出 Alembic）。

## API 说明
- 无新公开 API（若有薄修复，列出行为变化）。

## 权限与安全
- 管理写仍走 CSRF + Idempotency-Key；Chat ticket 仍仅内存。

## 测试结果
| 项 | 结果 |
|----|------|
| frontend vitest | … |
| backend pytest | … |
| 手工 admin | … |
| 手工 chat + OA | … |

## 未完成项（C 类）
- 附件 / 审批 / 多会话持久化 / 侧栏模块 / …

## 下一阶段计划
- 按产品优先级做 C 类扩展，或继续外部依赖联调。
```

- [ ] **Step 2: 对照 spec §1–§9 逐条勾是否覆盖**；缺则补任务或写入未完成项。

- [ ] **Step 3: Commit（仅用户要求时）**

```bash
git add docs/delivery/2026-10-22-wiring-delivery.md docs/delivery/2026-10-22-wiring-gap-table.md
git commit -m "$(cat <<'EOF'
docs: wiring closed-loop delivery notes

EOF
)"
```

---

## Plan self-review

| Spec 要求 | 对应 Task |
|-----------|-----------|
| 管理端契约验通 §4 | Task 1 + 3 + 4 |
| Chat 主路径 §5 | Task 1 + 2 + 5 |
| 不做 C 类 §2 | Task 1 out_of_scope；全局约束 |
| 错误/安全 §6 | Task 3 修复原则；交付 §权限与安全 |
| 测试标注 §7 | Task 5 手工表；Task 6 |
| 实施顺序 §8 | Task 1→6 |
| build dist §8.5 | Task 5 |
| 卡壳用方案 2 | Task 5 Step 4 |

Placeholder scan: 无 TBD；Task 3/4 以缺口表驱动但步骤可执行。  
类型一致性：`usesMockAgent` / `usesLiveStream` 与 `WorkMode` 一致。

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-22-frontend-backend-wiring.md`.

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每 Task 新开子代理，Task 间审查  
2. **Inline Execution** — 本会话按 executing-plans 连续执行并设检查点  

选哪一种？
