# Multi-System Platform M5 — 产品化（连接器/包管理 UI · 去 OA 中心化文案 · 接入手册）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管理员在后台完成「连接器实例 + 领域包启停 + IdP/demo 开关」的可视治理；员工/运营文档按**平台 + Pack**表述；补齐演示 Pack 与《新系统接入》手册，使有 API 的外部系统可在约一天内对接（不含对方改接口时间）。

**Architecture:** 复用 M2 ConnectorHub / envelope、M3 `/v1/admin/packs`、M4 IdP/demo。M5 以**管理端产品面 + 文案/手册**为主：新增 Packs 页面；将「OA 对接」配置组展示为「连接器 / 业务上游」；可选轻量 Connectors 只读总览 API；Routing 页展示 `connector_id` / `pack_id`；不重命名 Python 包 `oa_agent`、不上传 Pack zip。

**Tech Stack:** Vue 3 + Element Plus、现有 admin `http.ts`、FastAPI admin API、pytest / Vitest。

**规格：** [`docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`](../specs/2026-10-28-multi-system-platform-design.md) §6.4 / §8 / §9 M5  
**前置：** M1–M4 已交付。

## Global Constraints

- 硬约束：对 `td_oa` 零访问；模型不参与权限；密钥只写不读；管理写=权限+CSRF+Idempotency-Key+审计。  
- Pack：**本机目录 + 后台启停**；不上传 zip。  
- 不重命名仓库/包名 `oa_agent`（成本大、收益低）；**产品文案**去 OA 中心化即可。  
- 现网 office 上游与 `oa_travel` 默认启用行为不变。  
- 不伪造指标；无数据「暂无数据」。  
- 中文文档；英文标识符。用户未要求不强制每 Task commit。

## File map（M5）

| 路径 | 职责 |
|------|------|
| `frontend/src/admin/views/PacksView.vue` | 领域包列表 / 启停 |
| `frontend/src/admin/packs.ts` | API 客户端类型 |
| `frontend/src/admin/router.ts` | 菜单「领域包」 |
| `frontend/src/admin/views/SettingsView.vue` + schema labels | 「OA 对接」→「连接器 / 业务上游」等文案 |
| `frontend/src/admin/views/RoutingView.vue` | 展示 connector_id / pack_id（若事件已有） |
| `backend/oa_agent/admin/connectors_api.py` | 可选：只读连接器总览（office upstreams + mcp + builtin） |
| `backend/oa_agent/config/schema.py` | 组/字段 `label`/`help` 去 OA 中心化；可选 `idp.channel_idp_map`（若支持 dict/json 字符串） |
| `packs/demo_http/` | 补齐最小 openapi 示例或文档内 mock 步骤 |
| `docs/ops/integrate-external-system.md` | 《新系统接入》手册（&lt;1 天路径） |
| `docs/delivery/2026-10-29-multi-system-m5-delivery.md` | 交付 |
| `docs/STATUS.md` | M5 完成；平台路线收官说明 |

---

### Task 1: 管理端「领域包」页面（对接已有 packs API）

**Files:**
- Create: `frontend/src/admin/packs.ts`
- Create: `frontend/src/admin/views/PacksView.vue`
- Modify: `frontend/src/admin/router.ts`（ability 组，perm=`ops.tool.manage` 与后端一致）
- Test: `frontend` Vitest 轻量（API 模块 mock）或手工清单写入交付

**UI：**
- 表格：id、显示名、version、enabled、connectors、validation_errors  
- 操作：启用 / 禁用（写链经 `http.ts`：CSRF + Idempotency）  
- 空态「暂无数据」

- [ ] **Step 1: 对接 GET/POST packs API**
- [ ] **Step 2: 菜单注册**
- [ ] **Step 3:** `npm run test` / `vue-tsc` 相关不破

---

### Task 2: 设置页文案去 OA 中心化 + IdP 组可见

**Files:**
- Modify: `backend/oa_agent/config/schema.py` — `oa` 组 `description`/`label` 改为「业务上游 / 连接器（兼容原 OA 对接）」；`idp` 组确保后台可展示  
- Modify: `frontend/.../ToolsView.vue`、`catalogForm.ts` 等提示「系统设置 → OA 对接」→「连接配置 → 业务上游」  
- 兼容：配置组 **key 仍为 `oa`**（避免迁移），仅展示名变更

- [ ] **Step 1: schema labels**
- [ ] **Step 2: 前端 hint 字符串替换**
- [ ] **Step 3: settings 相关测绿**

---

### Task 3: 连接器只读总览 API + 可选页面

**Files:**
- Create: `backend/oa_agent/admin/connectors_api.py`  
  `GET /v1/admin/connectors` → items: `{id, kind: http|mcp|builtin, label, envelope_profile?, health: configured|missing}`  
  数据源：oa upstreams + MCP servers 列表 + builtin 固定项；**只读**  
- Modify: `main.py`  
- 可选：`ConnectorsView.vue` 或并入 Settings 顶部卡片  
- Test: `tests/test_connectors_api_m5.py`

权限：`sys.setting.view` 或 `ops.tool.manage`。

- [ ] **Step 1–3: API + 测；UI 至少一处展示**

---

### Task 4: 调用过程页展示 connector_id / pack_id

**Files:**
- Modify: `frontend/src/admin/views/RoutingView.vue`、`routing.ts`  
- 后端若 metadata 已有 `connector_id`：列表/详情列展示；`pack_id` 若事件尚无则从 run 或 routing_decision 扩展（可选：`routing_decision` metadata 增加 `pack_ids` 来自 enabled packs — 最小可只做 connector_id）

- [ ] **Step 1: 确认事件字段**
- [ ] **Step 2: UI 列**
- [ ] **Step 3: 无数据不造假**

---

### Task 5: demo_http 可运行说明 + 手册

**Files:**
- Enhance: `packs/demo_http/` README 或规则；可选 `docs/ops/demo-idp.md`  
- Create: `docs/ops/integrate-external-system.md`  
  步骤：① 配 HTTP 上游/信封 ② 写 Tool/Skill 或 Pack ③ IdP（OA/企微/demo）④ 启停 Pack ⑤ 验收清单  
- Update: `docs/ops/user-guide.md` / `docs/README.md` 链接  

验收口令文案：**「有稳定 HTTP JSON API 时，按手册可在一个工作日内完成 Agent 侧接入（不含对方改接口）。」**

- [ ] **Step 1: 手册初稿**
- [ ] **Step 2: demo 开关与测试引用手册路径**
- [ ] **Step 3: docs README 索引**

---

### Task 6:（可选增强）channel→IdP 映射配置

若 schema 仍无 dict kind：用 `string` JSON 字段 `channel_idp_map_json` 默认 `{"oa_web":"oa_assertion","wecom":"wecom","demo":"demo"}`，Broker/渠道路由读取；非法 JSON 回落默认。  
不做则在交付「未完成」列出（M4 已记）。

- [ ] **Step 1–3: 有则测解析；无则跳过并文档化**

---

### Task 7: 全量回归 + 交付 + STATUS 收官

- [ ] **Step 1:** `cd backend && uv run pytest -q`；`cd frontend && npm run test`（及必要 `vue-tsc`）  
- [ ] **Step 2:** `docs/delivery/2026-10-29-multi-system-m5-delivery.md`  
- [ ] **Step 3:** STATUS：M5 ✅；多系统平台 M0–M5 **产品化收官**（OIDC 完整实现仍非目标）  
- [ ] **Step 4:** 规格 §12 标注 M5 计划路径；用户要求时 commit/push  

---

## M5 明确不做

- 完整 OIDC 联调  
- Pack zip 上传 / 远程市场  
- 重命名 `oa_agent` 包或数据库去 `oa` 列  
- 拖拽编排 IDE  
- 真 OA 手工联调标「通过」  

## 验收口令

1. 管理员能在 UI 启停 `oa_travel` / 看到 `demo_http`。  
2. 设置页不再以「只有 OA」为唯一叙事；上游/IdP/demo 可发现。  
3. 《新系统接入》手册入库并链到 docs README。  
4. 自动化测绿；手工 UI 在交付中分列「未执行/已执行」。  

完成后多系统主线 **M0–M5 收官**；后续为增量（OIDC 真做、embedding、多实例等 STATUS X 项）。
