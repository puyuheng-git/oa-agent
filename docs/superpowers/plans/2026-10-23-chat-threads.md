# 员工历史会话（Chat Threads）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 员工再次打开助手时能看到并续聊历史会话（同 `oa` 跨网页/企微共用列表）；默认新会话，软删仅对自己隐藏。

**Architecture:** 新增 `agent_chat_thread` 表作为员工可见的会话容器；消息仍写 `agent_conversation_message`。Session 持有当前 `thread_id`；`POST /session/switch` 切换；发消息路径更新线程元数据。续聊复用同一 `thread_id`，LangGraph Checkpointer 自然承接 `history`/`memory`。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、既有 chat ticket（Redis/内存）、Vue 3 + Element Plus、pytest。

**Spec:** `docs/superpowers/specs/2026-10-23-chat-threads-design.md`

## Global Constraints

- 与 OA 只走 HTTP；不访问 `td_oa`。
- 身份只来自服务端 session.`oa`；客户端自报 `oa` / 他人 `thread_id` 一律拒绝（404 `THREAD_NOT_FOUND`）。
- 管理员不改 Checkpoint；员工软删不删除消息行、不挡管理端导出。
- 管理写操作纪律不适用于本员工 API；员工写操作失败可打日志，删/建线程可选轻量审计且失败不阻断（与 launch 一致）。
- 回复与文档中文；代码标识符英文。
- 测试结果不得把未执行说成通过。
- `data/` 不入库。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/migrations/versions/0008_chat_thread.py` | 建表 + 可选回填 |
| `backend/oa_agent/db/models.py` | `ChatThread` 模型 |
| `backend/oa_agent/chat/threads.py` | 线程领域逻辑（新建） |
| `backend/oa_agent/chat/router.py` | HTTP：threads CRUD、switch；session 返回 thread_id |
| `backend/oa_agent/auth/chat_launch.py` | redeem 创建线程行；可选 `thread_id` 续聊 |
| `backend/oa_agent/chat/service.py` | 对外封装 ensure/touch（若需要） |
| `backend/oa_agent/observability/conversation.py` | `record_user` 后 touch 线程 |
| `backend/oa_agent/channels/wecom.py` | 新建 wecom session 时 ensure 线程行 |
| `backend/tests/test_chat_threads.py` | 自动化测试（新建） |
| `frontend/src/chat/api.ts` | threads / switch API |
| `frontend/src/chat/App.vue` | 侧栏列表与切换 |
| `frontend/src/chat/api.spec.ts` | 前端单测（解析/调用形状） |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §12 API 表补一行（短更新） |

---

### Task 1: 模型、迁移与回填

**Files:**
- Create: `backend/migrations/versions/0008_chat_thread.py`
- Modify: `backend/oa_agent/db/models.py`
- Test: `backend/tests/test_chat_threads.py`（本 Task 先写迁移后可加载模型的冒烟；完整 API 测在后续 Task）

**Interfaces:**
- Produces: ORM `ChatThread`；表 `agent_chat_thread`；常量 status：`active` / `archived` / `deleted`

- [ ] **Step 1: 在 `models.py` 增加 `ChatThread`**

放在 `ConversationMessage` 之前或之后均可；字段与 spec §4.1 一致：

```python
class ChatThread(Base):
    __tablename__ = "agent_chat_thread"
    __table_args__ = (
        sa.UniqueConstraint("thread_id", name="uk_chat_thread_id"),
        sa.Index("ix_chat_thread_oa_status_msg", "tenant_id", "oa", "status", "last_message_at"),
    )
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(sa.String(40))
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    oa: Mapped[str] = mapped_column(sa.String(64))
    created_channel: Mapped[str] = mapped_column(sa.String(16), default="")
    last_channel: Mapped[str] = mapped_column(sa.String(16), default="")
    title: Mapped[str] = mapped_column(sa.String(200), default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="active")  # active|archived|deleted
    pinned: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    metadata_json: Mapped[Any] = mapped_column(sa.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_message_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
```

- [ ] **Step 2: 写迁移 `0008_chat_thread.py`**

`down_revision = "0007_conversation_log"`。`upgrade`：建表 + 索引；并从 `agent_conversation_message` 回填（按 `thread_id` 分组；SQLite/MySQL 兼容的 SQLAlchemy 查询写在 `upgrade()` 用 `op.get_bind()` 执行，或纯 SQL）。无消息则跳过。`downgrade`：drop 表。

回填逻辑要点：

```python
# 伪代码：对每个 thread_id
# oa = 任取一条；created_channel = 最早消息 channel；last_channel = 最晚
# title = 最早 role=user 的 content 截断 40 字（去换行）
# last_message_at = 最晚 created_at；status=active
```

- [ ] **Step 3: 跑迁移冒烟**

Run: `cd backend && .venv\Scripts\python -m pytest -q tests/test_chat.py::test_session_reports_chat_availability -q`  
（或全量 conftest 会跑迁移的任一测试）  
Expected: PASS（库能起来）

- [ ] **Step 4: Commit**

```bash
git add backend/oa_agent/db/models.py backend/migrations/versions/0008_chat_thread.py
git commit -m "feat(chat): add agent_chat_thread table and model"
```

---

### Task 2: `chat/threads.py` 领域服务

**Files:**
- Create: `backend/oa_agent/chat/threads.py`
- Test: `backend/tests/test_chat_threads.py`

**Interfaces:**
- Produces:
  - `STATUS_ACTIVE/ARCHIVED/DELETED`
  - `ensure_thread(db, *, thread_id, oa, channel, tenant_id=...) -> ChatThread`
  - `create_thread(db, *, oa, channel, tenant_id=...) -> ChatThread`（内部 `new_thread_id()`）
  - `get_owned(db, *, thread_id, oa, tenant_id=..., allow_statuses=...) -> ChatThread | None`
  - `list_threads(db, *, oa, status, tenant_id, limit, offset) -> tuple[list[ChatThread], int]`
  - `patch_thread(db, thread, *, title=None, status=None) -> ChatThread`
  - `soft_delete(db, thread) -> None`
  - `touch_on_user_message(db, *, thread_id, oa, channel, user_text) -> None`（更新 last_*；空 title 则截断填标题；找不到行则 ensure）
  - `thread_view(t: ChatThread) -> dict`
  - `TITLE_MAX = 40`

- [ ] **Step 1: 写失败测试（领域逻辑，可用 db fixture）**

```python
def test_create_and_list_owned_only(admin):  # 或 installed+session
    # 用 runtime.session 创建两个 oa 的线程，list 只返回本人
    ...

def test_soft_delete_hides_from_get():
    ...

def test_touch_fills_title_once():
    # 空 title + 用户消息 → title 截断；第二次不覆盖已有 title
    ...
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv\Scripts\python -m pytest -q tests/test_chat_threads.py -x`  
Expected: FAIL（模块或函数不存在）

- [ ] **Step 3: 实现 `threads.py`**

要求：

- `get_owned`：`deleted` 默认不返回（除非 `allow_statuses` 显式包含）。
- `patch_thread`：只允许 `active`↔`archived`；非法 status → `AppError(422, ...)`。
- `touch_on_user_message`：吞掉「行不存在」时先 `ensure_thread`；写库失败由调用方决定是否吞（见 Task 4）。
- `thread_view` 字段：`thread_id, title, status, created_channel, last_channel, pinned, created_at, updated_at, last_message_at`（时间 ISO）。

- [ ] **Step 4: 跑测试通过**

Run: `cd backend && .venv\Scripts\python -m pytest -q tests/test_chat_threads.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/oa_agent/chat/threads.py backend/tests/test_chat_threads.py
git commit -m "feat(chat): thread domain service for list/create/touch/soft-delete"
```

---

### Task 3: Launch / WeCom 注册线程行

**Files:**
- Modify: `backend/oa_agent/auth/chat_launch.py`
- Modify: `backend/oa_agent/chat/router.py`（`create_session`）
- Modify: `backend/oa_agent/channels/wecom.py`
- Modify: `backend/tests/test_chat_threads.py` / `test_chat.py`

**Interfaces:**
- Consumes: `threads.create_thread` / `threads.ensure_thread` / `threads.get_owned`
- Change: `redeem_launch` 签名增加可选 `thread_id`；或 **更干净**：redeem 仍只建 session，由 `create_session` 路由负责落库线程（推荐，避免 chat_launch 依赖 DB）

**推荐实现（避免 auth 层依赖 SessionFactory）：**

1. `redeem_launch` 保持生成 `thread_id`（或接受已校验的 id）。
2. `router.create_session`：redeem 后 `with rt.session() as db: threads.ensure_thread(...)`；若 body 带 `thread_id`，先 `get_owned`，失败 404，成功则 session.thread_id=该 id 并 `store_session`。
3. WeCom：`wecom_session` 在新建 `ChatSession` 后 `ensure_thread`（需传入 `rt`，已有）。

- [ ] **Step 1: 扩展 `SessionIn`**

```python
class SessionIn(BaseModel):
    launch_code: str = Field(min_length=10, max_length=128)
    thread_id: str | None = Field(default=None, min_length=8, max_length=40)
```

- [ ] **Step 2: 测试**

```python
def test_session_defaults_to_new_thread_row(chat, office):
    h = open_chat(chat)
    # GET session 有 thread_id；DB 有对应 ChatThread status=active

def test_session_with_foreign_thread_404(chat, office):
    # 另一 oa 的 thread_id → 404 THREAD_NOT_FOUND

def test_wecom_creates_thread_row(...):  # 若已有 wecom fixture 则加；否则本 Task 只测 web，wecom 单测 mock ensure 调用
```

- [ ] **Step 3: 实现 router + wecom ensure**

`GET /session` 已返回 `thread_id`（来自 session）。确认 `open_chat` 测试不破。

- [ ] **Step 4: pytest**

Run: `cd backend && .venv\Scripts\python -m pytest -q tests/test_chat_threads.py tests/test_chat.py tests/test_wecom.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/oa_agent/chat/router.py backend/oa_agent/channels/wecom.py backend/tests/test_chat_threads.py
git commit -m "feat(chat): register chat_thread on session create and wecom login"
```

---

### Task 4: Threads HTTP API + switch

**Files:**
- Modify: `backend/oa_agent/chat/router.py`
- Modify: `backend/tests/test_chat_threads.py`

**Interfaces:**
- `GET /v1/chat/threads`
- `POST /v1/chat/threads`
- `GET /v1/chat/threads/{thread_id}/messages`
- `PATCH /v1/chat/threads/{thread_id}`
- `DELETE /v1/chat/threads/{thread_id}`
- `POST /v1/chat/session/switch` body `{ "thread_id" }`

- [ ] **Step 1: 写 API 测试**

```python
def test_list_create_switch_messages_delete(chat, office, monkeypatch):
    h = open_chat(chat)
    # POST /threads → 新 id，session 指向它
    # 发一条消息（rules 或 mock model）
    # GET /threads 含该会话且 title 非空
    # GET .../messages 含 user/assistant
    # switch 回另一线程
    # DELETE → 列表消失；switch 回删线程 → 404
```

- [ ] **Step 2: 实现路由**

分页：`page` 从 1、`page_size` 默认 20 最大 100。  
messages：按 `id` 升序或 `created_at`；返回 `{ items: [{message_id, role, content, reply_type, data, error_code, created_at, run_id}], page, page_size, total }`。  
`POST /threads`：`create_thread` + 更新 session Redis。  
`switch`：校验后 `session.thread_id=...` + `store_session`。

- [ ] **Step 3: pytest**

Run: `cd backend && .venv\Scripts\python -m pytest -q tests/test_chat_threads.py`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/oa_agent/chat/router.py backend/tests/test_chat_threads.py
git commit -m "feat(chat): employee thread list/messages/switch/soft-delete APIs"
```

---

### Task 5: 发消息时 touch 线程

**Files:**
- Modify: `backend/oa_agent/observability/conversation.py`
- Modify: `backend/oa_agent/chat/service.py`（若 touch 放在 `record_user` 之后由 service 调更清晰）
- Test: `backend/tests/test_chat_threads.py`

**推荐：** 在 `service.start_run` 里 `conversation.record_user(...)` 之后调用 `threads.touch_on_user_message`（需要 db session）；失败 `log.exception`，不抛。

- [ ] **Step 1: 测试「首条消息写入 title + last_message_at」**（若 Task 4 已覆盖可补边界：超长截断、已有 title 不覆盖）

- [ ] **Step 2: 实现 touch 调用**

- [ ] **Step 3: pytest 相关用例 PASS**

- [ ] **Step 4: Commit**

```bash
git add backend/oa_agent/chat/service.py backend/oa_agent/observability/conversation.py backend/tests/test_chat_threads.py
git commit -m "feat(chat): update thread title and last_message_at on user message"
```

---

### Task 6: 续聊承接 Checkpoint（回归）

**Files:**
- Modify: `backend/tests/test_chat_threads.py`（或扩展 `test_agent_chat.py`）

- [ ] **Step 1: 测试**

```python
def test_reopen_thread_keeps_model_history(chat, office, monkeypatch):
    # mock 模型两轮聊天；记录 thread_id
    # 新 launch，session 带 thread_id（或 switch）
    # 第三轮模型输入应含前两轮 human/ai（条数断言同 history_turns）
```

- [ ] **Step 2: 若失败，检查 switch 是否写回 session.thread_id、invoke 是否用 session.thread_id**

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_chat_threads.py
git commit -m "test(chat): reopened thread continues checkpoint history"
```

---

### Task 7: 前端 API + 侧栏

**Files:**
- Modify: `frontend/src/chat/api.ts`
- Modify: `frontend/src/chat/App.vue`
- Modify: `frontend/src/chat/api.spec.ts`（如有可测纯函数）

**Interfaces:**
- `listThreads / createThread / getThreadMessages / patchThread / deleteThread / switchThread`
- `ChatSessionInfo` 已有 `thread_id` 则展示；打开历史：`switchThread` → `getThreadMessages` → 填入 `messages`
- 「新对话」：`createThread` → 清空主区 → 欢迎态
- 默认 launch：保持现网新 session（已是新线程），侧栏加载 `listThreads`

- [ ] **Step 1: 扩展 `api.ts`**

类型与函数对齐后端响应；错误用既有 `ApiError`。

- [ ] **Step 2: `App.vue` 布局**

左侧列表（可用简单 `div` + 按钮，避免过度设计）；项显示 `title || '新会话'`、相对时间可选、`last_channel` 小字。  
删除：`ElMessageBox.confirm`，文案说明「仅对自己隐藏」。  
流式发送逻辑不变，依赖 switch 后的 session。

- [ ] **Step 3: 前端测试 + 类型检查**

Run:

```bash
cd frontend && npm test && npx vue-tsc --noEmit
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add frontend/src/chat/api.ts frontend/src/chat/App.vue frontend/src/chat/api.spec.ts
git commit -m "feat(chat): sidebar for thread list, switch, and soft-delete"
```

---

### Task 8: 设计文档 API 表短更新 + 交付自检

**Files:**
- Modify: `docs/design/2026-10-09-oa-langgraph-design.md` §12（chat 行补 threads/switch）
- Create（可选）: `docs/delivery/2026-10-23-chat-threads-delivery.md` 若本阶段单独交付

- [ ] **Step 1: 更新权威设计 §12 一行**

例如：`/v1/chat/threads*`、`/v1/chat/session/switch`

- [ ] **Step 2: 后端全量 + 前端测试**

Run:

```bash
cd backend && .venv\Scripts\python -m pytest -q
cd frontend && npm test && npx vue-tsc --noEmit
```

Expected: 全绿

- [ ] **Step 3: 对照 spec §1 验收表自检**（能自动化的已测；企微→网页列表标「手工/未执行」）

- [ ] **Step 4: Commit**

```bash
git add docs/design/2026-10-09-oa-langgraph-design.md docs/delivery/2026-10-23-chat-threads-delivery.md
git commit -m "docs: chat threads API and delivery notes"
```

---

## Spec coverage（自检）

| Spec 要求 | Task |
|-----------|------|
| `agent_chat_thread` + 回填 | 1 |
| 按 oa 共用列表、channel 仅标签 | 2–4 |
| D3 默认新会话 | 3 |
| D4 软删 | 2, 4, 7 |
| CRUD + messages + switch | 4 |
| 发消息更新 title/时间 | 5 |
| Checkpoint 续聊 | 6 |
| 网页侧栏；企微只保证写入 | 3, 7 |
| 安全：他人 thread 404 | 3, 4 |
| 管理导出不受软删影响 | 4（不改导出 SQL）+ 8 自检说明 |

## Placeholder scan

无 TBD；企微列表 UI 明确不做。

## Type consistency

- 状态字符串统一：`active` | `archived` | `deleted`
- 错误码：`THREAD_NOT_FOUND`
- 视图字段名与 `thread_view` / 前端类型一致

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-23-chat-threads.md`.

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每个 Task 开新子代理，Task 间你我复核  
2. **Inline Execution** — 本会话按 Task 连续实现，设检查点  

你要哪一种？若选 1 或 2，回复后我再按对应技能开工（需要你明确说「开始实现」或选执行方式）。
