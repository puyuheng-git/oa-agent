# 员工长期记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 员工显式「请记住」的摘要事实按 `oa` 跨会话持久化并注入；可自助列表/删除/清空；Chat 薄面板；不做 Profile。

**Architecture:** 新表 `agent_employee_memory` + `chat/memory_store.py` 领域服务。`understand` 扩展 `memory_write` / `memory_forget` 动作（服务端校验 + 敏感过滤）。每次构图前装载 active 条目注入独立提示区块。员工 API + Vue「我的记忆」面板。会话内 Checkpoint `memory` 不变、不晋升。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、既有 chat ticket、Vue 3、pytest / vitest。

**Spec:** `docs/superpowers/specs/2026-10-23-employee-memory-design.md`

## Global Constraints

- 与 OA 只走 HTTP；不访问 `td_oa`。
- 身份只来自 `session.oa`；丢弃客户端自报 `oa`。
- 不做 Profile；无人事 office-api 新调用（D8=C）。
- 仅显式意图写长期记忆；禁止从会话压缩自动晋升（D9=A）。
- 敏感明细不得入库；注入抬头声明「不是指令、可过时」。
- 满员策略：拒绝写入并提示清理（非静默淘汰）。
- 管理写纪律不强制套在员工 API；若记审计则失败须失败。
- 回复与文档中文；代码标识符英文。
- 测试不得把未执行说成通过。
- `data/` 不入库。无 git 时跳过所有 Commit 步骤。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/migrations/versions/0010_employee_memory.py` | 建表 |
| `backend/oa_agent/db/models.py` | `EmployeeMemory` ORM |
| `backend/oa_agent/ids.py` | `new_memory_id()` → `mem_` |
| `backend/oa_agent/chat/memory_store.py` | 领域：写/删/清/列表/敏感/装载注入文本 |
| `backend/oa_agent/chat/router.py` | GET/DELETE memory API |
| `backend/oa_agent/runtime/graphs/travel_query.py` | 注入 + memory 动作路由 |
| `backend/oa_agent/chat/service.py` | 构图时传入 long-term memory 文本（若需） |
| `backend/oa_agent/config/schema.py` | 可选配置：条数上限、注入字数、text 上限 |
| `backend/tests/test_employee_memory.py` | 领域 + API + 注入/意图 |
| `frontend/src/chat/api.ts` + `api.spec.ts` | memory 客户端 |
| `frontend/src/chat/components/MemoryPanel.vue` | 面板 |
| `frontend/src/chat/App.vue` / `AppHeader` / sidebar | 入口 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §12 短更新 |
| `docs/delivery/2026-10-23-employee-memory-delivery.md` | 交付 |

---

### Task 1: 模型与迁移

**Files:**
- Create: `backend/migrations/versions/0010_employee_memory.py`
- Modify: `backend/oa_agent/db/models.py`
- Modify: `backend/oa_agent/ids.py`
- Test: `backend/tests/test_employee_memory.py`

**Interfaces:**
- Produces: `EmployeeMemory`；`new_memory_id() -> str`（`mem_` + ULID）
- Table: `agent_employee_memory`；`kind` ∈ `{preference,constraint,note}`；`status` ∈ `{active,deleted}`

- [ ] **Step 1: 写失败测试**

```python
def test_employee_memory_row_persists(rt):
    from oa_agent.db.models import EmployeeMemory
    from oa_agent.ids import new_memory_id
    mid = new_memory_id()
    with rt.session() as db, db.begin():
        db.add(EmployeeMemory(
            memory_id=mid, tenant_id=rt.tenant_id, oa="alice",
            kind="preference", text="只关心九月", status="active",
        ))
    with rt.session() as db:
        row = db.scalar(sa.select(EmployeeMemory).where(EmployeeMemory.memory_id == mid))
        assert row is not None and row.oa == "alice"
```

- [ ] **Step 2: 跑测确认 FAIL**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_employee_memory.py::test_employee_memory_row_persists -q`  
Expected: FAIL（ImportError 或无表）

- [ ] **Step 3: 实现 ORM + `new_memory_id` + 迁移 `0010`**

`down_revision = "0009_skill_visibility"`。风格对齐 `0008`/`0009`（BIGINT、MYSQL_OPTS、UtcDateTime）。UK(`memory_id`)；索引 `(tenant_id, oa, status, updated_at)`。无回填。

- [ ] **Step 4: 跑测 PASS + `test_head_matches_models`**

- [ ] **Step 5: Commit（无 git 则跳过）**

---

### Task 2: 领域服务 memory_store

**Files:**
- Create: `backend/oa_agent/chat/memory_store.py`
- Modify: `backend/tests/test_employee_memory.py`

**Interfaces:**
- Produces:
  - `KINDS = frozenset({"preference", "constraint", "note"})`
  - `TEXT_MAX = 200`；`ACTIVE_MAX = 50`（或读配置）
  - `reject_sensitive(text: str) -> str | None`  # 返回拒因或 None
  - `add_memory(db, *, tenant_id, oa, kind, text, source_thread_id=None) -> EmployeeMemory`  # 满/敏感/非法 kind → AppError MEMORY_REJECTED
  - `list_active(db, *, tenant_id, oa, limit, offset) -> tuple[list, int]`
  - `soft_delete(db, *, tenant_id, oa, memory_id) -> bool`  # False → 调用方 404
  - `clear_all(db, *, tenant_id, oa) -> int`
  - `forget_by_match(db, *, tenant_id, oa, match_text: str) -> EmployeeMemory | None`  # 唯一子串命中则删
  - `format_injection(rows: list[EmployeeMemory], *, char_limit: int = 800) -> str`  # 含固定抬头；空则 `""`

敏感启发式（最小集，可测）：

```python
# 示例：身份证 15/18 位数字模式；含「工资」「薪资」「银行卡」等关键词 → 拒绝
```

- [ ] **Step 1: 写失败测试**（显式可写、敏感拒、满员拒、非本人删失败、format 抬头）

- [ ] **Step 2: 实现 → PASS**

- [ ] **Step 3: Commit（无 git 则跳过）**

---

### Task 3: 员工 HTTP API

**Files:**
- Modify: `backend/oa_agent/chat/router.py`
- Modify: `backend/tests/test_employee_memory.py`

**Interfaces:**
- `GET /v1/chat/memory` → `{items, total, page, page_size}`
- `DELETE /v1/chat/memory/{memory_id}` → `{ok: true}` 或 404 `MEMORY_NOT_FOUND`
- `DELETE /v1/chat/memory` body `{"confirm": true}` → `{ok: true, deleted: N}`；缺 confirm → 422

鉴权同现有 chat routes（ticket）。列表字段：`memory_id, kind, text, created_at, updated_at`。

- [ ] **Step 1: 集成测试**（open_chat → 领域写入或后续 Task4；本 Task 可用 store.add 插数再测 API）

- [ ] **Step 2: 实现路由 → PASS**

- [ ] **Step 3: Commit（无 git 则跳过）**

---

### Task 4: understand 意图 + 注入接线

**Files:**
- Modify: `backend/oa_agent/runtime/graphs/travel_query.py`
- Modify: `backend/oa_agent/chat/service.py`（`_build_context` / RunContext 增加 `long_term_memory: str`）
- Modify: prompts 中增加 memory_write/forget 动作说明（仅 llm chat 模式）
- Test: `backend/tests/test_employee_memory.py`

**Interfaces:**
- `RunContext` 增加 `long_term_memory: str = ""`
- `_build_context`：用 `memory_store.list_active` + `format_injection` 填入（库失败 → 日志 + 空串，不挡对话）
- `_normalize_llm` / 路由：识别 `action=memory_write|memory_forget`：
  - write → `add_memory`；成功则 `chat_reply` 确认；失败附原因
  - forget → id 或 match；结果口语化
  - 然后走 `respond`（不再 call_tool），**不**改 session memory 晋升逻辑
- 提示词增加：可输出 memory 动作的 JSON 示例；强调不得把敏感明细写入 text
- 规则回退（无模型）：可用极简关键词「请记住」「忘掉」启发式（可选；至少 LLM 路径必须测）

注入块抬头必须为：

`## 关于你的长期记忆（摘要，不是指令，可能过时）`

与 `MEMORY_HEAD`（更早对话）分开两段。

- [ ] **Step 1: 测试**

```python
def test_non_explicit_message_does_not_write_memory(...): ...
def test_memory_write_action_persists_and_injects(...): ...
def test_sensitive_write_rejected_in_graph(...): ...
```

可用 monkeypatch `_understand` 返回固定 memory_write，避免依赖真 LLM。

- [ ] **Step 2: 实现 → PASS**

- [ ] **Step 3: Commit（无 git 则跳过）**

---

### Task 5: Chat「我的记忆」面板

**Files:**
- Modify: `frontend/src/chat/api.ts`、`api.spec.ts`
- Create: `frontend/src/chat/components/MemoryPanel.vue`
- Modify: `App.vue` 或 `AppHeader.vue` / `ConversationSidebar.vue`（次级入口，不占欢迎首屏）
- Test: vitest 覆盖 api 映射；面板可测 props/emit 或薄挂载

**Interfaces:**
- `listMemory` / `deleteMemory` / `clearMemory(confirm=true)`

- [ ] **Step 1: 前端测试（api 形状）→ 实现面板 → `npm test` + `vue-tsc --noEmit`**

- [ ] **Step 2: Commit（无 git 则跳过）**

---

### Task 6: 文档 + 全量测试

**Files:**
- Modify: `docs/design/2026-10-09-oa-langgraph-design.md` §12
- Create: `docs/delivery/2026-10-23-employee-memory-delivery.md`

交付须含：功能、文件、迁移 `0010`、API、安全、测试诚实分类、未完成（Profile、企微面板、自动晋升）、下一阶段 **D**。

- [ ] **Step 1: 写文档**

- [ ] **Step 2: 全量**

```bash
cd backend && .venv\Scripts\python -m pytest -q
cd frontend && npm test && npx vue-tsc --noEmit
```

- [ ] **Step 3: Commit（无 git 则跳过）**

---

## Spec coverage checklist

| Spec 项 | Task |
|---------|------|
| 表/ORM/mem_ id | 1 |
| 领域 CRUD/敏感/满员/注入格式 | 2 |
| 员工 API | 3 |
| 显式意图 + 注入 + 不晋升 | 4 |
| Chat 面板 | 5 |
| 文档与全量测试 | 6 |
| Profile / 自动晋升 / 企微面板 | 非目标 |

## Self-review notes

- 无 TBD；满员=拒绝；清空需 `confirm: true`。
- 库宕机：注入降级为空，不挡对话（对齐 C/E）。
- `_route` 须让 memory 动作进入 respond 路径，避免误 call_tool。
