# 前后端对接闭环交付（2026-10-22）

| 项 | 内容 |
|----|------|
| 范围 | D = A（管理端契约验通）+ B（Chat 真实 API）；C 本轮不做 |
| Spec | `docs/superpowers/specs/2026-10-22-frontend-backend-wiring-design.md` |
| 缺口表 | `docs/delivery/2026-10-22-wiring-gap-table.md` |
| 策略 | 方案 1（代码契约对照）；方案 2（同源联调）本轮未跑 |

## 功能

- **管理端（A）**：按矩阵完成 `/v1/admin/*` 与页面契约对照；P0/P1/P2 无 `mismatch`，无需薄修复。写链经 `http.ts`（CSRF + `Idempotency-Key`）；密钥只写不读；空态不伪造。
- **Chat（B）**：默认 `workMode='chat'` 走真实 SSE（`POST /v1/chat/messages/stream`）；`task_demo` 才走 Mock；`usesMockAgent` / `usesLiveStream` 与模式一致。session / refresh / runs 轮询契约已对齐。
- **Workflow**：决策 `keep_travel_query`（不接列表选 id；多 workflow 属 C）。
- **同源托管**：`npm run build` 产出 `frontend/dist`；后端 `_mount_frontend` 挂载 `/admin/`、`/chat/`、`/setup/`、`/assets`。

## 文件清单

| 类别 | 路径 | 说明 |
|------|------|------|
| 缺口表 | `docs/delivery/2026-10-22-wiring-gap-table.md` | 管理端 + Chat 契约终态；C 类清单；无 mismatch；`keep_travel_query` |
| 交付 | `docs/delivery/2026-10-22-wiring-delivery.md` | 本文 |
| Chat 门控 | `frontend/src/chat/workMode.ts` | `usesMockAgent` / `usesLiveStream` |
| Chat 测试 | `frontend/src/chat/workMode.spec.ts` | 模式门控单测 |
| Chat 改动 | `frontend/src/chat/App.vue`、`Composer.vue`、`ConversationSidebar.vue` | 默认真实 stream；演示标注 |
| 构建产物 | `frontend/dist/**` | admin/chat/setup/assets/embed.js |
| 挂载 | `backend/oa_agent/main.py`（`_mount_frontend`）、`settings.py`（`frontend_dist`） | 默认 `{REPO_ROOT}/frontend/dist` |

本轮**无**后端薄修复实现文件（Task 3/4 筛选 mismatch 为空）。

## 迁移说明

- 需重新 `cd frontend && npm run build`，并重启后端以加载新 `dist`。
- 环境变量可选：`OA_AGENT_FRONTEND_DIST` 覆盖挂载目录。
- **无 DB / Alembic 迁移**（本轮未改后端业务库结构）。
- 未 `build` 时同源仍可能加载旧静态资源（见 Spec §9）。

## API 说明

- **无新公开 API**；无行为变化类薄修复。
- 管理端 / Chat 现有路径与字段以缺口表为准：P0/P1/P2 均为 `ok` 或非闭环必须的 `be_only`。
- 特例（设计允许）：`/readyz` 裸 fetch；Chat SSE 裸 fetch；对话审计 export Cookie GET。

## 权限与安全

- 管理写仍走 CSRF + `Idempotency-Key` + 权限点；审计失败则操作失败（权威设计不变）。
- Chat ticket 仍仅内存；员工端不接 `/v1/admin/interventions`；`user_confirm` 管理端 resume/terminate 保持 403。
- 密钥只写不读；launch_code / token 不进日志明文与 localStorage；launch 继续 `replaceState` 清除。
- 不伪造指标、健康、成本；无数据显示「暂无数据 / 未检测」。

## 测试结果

| 项 | 结果 | 标注 |
|----|------|------|
| frontend vitest（全量） | 13 files / 80 tests passed（Task 3/4） | 自动化通过 |
| frontend vitest（`src/chat/`） | 13 tests passed（含 workMode 2） | 自动化通过 |
| frontend `npm run build` | vue-tsc 无错；vite build 成功（~8s） | 自动化通过 |
| backend pytest | `uv run pytest -q --tb=line` exit 0（Task 3） | 自动化通过 |
| 手工 admin（登录/指挥舱/Runs/Settings/Tools/无权限） | 未跑后端 | **未执行** |
| 手工 chat + OA（launch → session → SSE / pending 轮询） | 未接 OA/LLM/office | **未执行**（外部依赖未验证） |
| 手工：任务演示不打 `messages/stream` | 未开浏览器 Network | **未执行** |

手工冒烟明细见下文「手工验收清单」；禁止将未执行标为通过。

### Spec §1–§9 覆盖对照

| Spec | 覆盖情况 |
|------|----------|
| §1 目标（管理运维可用 + 员工真实流式） | 契约侧完成；手工验收未执行 |
| §2 非目标 C | 已列入「未完成项（C）」；未实现 |
| §3 方案 1 为主 | 缺口表代码对照完成；方案 2 未跑 |
| §4 管理端矩阵 / 修复原则 | 无 mismatch；写链/空态/权限原则保持 |
| §5 Chat 主路径 / 门控 | Task 2 默认真实 SSE；Mock 仅 `task_demo` |
| §6 错误与安全 | 见「权限与安全」；联调错误体未手工验证 |
| §7 测试标注 | 本表诚实分类 |
| §8 实施顺序 | Task 1→6 已走完；build dist 已做 |
| §9 风险 | 外部依赖未通；须 build 后重启 |

## 未完成项（C）

- 附件上传（Composer 仅提示「尚未接入」，只发文本）
- 员工审批 HTTP（`/v1/chat/approvals`）；禁止接管理端 interventions
- 多会话服务端持久化（`/v1/chat/threads*`）；侧栏会话仅本地内存
- 侧栏 workspace / documents / knowledge / tools / settings 业务模块
- 文档预览 / 知识库
- 多 workflow 列表选择（本轮 `keep_travel_query`）
- `task_demo` / Mock UI 入口进一步弱化（默认已不抢主路径）
- 企微通道改造、多实例部署改造
- **同源手工冒烟与 OA/LLM/office 联调**（方案 2）— 状态：未执行

## 下一阶段计划

1. 按产品优先级推进 C 类（附件 / 审批 / 多会话 / 侧栏模块等），或先做方案 2 外部依赖联调并回填冒烟表。
2. 若联调发现契约/环境问题：回填缺口表 `mismatch` + `fix_in`，再开修补 Task。
3. 多 workflow：仅当列表 API 可用且改动极小时再议 `list_select`；否则继续 `travel_query`。

---

## 前端构建与同源挂载（运维备忘）

- 命令：`cd frontend && npm run build`
- 产物：`frontend/dist/`（`admin/`、`chat/`、`setup/`、`assets/`、`embed.js`）
- 入口：`backend/oa_agent/main.py` → `_mount_frontend`
- 默认：`AppSettings.frontend_dist` = `{REPO_ROOT}/frontend/dist`
- 覆盖：`OA_AGENT_FRONTEND_DIST`
- 缺失 `index.html` / `embed.js` 时返回 `FRONTEND_NOT_BUILT`

## 手工验收清单

| # | 步骤 | 结果 | 备注 |
|---|------|------|------|
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

说明：本轮未启动后端、未接 OA/LLM；#7–#8 及依赖真实环境的项保持「未执行」或后续回填「外部依赖未验证」，禁止无执行标「通过」。
