# Agent 运行时契约纠偏：Skill 两级 + 确定性窄门（设计规格）

**日期：** 2026-11-20  
**状态：** 已交付  
**权威设计：** [`docs/design/2026-10-09-oa-langgraph-design.md`](../../design/2026-10-09-oa-langgraph-design.md)  
**相关：** [`2026-10-28-tool-routing-modes-design.md`](./2026-10-28-tool-routing-modes-design.md)、[`2026-10-23-mcp-skill-visibility-design.md`](./2026-10-23-mcp-skill-visibility-design.md)、[`2026-10-27-mcp-builtin-tool-guard-design.md`](./2026-10-27-mcp-builtin-tool-guard-design.md)

> **对外用语：** 员工面不出现「MCP」。MCP 仅为 Tool 的 `kind`。  
> **本期范围：** 只做运行时契约（A）；录入智能化（B）后置，且必须服从本契约。

---

## 0. 问题重定义（非症状）

**表面诉求：** 建 Tool/Skill 表单太重；对话里 Tool/Skill/MCP 调用「乱七八糟」。

**底层目标（已对齐）：** 先把**运行时选路契约**做对并可验收，再让录入为契约服务。  
「少填表」是手段，不是本期目标。

**采纳路径：** 方案 1 — 在现有 `tool_routing.route()` / Executor / Catalog 边界做**契约闸门 + 默认切换**，不大改编排图。

---

## 1. 目标（给实现者的一句话）

让员工对话的选路变为：**确定性窄门 → Skill 两级 → 低置信澄清**；配置生效来源可核对；候选只来自可见目录 Skill 绑定（`builtin` 例外）；MCP/孤儿/Pack 不再污染选路。

---

## 2. 硬约束（不可违反）

1. 与 OA 只走 HTTP；对 `td_oa` 零访问。  
2. LangGraph 只做编排；**模型输出不参与权限判定**。  
3. 管理员与员工两套主体；后台不能直改 Checkpoint。  
4. 不伪造指标；密钥只写不读；员工面不展示内部 mode/MCP 字样。  
5. 管理写 = 权限点 + CSRF + `Idempotency-Key` + 审计。  
6. **写操作**仍只允许固定写 Workflow 白名单，不进入自由选 Tool；写路径低置信也**不猜**。  
7. 配置优先级不变：**工作流发布快照 > 全局 runtime 默认**。  
8. 不自动批量改已发布快照；不废除快照优先。

---

## 3. 已锁定产品决策

| 项 | 决定 |
|----|------|
| 优先级 | 先 A（运行时）再 B（录入智能化） |
| 主契约 | `deterministic_first`，未命中回退 `skill_then_tool` |
| MCP | Tool `kind=mcp`，不单独插队选路 |
| 孤儿 Tool | 对话不可选；入库启用须绑 Skill；仅 `builtin` 可全局 |
| 全局默认 | 改为上述主契约（替换现行 `legacy_prompt` 默认） |
| 旧快照 | 清单标出仍海选项，**人工确认**后迁移 |
| 低置信 | 澄清不猜；候选点选 UI 后置 |
| MCP 同步 | 每 Server 一个目录 Skill；默认同步不可对话，确认后开放 |
| Skill Pack | A 期**不参与**选路；长期再挂到目录 Skill 作说明层 |
| Skill 种类 | **不参与**选路；约束可绑 Tool kind + 后台分组 |
| A 期 Done | 配置真相 + 可解释轨迹 + 回归集 三者齐全 |

---

## 4. 运行时选路契约

**唯一选路入口：** `oa_agent.executor.tool_routing.route()`（`oa_assistant.understand` 只调它）。

**全局默认（须改代码与配置 schema 默认值）：**

| key | 新默认 |
|-----|--------|
| `tool_routing_mode` | `deterministic_first` |
| `deterministic_fallback_mode` | `skill_then_tool` |
| `routing_clarify_on_low_confidence` | `true`（保持） |

**单轮决策序：**

1. 写操作 → 固定写 Workflow（不进自由选 Tool）。  
2. 确定性窄门 → 命中则直接 Tool + 填参；轨迹标记 `source=deterministic`。  
3. Skill 两级 → 仅从「对该员工可见且启用的**目录 Skill**」选 Skill → 候选 Tool = 该 Skill 绑定 ∩ 启用 Tool。  
4. 全局例外 → 未绑 Skill 的 `builtin` 可进候选；其它 kind 孤儿**永不进候选**。  
5. 低置信 → `clarify`，不调用业务 Tool。  
6. Skill Pack → 不贡献 Tool 候选（可仍展示/安装）。

**执行前二次门禁：** 若旁路点到孤儿/不可见 Tool → `TOOL_NOT_AVAILABLE`（友好文案），不上游。

---

## 5. 配置真相与快照迁移

### 5.1 管理端「配置真相」

只读摘要（可挂现有路由观测页），至少包含：

- `global_mode` / `global_fallback`
- `active_workflows[]`：在用工作流的 release、快照内 `tool_routing_mode`、是否与全局一致
- `legacy_prompt_releases[]`（或更广的「非契约默认」）待迁移清单
- 说明：单次对话以**会话绑定 release 快照**为准；无键则回落全局

无数据则显示「暂无」，禁止假装全站已切换。

### 5.2 人工迁移

- 单项「迁移到契约默认」：写入 `deterministic_first` + fallback `skill_then_tool` + clarify=true  
- 二次确认 + 前后 diff；管理写门槛全套；审计如 `routing.snapshot.migrate`  
- 可「标记确认保留海选」以降低清单噪音  
- **禁止**一键改全部已发布；**不改**进行中 Run / Checkpoint

### 5.3 文档与枚举

`legacy_prompt` 标为「兼容/待迁移」，非推荐默认。

---

## 6. 目录闸门：孤儿 / 绑定 / MCP / 种类

### 6.1 运行时候选过滤

| 条件 | 结果 |
|------|------|
| 非 builtin 且未出现在任一可见启用目录 Skill 绑定中 | 剔除 |
| Tool 或 Skill 未启用 | 剔除 |
| MCP 未「确认对员工开放」 | 剔除 |
| 仅由 Skill Pack 引入、无目录绑定 | 剔除 |

### 6.2 入库最小闸门（服务契约，非 B 向导大改）

| 动作 | 规则 |
|------|------|
| 新建/启用非 builtin Tool | 必须至少绑一个目录 Skill；否则拒绝启用（可草稿/禁用） |
| 解绑将导致孤儿 | **拒绝解绑**，提示先改绑或禁用 Tool |
| Skill 种类 → 可绑 Tool kind | 保存时校验；不合法拒绝 |

种类枚举可先最小集合（与现有 Tool kind：`office` / `open_oa_invoke` / `builtin` / `mcp` 对齐的约束表）。

### 6.3 MCP 同步

1. Server 创建/启用 → 确保对应目录 Skill 存在（稳定命名，关联 server id/name）。  
2. 同步 Tool：`kind=mcp`，自动绑到该 Server Skill。  
3. 默认可对话性 = 关；管理端「确认开放」后才进选路候选。  
4. 员工文案不出现 MCP。

### 6.4 历史孤儿

管理端列出孤儿（非 builtin、未绑 Skill）；不自动删除；提供改绑或保持禁用。未处理不阻塞发版（运行时已不可选）。

---

## 7. 可解释轨迹

`routing_trace_enabled=true` 时，单次 understand 至少包含：

| 阶段 | 内容 |
|------|------|
| `config_resolved` | 生效 mode、来源（`global` / `release:<id>`） |
| `deterministic` | 命中/未命中；命中则 tool |
| `skill_select` | 可见 Skill 规模、选中或 clarify |
| `tool_candidates` | 候选列表 + 过滤原因摘要（孤儿/不可见/pack） |
| `tool_select` / `clarify` / `chat` | 最终动作 |

管理端时间线按阶段展示；员工面用中性文案。

---

## 8. 错误与安全

- 不可用/孤儿：统一友好错误，不泄露他人可见性规则细节。  
- 闸门均在服务端；模型不能扩大权限。  
- 迁移、MCP 确认开放、强制绑定相关写：权限 + CSRF + Idempotency + 审计。

---

## 9. A 期回归集（Done 必备）

1. 默认解析为 `deterministic_first` + fallback `skill_then_tool`。  
2. 确定性命中 → 不进入 Skill 海选。  
3. 绑在可见 Skill 下的 Tool 可选中。  
4. 孤儿非 builtin → 不在候选；执行前再拦。  
5. builtin 未绑也可进候选。  
6. 低置信 → clarify，无业务 tool 调用。  
7. MCP 同步默认不可对话；确认开放后可进候选。  
8. Skill Pack 启用不扩大 Tool 候选。  
9. 种类不允许的 Tool kind 绑定保存失败。  
10. 快照仍为 `legacy_prompt` 时 effective 为海选，且出现在待迁移清单。

---

## 10. 明确不做（A 期） / 留给 B

| A 做 | B 做（A 回归保持绿为前提） |
|------|---------------------------|
| 默认模式、闸门、真相页、迁移清单、MCP Server Skill、轨迹、回归 | Tool/业务接入向导少填、模型分析 schema/文案 |
| 入库必须绑 Skill / 种类校验（最小） | Skill 优质说明生成、向导交互大改 |
| Pack 排除选路 | Pack 挂目录 Skill 的说明层产品化 |

B 不得再制造孤儿或绕过种类约束。

---

## 11. 风险

- 现网主工作流若仍钉 `legacy_prompt`：只改全局体感不变 → 依赖迁移清单推进。  
- 历史孤儿突然不可调：契约预期；用清单治理，不恢复海选兼容后门。  
- 旁路若绕过 `route()`：靠 Executor 二次门禁；若仍漏再升级方案 2（大改编排）。

---

## 12. 关键代码锚点（实现时）

- `backend/oa_agent/executor/tool_routing.py` — `ROUTING_DEFAULTS` / `route()`  
- `backend/oa_agent/config/schema.py` — runtime 默认枚举  
- `backend/oa_agent/runtime/graphs/oa_assistant.py` — understand 只经 route  
- `backend/oa_agent/chat/service.py` — `visible_skills_for`  
- `backend/oa_agent/executor/catalog.py` / `admin/catalog_api.py` — 绑定与种类校验  
- MCP：`mcp_sync` / `mcp_servers_api` / Server→Skill  
- 管理端：路由观测 / 配置真相 / 孤儿清单 / 迁移确认  

---

## 13. 验收标准（产品）

管理员能回答：

1. 「当前全局默认是什么？这个对话绑的快照是什么模式？」  
2. 「为什么选了这个 Skill/Tool，或为什么澄清？」  
3. 「哪些发布还在海选、哪些孤儿、哪些 MCP 未开放？」  

且 §9 回归全绿。
