# O1–O6 纠偏规格（只读口径 → 写闭环 → 多实例 → 多 Agent → 安全）

**日期：** 2026-10-26  
**状态：** 已确认（随总计划执行）  
**权威设计：** [`docs/design/2026-10-09-oa-langgraph-design.md`](../../design/2026-10-09-oa-langgraph-design.md)  
**覆盖：** [`docs/superpowers/plans/2026-10-23-platform-next-roadmap.md`](../plans/2026-10-23-platform-next-roadmap.md) 中未完成的固定 Workflow（D）与多 Agent（B）排序改走本规格 O2 / O5。

---

## 1. 现状结论（已核对代码）

| 域 | 结论 |
|----|------|
| **产品** | 现网是**只读查询助手**，不是「操作 OA 的 Agent」。运行时注册表仅 GET + low + 免确认；确认令牌有实现但生产图未接通；无查→确认→提交闭环。 |
| **命名** | 包名 `mcp/` 实为 Registry/Executor/Catalog/Visibility；Outbound 仅 Noop。Skill=说明+示例+Tool 列表。图 id `travel_query` 实为通用助手。`tenant_id` 一期固定 `dscpa`。 |
| **运行时** | SQLite Checkpointer、进程内 EventSink、Redis 未配→MemoryKV、企微单连接 → **单实例**。上帝图 + 上帝服务；模型写 `$ref` 串联脆弱；回复拼装在图内。 |
| **安全** | 身份注入依赖 office-api 校验 oa≈token；可见≠授权；LTM 进系统提示；对话/model_call 长期留存。 |
| **工程** | 运营后台骨架齐全 ≠ 写业务闭环。未接通能力不得假装已上线。 |

---

## 2. 锁定决断

| ID | 决断 |
|----|------|
| P0 | 一期对外口径=**只读助手**；未接通写 API 时不得宣传「可提交报销」 |
| P1 | 停只读 Tool 盲目扩面；激活仍须 GET/low/免确认 +（O3 起）契约测试绿 |
| P2 | 写路径不开放自由注册非 GET；仅固定写 Workflow 白名单 Tool |
| P3 | 首个写场景=行程报销：查→草稿→确认→提交；OA 未上线前契约+respx 绿、生产 flag 关 |
| P4 | 包 `mcp` → `executor`；Outbound 称「出站连接器」且保持 Noop |
| P5 | `travel_query` → `oa_assistant`；历史 id 保留别名 |
| P6 | 无 LLM：可见 Skill 快捷 + 内置规则；其它明确「需配置模型」 |
| P7 | 多 Agent 排 O5；前提=写闭环可演示 + 非内存会话生产门禁 + 可见性口径诚实 |
| P8 | 生产禁止 MemoryKV（`require_redis`） |

---

## 3. 阶段范围与验收

### O0 规格入库

文档互链无矛盾；交付说明区分「已上线 / 未接通」。

### O1 改名 / 冻结 / 降级

- `executor` 包与 import 全绿；`oa_assistant` 为默认 workflow_id  
- `travel_query` 可读旧 release / 旧 run  
- 文案无「可写 OA / MCP Server 已通」误导  
- 无模型时新 Tool 明确降级话术  

### O2 写闭环

- OpenAPI 契约草图 + Agent 白名单写执行 + `confirmation.issue/verify` 接通  
- 固定图：fetch → draft → await_confirm → submit → respond  
- `write_workflows_enabled` 默认关；探针失败保持关  

### O3 选工具与串联

- Top-K 候选（Skill/关键词）；服务端两轮/规划，禁止模型 `$ref`  
- 契约测试失败不可激活  

### O4 多实例

- Checkpointer 可配 Postgres（或等价）；事件非仅进程内；生产拒 MemoryKV；企微独立 worker 入口  

### O5 多 Agent

- L1：Orchestrator + Domain 提示词/Skill 子集；拆分 chat/service 边界预留  

### O6 安全合规

- 越权探针；LTM 注入防护；对话/model_call 可配保留；可见≠授权文案  

---

## 4. 与既有路线图关系

- E/C/A（会话、可见性、记忆）及员工治理 **已交付**，本规格不重做。  
- 原 D11 写操作 Workflow → **O2**。  
- 原 S5/D13 多 Agent → **O5**（更晚，且加门禁）。  
- 原「MCP=执行平面」用语 → 代码包名落地为 `executor`（O1）。  

---

## 5. 明确不做（直至对应阶段）

自由 POST Tool 给模型；假装 Outbound 已通；未 Redis 的多实例生产；O2 前开多 Agent；未接通写 API 时对外宣称可提交。
