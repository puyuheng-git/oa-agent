# O1–O6 纠偏交付说明（2026-10-26）

**规格：** [`docs/superpowers/specs/2026-10-26-remediation-o1-o6-design.md`](../superpowers/specs/2026-10-26-remediation-o1-o6-design.md)  
**权威设计：** 已同步修订 `docs/design/2026-10-09-oa-langgraph-design.md` / OA 侧配套 / 平台路线图覆盖说明。

## 功能

| 阶段 | 状态 | 要点 |
|------|------|------|
| O0 | 已上线（文档） | 纠偏规格入库；一期=只读助手口径；写依赖 OA MVP-3 |
| O1 | 已上线 | `executor/` 包；`oa_assistant` 主图；`travel_query` shim；无模型降级话术 |
| O2 | 已实现（flag 默认关） | 写契约 YAML + 白名单写执行 + 确认 API + 固定写图；**真 OA 写 API：外部依赖未验证** |
| O3 | 已实现 | Top-K 选工具；服务端 `plan_list_then_detail`；契约检查门禁 |
| O4 | 部分 | `require_redis`；checkpointer postgres 可配（回退 sqlite）；EventSink sync_write；wecom_worker 入口 |
| O5 | 骨架 | L1 `multi_agent.Orchestrator`；未挂主引擎 |
| O6 | 部分 | 记忆注入过滤；对话/model_call 保留清理；写路径越权探针；可见≠授权口径在设计文档 |

## 测试结果

- **自动化通过：** `backend` 全量 `pytest`（纠偏相关含 write/alias/multi_agent/tool_select/memory_guard/retention/require_redis/chain_plan/contract/authz 等）已绿。
- **手工：** 未执行。
- **外部依赖未验证：** office-api 草稿/提交真接口；Postgres checkpointer 真库；企微多实例租约。

## 迁移说明

- 新 Workflow 发布 id=`oa_assistant`；旧 `travel_query` 经 shim/API 别名可读。
- `WORKFLOW_VERSION=5`：挂起在 v4 的介入任务不可恢复（与设计一致）。
- 生产建议：`OA_AGENT_REQUIRE_REDIS=true`；写能力需显式打开 `runtime.write_workflows_enabled`。

## 未完成 / 下一阶段

- 真 OA 写 API 联调后开 flag。
- Checkpointer 默认迁出 SQLite；企微 worker 租约。
- O5 挂接引擎路由；可见性 TagProvider 真源。
- 对话保留策略挂管理 UI / 定时任务。
