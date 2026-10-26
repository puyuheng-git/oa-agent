# 前后端对接闭环设计（A+B，C 另议）

| 项 | 内容 |
|----|------|
| 日期 | 2026-10-22 |
| 状态 | 已确认 |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md`（冲突时以该文档为准） |
| 范围代号 | D = A（管理端契约验通）+ B（对话端真实 API 接稳）；C（附件/审批/多会话等）本轮不做 |

## 1. 背景与目标

盘点结论：管理端页面大多已调用 `/v1/admin/*`，并非从零接线；员工端已接 session / stream / runs 轮询，但存在 Mock/演示路径与占位功能。用户感知「前后端未连上」，在**只起后端、同源托管** `/admin/`、`/chat/` 的前提下，优先做契约验通与定点修补。

**验收目标**

1. **管理端**：登录 → 指挥舱真实统计（或明确空态）→ 至少抽测 Runs / Settings / Tools 等读写成功；无权限显示「无权限」，无数据显示「暂无数据 / 未检测」。全矩阵以发现问题则修为准，不以「每一页穷尽点完」为阻塞条件。
2. **员工端**：真实 OA `?launch=` → session → SSE 流式问答；`pending` 时轮询 `GET /v1/chat/runs/:id` 至终态。

**访问与入口约束（已确认）**

- 前端由 FastAPI 静态托管（同源），不以独立 vite 端口作为本轮验收路径。
- 员工对话使用真实 OA / office-api 可拿到的 `launch_code`。

## 2. 非目标（C 类 / 另议）

- 附件上传、文档预览、知识库 / 工作空间 / 工具中心等侧栏业务模块。
- 员工审批 HTTP（如 `/v1/chat/approvals`）；禁止把 `/v1/admin/interventions` 接到员工端批准按钮（管理员与员工两套主体）。
- Chat 多会话服务端持久化（`/v1/chat/threads*`）。
- 新业务 workflow 图；多 workflow 选择仅在「列表 API 已有且改动很小」时可选接入，否则保持 `travel_query`。
- 企微通道改造、多实例部署改造。

## 3. 策略

- **主策略（方案 1）**：按对接矩阵做契约对照（路径、状态码、字段、权限、CSRF / `Idempotency-Key`），只修发现的不匹配；Chat 默认 `workMode=chat` 走真实 stream；`task_demo` / Mock 可保留但不得成为默认路径。
- **卡壳时（方案 2）**：本机起后端，同源打开 SPA，用真实 OA launch 与 Network/日志定位环境或契约问题。

## 4. 管理端对接矩阵与修复原则

### 4.1 矩阵

| 优先级 | 模块 | 前端 | 后端 | 本轮动作 |
|--------|------|------|------|----------|
| P0 | 鉴权壳 | login / me / logout / password、Layout CSRF | `/v1/admin/auth/*` | 验 Cookie + CSRF + 幂等；失败提示可读 |
| P0 | 就绪 | `/readyz`、指挥舱 chip | `/readyz` | 无数据不伪造；503 可展示 body |
| P1 | 运行 | Runs / 详情 / 取消重试 / stats / top errors | `/v1/admin/runs*` | 对齐列表/详情/事件字段；取消重试走写链 |
| P1 | 介入 | Interventions 恢复/终止 | `/v1/admin/interventions*` | 仅 `admin` 类可操作；`user_confirm` 保持 403 |
| P1 | 设置/LLM | Settings / Llm 保存与测试 | settings + llm | 密钥只写不读；测试结果如实 |
| P2 | Tool/Skill | CRUD、启停、sync、Apipost | tools/skills | 对照响应形状；diff/activate 字段不一致则薄适配 |
| P2 | Workflow | 现写死 `travel_query` | 已有 list/draft/publish… | 默认不改 id；list 可用且改动小时再改为选择已发布流程 |
| P2 | 账号/角色/审计 | Accounts / Roles / Audit | accounts/roles/perms/audit | 权限不足 →「无权限」 |
| P2 | 对话审计 | Conversations + export | conversations* | export 可继续 Cookie；易改则统一错误体验 |

### 4.2 修复原则

1. 以权威设计 + **后端现有响应**为契约权威；优先改前端适配，不为迁就 UI 改权限模型。
2. 管理写操作必须经 `frontend/src/shared/http.ts`（CSRF + `Idempotency-Key`）；不新增裸 `fetch` 写路径（conversations export 等已有 GET 特例可保留）。
3. 禁止管理端演示数字；空态用「暂无数据 / 未检测」。
4. 前端按钮无对应 API：本轮只记入「未做 / C 类」，不扩后端（笔误级且设计已写的路由除外）。
5. 卡壳时按矩阵同源联调。

### 4.3 管理端验收

超管登录后：指挥舱有真实 stats 或明确空态；至少抽测 Runs 列表、Settings 一组保存、Tools 列表；无权限账号看到「无权限」而非假成功。

## 5. 员工 Chat 闭环

### 5.1 主路径

```
OA 宿主 mint → iframe /chat/?launch=CODE
  → takeLaunchCode() 从 URL 移除
  → POST /v1/chat/session → 内存 ticket + skills/chat/限流配置
  → 定时 POST /v1/chat/session/refresh
  → POST /v1/chat/messages/stream（Bearer + client_msg_id）
  → SSE delta → done 结构化 reply
  → pending → GET /v1/chat/runs/:runId 轮询至终态
```

### 5.2 前端约束

| 项 | 行为 |
|----|------|
| 默认模式 | `workMode = 'chat'`，走真实 stream |
| `task_demo` / Mock | 可保留；不得影响默认发送；入口标注「仅演示」或弱化 |
| 附件 | 提示尚未接入，只发文本 |
| 审批 | 明确不可用；不接管理端 interventions |
| 侧栏会话 | 本地内存可保留；标明非服务端历史 |
| 侧栏占位导航 | 保持「尚未接入」 |
| 适配器 | 以 `api.ts` + `App.vue` 主路径为准，本轮不强行大重构 LiveAgentAdapter |

### 5.3 契约对齐重点

- session：`ticket` / `expires_in` / `display_name` / `thread_id` / `skills` / `chat` / 字数与轮询配置。
- stream：`delta` / `done` / `error` 与 `MessageResult` 一致；401 → 过期态 + reopen 提示。
- pending：轮询间隔用 session 配置，终态替换气泡。

### 5.4 后端本轮

不以扩功能为主。仅当契约缺口导致闭环失败时做薄修复（字段、错误码、SSE 头等）。**不**新增 approvals / 附件 / threads。

### 5.5 员工端验收

真实 launch 进入 → 欢迎能力来自 session → 发送业务问句能流式出答或明确错误（LLM/office 未就绪等）→ pending 能轮询到终态。不测附件/审批/多端会话同步。

## 6. 错误处理与安全

- 统一错误体 → 前端提示；员工 401 → 过期态；管理 401 → 登录。
- 密钥、token、assertion、launch_code：不进日志明文、不进审计详情、不进 localStorage；launch 继续 `replaceState` 清除。
- 不伪造健康/成本/统计。

## 7. 测试结果标注

| 类型 | 含义 |
|------|------|
| 自动化 | Vitest / pytest 能跑则跑并记录 |
| 手工 | 同源 admin 抽测；真实 OA launch 走 Chat |
| 外部依赖未验证 | OA mint、office-api、LLM、Redis/MySQL 不可用时如实标注，不得写成通过 |

## 8. 实施顺序

1. 产出缺口表：管理端 API ↔ 页面、Chat api ↔ router。
2. 修 P0/P1 断裂（鉴权、runs/介入、settings、Chat session/stream）。
3. 修 P2 明显字段/权限问题；workflow 多选仅极小改动时做。
4. Chat 默认真实路径干净；Mock 不抢主路径。
5. `npm run build` 更新 `frontend/dist`（后端静态托管依赖构建产物）。
6. 能跑则跑测试；卡壳切方案 2。
7. 交付说明：已修、未做（C 类）、测试结果分类。

## 9. 风险

- 外部 OA / office-api / LLM 不通时，只能验到「正确报错」，需环境配合。
- 只改 `frontend/src` 未 `build` 会导致同源仍加载旧 `dist`。

## 10. 决策记录

| 问题 | 结论 |
|------|------|
| 范围 | D（A+B），C 另议 |
| 验收 | 管理端运维可用 + 员工真实流式对话 |
| Chat 入口 | 真实 OA launch |
| 访问方式 | 仅后端托管同源 SPA |
| 实施策略 | 方案 1 为主，卡壳用方案 2 |
