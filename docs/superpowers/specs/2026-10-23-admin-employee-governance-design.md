# 后台员工治理（会话 · 记忆 · 可见权限）设计

| 项 | 内容 |
|----|------|
| 日期 | 2026-10-23 |
| 状态 | **已确认**（用户审阅通过 2026-10-23） |
| 范围 | 对已交付子系统 **E / C / A** 的管理端统一运营能力 |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md`（冲突时以该文档为准） |
| 相关交付 | E 会话、C Skill 可见性、A 员工长期记忆 |

### 已锁定决断

| ID | 选择 | 含义 |
|----|------|------|
| **M1** | **A** | 统一「员工治理」：按 `oa` 详情 + 三 Tab |
| **M2** | **B** | 读写较全：改标题、恢复软删会话、编辑记忆正文、按 oa 调可见规则等 |
| **M3** | **A** | 权限三分：`ops.employee.view` / `sensitive` / `manage` |
| **M4** | **A** | 员工目录 = 本库痕迹聚合 + 可精确/前缀搜 `oa` |

**实施路径：** 方案 1 — 新菜单 + `/v1/admin/employees*`；可见性复用 `VisibilityService`；**禁止**写 Checkpoint / 图状态。

---

## 1. 背景与目标

**现状：**

- 员工侧：历史会话、Skill 可见裁剪、长期记忆已交付。
- 管理侧：对话导出按消息、Skill CRUD + 可见性 API（无按人运营台）、记忆无管理端。
- 硬约束：管理员与员工两套主体；**后台不能直改 Checkpoint / 图状态**；敏感读须审计；管理写 = 权限 + CSRF + Idempotency-Key + 审计。

**目标：**

1. 按 `oa` 统一查看与调控：会话元数据、长期记忆、Skill 目录可见性。
2. 敏感原文（消息、记忆正文）受独立权限点保护且访问即审计。
3. 写操作可运营、可审计，且不触碰图状态。

**验收素描：**

1. 目录列出有痕迹的 `oa`，搜索可进详情。
2. 可查看含员工已软删线程的消息（sensitive）；可改标题、恢复软删（仅元数据）。
3. 可编辑/清空/代写该人记忆（敏感过滤仍生效）。
4. 可预览该 oa 可见 Skill，并追加/删除针对该 oa 的 allow/deny 规则。
5. 无 Checkpoint 写路径；无 `td_oa` 访问。

---

## 2. 非目标

- Profile / 人事接口、改 Checkpoint、代员工发消息、伪造 run。
- 物理删除对话消息行、跨租户、入站 MCP。
- 替换现有「对话导出」「Skill 管理」页（保留并互链）。
- 企微专用管理 UI。

---

## 3. 信息架构与权限

### 3.1 前端

- 菜单：「员工治理」→ `/admin/employees`（目录）→ `/admin/employees/:oa`（详情）。
- 详情三 Tab：**会话 | 记忆 | 可见性**。

### 3.2 权限点（写入 `perms` / 角色分配）

| 权限点 | 用途 |
|--------|------|
| `ops.employee.view` | 目录、非敏感摘要、可见性预览（Skill 名列表） |
| `ops.employee.sensitive` | 会话消息原文、记忆正文；**每次成功访问写审计**，审计失败则请求失败 |
| `ops.employee.manage` | 全部写操作；CSRF + Idempotency-Key + 审计 |

超级管理员默认拥有上述权限；其它角色按需勾选。

### 3.3 硬边界

- **允许写：** `agent_chat_thread` 元数据/status；`agent_employee_memory` 行；`agent_skill_visibility_rule` 中与运营相关的规则行。
- **禁止写：** Checkpoint、LangGraph 状态、Run 篡改、office-api 代权放宽。
- 恢复软删会话：仅 `status` 变更；UI 明示「不保证 Checkpoint 可续聊」。

---

## 4. 员工目录（M4）

**数据源：** 本租户下出现过的 `oa` 并集，来自：

- `agent_chat_thread.oa`
- `agent_employee_memory.oa`
- `agent_run.oa`（或等价 Run 表字段）

**API：** `GET /v1/admin/employees?q=&page=&page_size=`

**返回摘要（view）：** `oa`、最近活跃时间、会话数（含/不含 deleted 可配置展示）、记忆 active 数。不含消息/记忆正文。

无痕迹账号：`q` 精确匹配时可返回「空壳详情」（三 Tab 为空），便于预配可见规则。

---

## 5. 会话 Tab（E）

### 5.1 读

| 方法 | 路径 | 权限 |
|------|------|------|
| GET | `/v1/admin/employees/{oa}/threads` | view；Query `status` 含 `deleted` |
| GET | `/v1/admin/employees/{oa}/threads/{thread_id}/messages` | **sensitive** + 审计 |

列表含员工已软删线程。消息来自 `agent_conversation_message`，可附 `run_id` 链到现有运行详情（只读）。

### 5.2 写（manage）

| 操作 | API | 行为 |
|------|-----|------|
| 改标题 | PATCH `.../threads/{id}` `{title, reason}` | 截断规则可与员工侧一致 |
| 归档/启封 | PATCH `{status: active\|archived, reason}` | 不可直接 PATCH 为 deleted（走 DELETE） |
| 软删 | DELETE `.../threads/{id}` + reason | `status=deleted` |
| 恢复 | POST `.../threads/{id}/restore` `{status?: active\|archived, reason}` | 仅元数据 |
| 批量（同 oa） | POST `.../threads/batch` `{action, thread_ids, reason}` | archive / soft_delete；跨 oa 禁止 |

---

## 6. 记忆 Tab（A）

### 6.1 读

| 方法 | 路径 | 权限 |
|------|------|------|
| GET | `/v1/admin/employees/{oa}/memory` | view 返回元数据；正文字段仅 **sensitive** 角色可见（或分端点） |

推荐：列表默认打码/省略正文；`?include_text=1` 需 sensitive 并审计。

### 6.2 写（manage）

| 操作 | 行为 |
|------|------|
| POST 代写 | 同员工 `add_memory` 校验（kind 白名单、长度、敏感、满员拒绝） |
| PATCH 编辑 | 改 `kind`/`text`；再跑敏感校验 |
| DELETE 单条 | 软删 |
| POST restore | deleted → active（满员则 422） |
| DELETE 清空 | `confirm: true`；软删全部 active |

API 前缀：`/v1/admin/employees/{oa}/memory*`。

---

## 7. 可见性 Tab（C）

### 7.1 预览（view）

`GET /v1/admin/employees/{oa}/visibility`  
→ `{visible: [...], hidden: [{name, reason}]}`  
基于 `VisibilityService` + `PrincipalContext(oa, tags=[])`（本期 TagProvider 仍空）。

### 7.2 写（manage）— 按 oa 安全改规则

**原则：** 员工详情页**不得**用「全量替换某 Skill 全部规则」作为默认操作（易误删他人 oa/all/tag 规则）。

推荐 API：

| 方法 | 路径 | 行为 |
|------|------|------|
| POST | `/v1/admin/employees/{oa}/visibility/grants` | body `{skill_name, effect: allow\|deny, reason}` → 追加一条 `principal_type=oa, principal_value={oa}`（已存在则幂等） |
| DELETE | `/v1/admin/employees/{oa}/visibility/grants` | body `{skill_name, effect?, reason}` → 删除该 skill 上针对该 oa 的规则行 |
| POST | `.../visibility/grants/batch` | 多 skill 统一 allow 或 deny |

完整规则编辑仍在现有 `PUT /v1/admin/skills/{name}/visibility`（`ops.skill.manage`）。

---

## 8. 审计与安全

- 所有 manage 写：权限 + CSRF + Idempotency-Key + 审计；审计失败则失败。
- sensitive 读：审计 `employee.sensitive.read`（resource 含 oa、thread_id 或 memory_id）；失败则失败。
- 日志/审计不落 office_token、master key；记忆/消息正文是否写入审计 after：默认**不写全文**，只写 id + 操作类型（与训练导出通道分离）。
- 路径中的 `{oa}` 必须与资源行一致；禁止通过改 body 调包到其他 oa。

---

## 9. 测试计划（诚实分类）

| 项 | 标注 |
|----|------|
| 目录聚合与搜索 | 自动化 |
| 无权限 403；sensitive 无审计失败 | 自动化 |
| 会话恢复不碰 Checkpoint | 自动化（断言无 checkpointer 写调用或状态文件不变） |
| 记忆编辑敏感拒绝 | 自动化 |
| 可见性 grant 仅影响目标 oa | 自动化 |
| 管理端 UI 手工点通 | 手工 / 未执行 |
| 真 OA 员工联调 | 外部依赖未验证 |

---

## 10. 实施分期建议

| Task | 内容 |
|------|------|
| 1 | 权限点注册 + 角色种子/迁移说明 |
| 2 | 目录 API + 单测 |
| 3 | 会话 Tab API（读+写） |
| 4 | 记忆 Tab API（读+写） |
| 5 | 可见性预览 + oa grant API |
| 6 | 管理前端：目录 + 详情三 Tab |
| 7 | 权威设计 §9/§12 短更新 + 交付 + 全量测试 |

---

## 11. 规格自检

- 无 TBD；M2=B 的「批量改多人规则」收窄为**同 oa 多 skill**，跨 oa 批量明确不做（避免误操作面过大）。
- 记忆列表正文默认不暴露给仅 view 角色。
- 与 C 的 Skill 级 PUT 并存、互链。
