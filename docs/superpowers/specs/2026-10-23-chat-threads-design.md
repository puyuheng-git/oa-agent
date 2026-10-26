# 员工历史会话（Chat Threads）设计

| 项 | 内容 |
|----|------|
| 日期 | 2026-10-23 |
| 状态 | **已确认**（用户确认 E 草案 + D3=A + D4=A） |
| 子系统 | 平台路线图 **E**（总序 E → C → A → D → B） |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md`（冲突时以该文档为准） |
| 路线图 | `docs/superpowers/plans/2026-10-23-platform-next-roadmap.md` |

---

## 1. 背景与目标

**现状：** 员工每次 `launch` → `session` 都会 `new_thread_id()`；对话原文已写入 `agent_conversation_message`，但员工端无会话列表、无法指定线程续聊，故「每次登录历史消失」。图内 `history` / `memory` 随 Checkpoint 绑在 `thread_id` 上，新线程自然接不上。

**目标：**

1. 员工登录后能看到本人历史会话列表（iframe 与企微按同一 `oa` **共用**一套列表，D2=A）。
2. 点开某会话可加载消息并继续提问（复用同一 `thread_id`，Checkpointer 承接）。
3. 可新建会话、重命名、归档、软删（对员工隐藏，D4=A）。
4. 默认进入体验为欢迎/可开新会话，历史在侧栏（D3=A）；不自动强行进入「最近会话」（避免企微误续旧题）。

**验收（真实环境证据）：**

1. 员工在网页提问后关闭再进入：侧栏可见该会话；打开后消息完整；追问「那第二条呢」能承接摘要中的记录 ID。
2. 同一 `oa` 在企微产生的会话出现在网页列表（可带来源标签）；反之亦然。
3. 软删后员工列表与打开均 404/不可见；管理员对话导出/审计仍能见到对应消息（若原通道已有）。
4. 伪造他人 `thread_id` 续聊 → 403/404；客户端自报 `oa` 无效。

---

## 2. 非目标（本规格不做）

- 长期记忆文件 / Profile（子系统 A）。
- MCP / Skill 可见权限、多 Domain（子系统 C/B）。
- 新业务 Workflow 图（子系统 D）。
- 向量检索历史、会话分享、物理删除消息。
- 管理员直接改 Checkpoint / 图状态。
- 改企微长连接协议本身（仅在写消息/建线程时写入 `channel` 与线程表）。

接线设计 `2026-10-22-…-wiring-design.md` §2 曾将「多会话 `/v1/chat/threads*`」列为 C 类；**本规格正式纳入实施范围**，以本文为准。

---

## 3. 概念与身份

| 概念 | 定义 |
|------|------|
| **Thread（会话）** | 员工可见的对话容器；主键 `thread_id`（`thr_` + ULID），与现有 Run / Checkpoint / 消息表一致 |
| **Session（登录态）** | Redis 中的 chat ticket；持有当前 `oa`、`office_token`、**当前** `thread_id` |
| **Message** | 已有 `agent_conversation_message` 行；不新建消息表 |

- 列表与读写授权：**仅** `session.oa == thread.oa`（及 `tenant_id`）。
- `channel`（`web` / `wecom` 等）记在线程的「最近来源 / 创建来源」上，**不**用于隔离列表（D2=A）。
- `thread_id` **不是**授权凭证；即便泄露，无本人 ticket 也不能读。

---

## 4. 数据模型

### 4.1 新表 `agent_chat_thread`

| 列 | 类型（示意） | 说明 |
|----|--------------|------|
| `id` | PK | 自增 |
| `thread_id` | String(40) UK | `thr_` + ULID |
| `tenant_id` | String(32) | 一期 `dscpa` |
| `oa` | String(64) | 员工账号；列表过滤键 |
| `created_channel` | String(16) | 创建时渠道 |
| `last_channel` | String(16) | 最近一次发言渠道 |
| `title` | String(200) | 展示标题；默认可空，首条用户消息截断填充 |
| `status` | String(16) | `active` \| `archived` \| `deleted` |
| `created_at` / `updated_at` / `last_message_at` | UtcDateTime | |
| `pinned` | bool | 默认 false；本期 API 可只读 false，或支持 PATCH |
| `metadata_json` | JSON nullable | 预留（如等待人工的 run_id 缓存，非权威） |

索引建议：

- UK(`thread_id`)
- (`tenant_id`, `oa`, `status`, `last_message_at` DESC) — 列表
- (`tenant_id`, `oa`, `updated_at`) — 备用

### 4.2 已有表

- `agent_conversation_message`：不改结构；继续按 `thread_id` 写入。
- `agent_run`：已有 `thread_id`；列表角标「等待人工」可 join 该 oa+thread 下非终态 / `waiting_human` 运行（只读，失败则不显示角标，不伪造）。

### 4.3 历史数据回填（迁移）

升级时可选数据修复（同一迁移或后续脚本）：

1. 从 `agent_conversation_message` 按 `thread_id` 聚合，为尚无行的 `thread_id` 插入 `agent_chat_thread`。
2. `oa` / `created_channel` / `last_channel` 取该线程最早与最晚消息；`title` 取最早 user 内容截断（如 40 字）；`status=active`；`last_message_at` 取最晚 `created_at`。
3. 无消息的孤儿 Checkpoint 线程可不建行（员工不可见无妨）。

回填失败不得阻断空库新装。

---

## 5. API（员工，前缀 `/v1/chat`）

鉴权：与现网一致，`Authorization: Bearer` ticket；身份只来自服务端 session。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/threads` | 本人列表。Query：`status`（默认 `active`，可选 `archived`）、`page`/`page_size`（上限 100）。不含 `deleted` |
| POST | `/threads` | 新建空会话；返回 `thread_id` 等；**同时**把 session 当前 `thread_id` 切到新线程并写回 Redis |
| GET | `/threads/{thread_id}/messages` | 消息翻页（`before_id` 或 `page`）；仅 `active|archived` 且本人 |
| PATCH | `/threads/{thread_id}` | `title`、`status`（`active`↔`archived`）；不可把 `deleted` 经此恢复为捷径以外的值时：允许 `archived`→`active`；`deleted` 仅 DELETE |
| DELETE | `/threads/{thread_id}` | 软删：`status=deleted`；之后 GET 列表/消息/续聊均不可见 |

### 5.1 Session 调整

`POST /v1/chat/session`（redeem launch）与现有 `GET /session`：

请求体（redeem）增加可选字段：

```json
{ "launch_code": "...", "thread_id": "thr_..." }
```

| `thread_id` | 行为 |
|-------------|------|
| 省略 / null | **新建**线程并写入 `agent_chat_thread`（D3=A：默认新会话）；session 持有新 id |
| 合法且本人且未 deleted | session 绑定该线程（续聊入口；前端从侧栏打开时先 PATCH session 或发消息前绑定——见 §5.2） |
| 他人 / 不存在 / deleted | `404 THREAD_NOT_FOUND`（文案不泄露是否存在于他人） |

`GET /v1/chat/session` 响应增加：`thread_id`（当前）、以及既有 `skills` / `chat` / 限流字段。

企微建会话：`wecom_session` 路径同样在首次发言或进入时确保线程行存在；列表与网页共用。

### 5.2 切换当前线程

两种等价策略（实现选一，推荐 B）：

- **A.** `POST /v1/chat/session/switch` `{ "thread_id" }` 更新 Redis session。  
- **B.** 发消息时 body 带可选 `thread_id`；服务端校验后覆盖本次 run 使用的 thread，并写回 session。列表「打开」只拉 messages，首条发送再绑定。

**推荐 B + 打开时可选 switch：** 打开侧栏会话时调用轻量 `POST /session/switch`（或复用 PATCH），避免用户未发言前 session 仍指向旧线程导致「欢迎态错乱」。

本规格采用：

1. `POST /v1/chat/session/switch` `{ "thread_id" }`：校验本人未删除后更新 session。  
2. `POST /messages` 与 `/messages/stream`：以 **session 当前 `thread_id`** 为准（与现网一致）；不信任客户端在消息体里改 oa。

### 5.3 发消息时更新线程

在 `record_user` 成功路径上（同事务或紧随其后，失败只打日志不挡对话）：

- 更新 `last_message_at`、`updated_at`、`last_channel`。  
- 若 `title` 为空，用本条用户消息截断写入（去换行，最大 40～80 字）。

### 5.4 错误码（新增）

| code | HTTP | 场景 |
|------|------|------|
| `THREAD_NOT_FOUND` | 404 | 不存在、非本人、已 deleted |
| `THREAD_GONE` | 409 | 并发被删（可选，可与 NOT_FOUND 合并） |

---

## 6. 运行时与 Checkpoint

- `engine.invoke(..., thread_id=session.thread_id)` 不变。  
- 续聊旧线程 = 自动加载该 thread 的 Checkpoint（含 `history` / `memory`）。  
- 软删线程：**不再接受**新消息与 switch；Checkpoint 文件保留（不做后台物理清，避免越权运维）；管理员不提供「恢复 Checkpoint」UI。  
- 超会话压缩配置仍按发布配置；与线程列表无关。

---

## 7. 前端（员工 Chat）

1. **侧栏：** 会话列表（标题、相对时间、渠道小标签、可选「等待中」角标）；「新对话」按钮 → `POST /threads` + 清空主区欢迎态。  
2. **默认进入（D3=A）：** 新 launch 后进入欢迎/空会话（新建线程），不自动打开最近会话。  
3. **打开历史：** switch → 拉 messages 渲染 → 可发送。  
4. **归档/删除：** 确认后 PATCH/DELETE；删除用「仅对自己隐藏」文案，避免误解为公司销毁审计。  
5. **企微：** 无完整侧栏时，本期可不做列表 UI；但后端线程仍写入，网页侧可见。企微「历史列表」列为后续增强，不阻塞本规格验收（验收项 2 用网页看企微产生的线程即可）。

---

## 8. 权限与安全

- 无新管理权限点；员工 API 仅 ticket。  
- 管理端现有 conversations 导出/查询逻辑不因员工软删而过滤掉消息（D4=A）；若列表 API 将来按 thread 表展示，需明示「含员工已隐藏会话」或独立筛选——**本期管理端可不改**，仅保证导出 SQL 不依赖 `status!=deleted`。  
- 审计：员工侧写操作（建线程、删线程）可选记 `actor_type=employee` 的轻量审计（与 launch 一样失败不阻断）；至少打结构化日志。  
- 不把 office_token、密钥写入线程 metadata。

---

## 9. 配置

本期可不新增配置中心项。若需可后续加：

- 列表分页默认、标题最大字数、软删保留天数（物理清理任务）——**不做则不写死进必须范围**。

---

## 10. 测试要点

| 类型 | 用例 |
|------|------|
| 自动化 | 建线程、列表只见本人、跨 oa 404、软删后不可 switch/发消息、首条消息填 title、session 默认新线程、指定 thread_id 续聊 Checkpoint 历史条数增加 |
| 自动化 | 回填迁移：给定两线程消息 → 两行 thread |
| 手工 | 网页侧栏 UX；企微发言后网页可见该线程 |
| 外部依赖 | 真实 OA launch 联调（可记未执行） |

---

## 11. 文件影响（实施时）

| 区域 | 预期 |
|------|------|
| `db/models.py` + Alembic 迁移 | `ChatThread` |
| `chat/threads.py` 或 `chat/service` 扩展 | CRUD + 列表 |
| `chat/router.py` | 新路由；session/switch |
| `auth/chat_launch.py` | redeem 可选 thread；新建时注册线程行 |
| `channels/wecom.py` | 确保线程行 |
| `observability/conversation.py` | 触达更新 thread 元数据 |
| `frontend/src/chat/*` | 侧栏 + API |
| 测试 | `tests/test_chat_threads.py` 等 |

---

## 12. 决断记录（本规格）

| ID | 选择 |
|----|------|
| D2 | A 同 oa 跨渠道共用列表 |
| D3 | A 默认新会话，历史在侧栏 |
| D4 | A 软删仅对员工隐藏 |

---

## 13. Spec 自检

- 无 TBD/TODO 占位。  
- 与硬约束一致：不碰 `td_oa`、权限不靠模型、管理不改 Checkpoint。  
- 范围仅 E；未混入 A/B/C/D 实现。  
- D3/D4/D2 与 API/前端行为一致。  
- 企微列表 UI 降级已写明，避免验收歧义。
