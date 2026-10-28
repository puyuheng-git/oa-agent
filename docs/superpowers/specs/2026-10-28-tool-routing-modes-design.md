# Tool / Skill 路由策略可配置 + 调用过程观测（实现提示词 / 规格）

**日期：** 2026-10-28  
**状态：** **已交付**（2026-10-28）；扩展项见交付 §7 / [`STATUS.md`](../../STATUS.md) X1–X3  
**权威设计：** [`docs/design/2026-10-09-oa-langgraph-design.md`](../../design/2026-10-09-oa-langgraph-design.md)  
**交付：** [`docs/delivery/2026-10-28-tool-routing-modes-delivery.md`](../../delivery/2026-10-28-tool-routing-modes-delivery.md)  
**相关：** O1–O6 纠偏、`executor/`、Top-K（`tool_select`）、固定写 Workflow  

> **用法：** 历史实现提示词；冲突时以权威设计硬约束为准。  
> **对外用语：** 员工面不出现「MCP」。代码包为 `executor`；出站连接器未接通时页面标注「未配置 / Noop」，禁止假装已通。

---

## 1. 目标（给实现者的一句话）

在后端把「如何从员工自然语言落到 Tool 调用」做成**可配置的路由模式**；关键步骤阈值由配置控制；管理后台新增页面，能看到每次运行的 **Skill / Tool /（出站）连接器** 调用过程时间线，并提供**真实统计详情**（无数据则「暂无数据」）。

---

## 2. 硬约束（不可违反）

1. 与 OA 只走 HTTP；对 `td_oa` 零访问。业务数据只来自 office-api 员工 token。  
2. LangGraph 只做编排；**模型输出不参与权限判定**。路由只影响「候选可见性」，执行仍走注册表 + 身份注入 + office-api。  
3. 管理员与员工两套主体；后台不能直改 Checkpoint。  
4. 不伪造指标；密钥只写不读；不展示模型隐藏推理链。  
5. 管理写 = 权限点 + CSRF + `Idempotency-Key` + 审计。  
6. **写操作**仍只允许固定写 Workflow 白名单，不进入自由选 Tool 模式。  
7. 现网可能只有 2 个只读 Tool：默认模式必须在此场景下行为正确、可测。

---

## 3. 路由模式（配置枚举）

配置键建议：工作流发布配置 `content_json.tool_routing_mode`（随 release 绑定，运行中不变）  
**同时**在配置中心 `runtime` 组提供**全局默认**（热生效仅影响「新运行读默认」；已绑定 release 的运行仍用快照）。  
优先级：**本次运行绑定的 workflow 发布快照 > 全局默认**。

| 模式 ID | 名称 | 行为摘要 |
|---------|------|----------|
| `legacy_prompt` | 提示词海选（兼容） | 可见 Tool 全量（或 Top-K）说明书塞进系统提示，模型一次选出并填参。**默认过渡模式**；Tool≤`prompt_topk` 时等同全量。 |
| `skill_then_tool` | 两级路由 A | 先选 Skill（规则/小模型/主模型，由子配置决定），再仅把该 Skill 下 Tool 说明书交给填参模型。不确定则澄清，不猜 Tool。 |
| `retrieve_then_tool` | 检索召回 B | Embedding/关键词索引召回 Top-N Tool（可加「最近用过」「规则强命中」必留），再交给模型精选填参。无向量后端时降级为关键词检索并在事件中标明 `fallback=keyword`。 |
| `meta_search` | 元工具渐进披露 C | 模型常驻 `search_capabilities` / `get_tool_schema`（服务端实现的元能力，不算业务 Tool）；按需拉取 schema 后再选业务 Tool。步数受 `meta_max_rounds` 限制。 |
| `deterministic_first` | 确定性优先 D | 先跑规则 / `plan_list_then_detail` / 固定意图表；命中则**不**把业务 Tool 说明书塞给模型。未命中再回退到 `deterministic_fallback_mode`（默认 `skill_then_tool`）。 |
| `router_then_fill` | 小路由大填参 E | 路由阶段只用便宜模型或分类提示（只输出 skill/tool/clarify）；填参阶段用主模型且只带 1 个 Tool schema。 |

**明确不做（本期）：** 自由注册非 GET 业务 Tool；假装 Outbound MCP 已通；未配置向量库时强依赖向量。

---

## 4. 配置项设计

### 4.1 配置中心 `runtime`（全局默认，热生效）

在 `oa_agent/config/schema.py` 的 `runtime` 组增加字段（均带 `help` / `min` / `max` / `default`）：

| key | 类型 | 默认 | 说明 |
|-----|------|------|------|
| `tool_routing_mode` | string/enum | `legacy_prompt` | 全局默认路由模式（上表 ID） |
| `prompt_topk` | int | 8 | `legacy_prompt` / 召回后精选上限；≤该值不截断 |
| `routing_skill_method` | enum | `rules_then_llm` | A：`rules` / `llm` / `rules_then_llm` |
| `retrieve_topk` | int | 8 | B：召回条数 |
| `retrieve_backend` | enum | `keyword` | B：`keyword` / `embedding`（embedding 未就绪则强制 keyword + 事件标记） |
| `retrieve_must_include_recent` | int | 2 | B：必留「本线程最近用过」Tool 数 |
| `meta_max_rounds` | int | 3 | C：元工具往返上限 |
| `deterministic_fallback_mode` | enum | `skill_then_tool` | D 未命中时的回退模式（禁止再设为 `deterministic_first` 防递归） |
| `router_model_id` | string/null | null | E：路由用模型；空则用默认模型 |
| `routing_clarify_on_low_confidence` | bool | true | 低置信时向员工澄清而非强行选 Tool |
| `routing_trace_enabled` | bool | true | 是否写入路由过程事件（关闭则仅保留 tool_call_*，统计页显示能力降级说明） |

工作流草稿 schema（`workflows`）同步增加同名字段，发布进 `content_json`；校验：enum 合法、D 的 fallback 不能指向自己。

### 4.2 不做成配置的

- 权限点、表名、事件 `event_type` 枚举扩展需改代码。  
- 写 Workflow 白名单、身份注入规则。  
- embedding 模型 API Key（若做 embedding：走现有 LLM/密钥保险箱，不另开明文配置）。

---

## 5. 运行时改造要点

### 5.1 统一「路由流水线」接口

在 `oa_agent/executor/` 或 `oa_agent/runtime/` 新增例如 `tool_routing.py`：

```text
route(message, ctx) -> RoutingDecision
  - mode, stages[], candidate_skills[], candidate_tools[],
    chosen_skill?, chosen_tool?, args?, action(tool|chat|clarify|help),
    clarify_question?, fallback_from?
```

`oa_assistant.understand` **只调用**该入口，删除散落的「仅 Top-K」隐式逻辑或将其收编为 `legacy_prompt` 的一步。

### 5.2 每阶段必须打点（`routing_trace_enabled=true` 时）

扩展 `RunRecorder.event`，建议 `event_type`：

| event_type | 含义 | metadata 要点 |
|------------|------|----------------|
| `routing_start` | 开始路由 | mode, message_chars（不要存全文到 metadata 若已有 run_start） |
| `routing_stage` | 某一阶段结束 | stage=`skill_select`\|`retrieve`\|`topk`\|`meta_search`\|`deterministic`\|`router_llm`\|`fill_args`, duration_ms, candidates[], scores?, backend? |
| `routing_decision` | 最终决定 | action, skill, tool, fallback_from, clarify? |
| `routing_clarify` | 向员工澄清 | question |
| 已有 `tool_call_start/end` | 真实执行 | 不变；额外 metadata：`routing_mode`, `via_stage` |

**禁止**在事件里写 office token、密钥、完整业务明细；候选列表只存 tool/skill **name** 与分数。

### 5.3 模式实现最小集（分期可砍，但接口一次留好）

| 模式 | 本期必须可运行 | 可后置 |
|------|----------------|--------|
| `legacy_prompt` | 是（包装现逻辑） | — |
| `skill_then_tool` | 是（Skill≤1 时退化为只暴露其 Tool） | 独立小模型 |
| `retrieve_then_tool` | 是（keyword 后端） | embedding |
| `deterministic_first` | 是（接现有 `intent_rules` + `plan_list_then_detail` 真正调用） | 更多意图表 |
| `meta_search` | 是：`search_capabilities` / `get_tool_schema` + `meta_max_rounds`；无模型时服务端推进 | embedding 增强检索 |
| `router_then_fill` | 可与 `skill_then_tool` 共用选 Skill，填参只带 1 schema | 专用 router_model |

未完工模式：配置校验允许保存，但 `readyz` / 配置页标注「部分实现」；选中后运行走明确降级并 `fallback_from` 记事件——**不得静默当成 legacy**。

### 5.4 修已知债（顺手必做）

- `plan_list_then_detail` 必须在 `deterministic_first`（及可选 legacy 多步）**真正调用**，禁止只 import 不用。  
- 若采用服务端串联，收敛或关闭模型 `$ref` 提示，避免双路径。

---

## 6. 管理后台：新页面「调用过程 / 路由统计」

### 6.1 菜单

- 分组：`monitor`（运行监控）  
- 路径：`/routing`（或 `/tool-calls`）  
- 标题：`调用过程`  
- code：`ROUTING`  
- 权限：`ops.run.view`（详情里若展示员工原话已有敏感字段，沿用现网 runs 同一套脱敏；完整对话仍要 `ops.run.view_sensitive`）  
- `frontend/src/admin/router.ts` 注册；图标可用 `Share` 或 `DataLine`。

### 6.2 页面结构（两 Tab）

**Tab1：过程明细（单次运行）**

- 筛选：`run_id` / `oa` / 时间 / `routing_mode` / `tool` / `skill` / 是否澄清 / 是否 fallback  
- 列表列：时间、run_id、oa、mode、stages 摘要、最终 skill/tool、action、耗时、tool_call 成败  
- 点开抽屉/详情：  
  - **路由时间线**：routing_* 事件竖向展示（候选、分数、耗时）  
  - **执行时间线**：tool_call_*（可深链到现有 `/runs/:run_id`）  
  - **出站连接器**：若有 Outbound 调用记 `connector_call_*`；Noop/未配置显示「未使用 / 未配置」，禁止假绿色成功  

**Tab2：统计详情**

时间范围 + 缓存沿用 `stats_cache_seconds`。指标必须来自库内真实聚合：

| 指标 | 口径 |
|------|------|
| 运行数（按 mode 分组） | routing_decision 或 run 上冗余字段 |
| 各 mode 占比 | 同上 |
| Tool 调用次数 / 成功率 | tool_call_end status |
| 路由后澄清率 | routing_clarify / 有 routing_decision 的运行 |
| fallback 率 | metadata.fallback_from 非空 |
| 平均 routing 耗时、平均 tool 耗时 | 事件 duration_ms |
| Top Tool / Top Skill | 按调用次数；无数据「暂无数据」 |
| 误选相关（可选一期） | 若有员工重试/立即换 Tool 的启发式，无则显示「未检测」 |

样本不足时 P95 显示「样本不足」（沿用 `p95_min_samples`）。

### 6.3 API 草案

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/v1/admin/routing/runs` | `ops.run.view` | 分页列表，支持上表筛选 |
| GET | `/v1/admin/routing/runs/{run_id}` | `ops.run.view` | 该 run 的 routing 事件 + tool_call 摘要 |
| GET | `/v1/admin/routing/stats` | `ops.run.view` | Tab2 聚合；`range` 查询参数 |

写配置仍走现有 `/v1/admin/settings/runtime` 与 workflows 草稿发布，不新造平行配置 API。

### 6.4 数据模型

优先：**不新表**，用 `agent_run_event` 的新 `event_type` + `metadata_json`。  
可选增强（若列表性能不够）：`agent_run` 增加可空列 `routing_mode`、`routing_tool`、`routing_skill`（在 `routing_decision` 时写入），Alembic 迁移；查询层带 `tenant_id`。

---

## 7. 前端与文案

- Vue 3 + Element Plus，风格与 `RunsView` / `RunDetailView` 一致。  
- 设置页 `runtime` 组自动渲染新 FieldDef（现有 Settings 动态表单则无需特写；若 enum 需下拉，按 schema 扩展）。  
- 流程配置页增加「工具路由」一节，与全局默认的差异在 diff 中可见。  
- 文案用「执行器 / 出站连接器」，避免对管理员暗示「标准 MCP 已通」。

---

## 8. 测试要求

自动化（pytest）：

1. 各 mode 在「仅 2 个行程 Tool」下：能选 list/detail 或澄清，不 500。  
2. `legacy_prompt` + `prompt_topk=8`：2 Tool 全进候选。  
3. `skill_then_tool`：多 Skill fixture 时候选 Tool 不跨 Skill。  
4. `deterministic_first`：命中规则时**不**调用模型选 Tool（mock llm 断言）。  
5. `plan_list_then_detail` 被调用的集成断言。  
6. `routing_*` 事件在 `routing_trace_enabled=true` 时出现；false 时不出现。  
7. stats API：插入已知事件后数字一致；空库「暂无数据」。  
8. 权限：无 `ops.run.view` → 403。  

手工 / 外部依赖：真 LLM、真 embedding——交付报告标明「未执行 / 外部依赖未验证」，禁止标通过。

---

## 9. 交付物清单

- [x] `config/schema.py` 字段 + workflows schema  
- [x] `tool_routing` 模块 + `oa_assistant` 接入  
- [x] 事件类型（未做可选 run 冗余列迁移）  
- [x] admin API + 前端 `/routing` 页 + 菜单  
- [x] 测试 + 交付说明（功能/文件/API/权限/测试结果/未完成项）  
- [x] 权威设计文档增补「工具路由模式」§8.1.1  
- [x] **扩展 X1：** `router_model_id` 真接线（`stage=router` / `fill`）  
- [ ] **扩展：** embedding 后端、管理端手工验收（见 STATUS X2–X3）

---

## 10. 给实现 Agent 的执行顺序

1. 加配置字段与校验（含 D 防递归）。  
2. 抽出 `route()`，先实现 `legacy_prompt` 包装现逻辑 + 打点。  
3. 实现 `skill_then_tool`、`deterministic_first`（含真正调用 `plan_list_then_detail`）。  
4. keyword 版 `retrieve_then_tool`。  
5. admin API + 统计 + 前端页。  
6. `meta_search` / `router_then_fill` 能降级运行或标明部分实现。  
7. 全量 pytest；更新交付文档。

---

## 11. 验收口令

- 管理员可在「连接配置 / 流程配置」切换路由模式，新运行事件里能看到对应 `routing_mode`。  
- 「调用过程」页能打开某次 run 的 Skill→候选→决策→Tool 执行链。  
- 统计页数字与库内事件一致，无数据不造假。  
- 写路径与权限硬约束不被绕过。
