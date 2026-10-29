# 交付说明：Tool/Skill 路由策略可配置 + 调用过程/统计

**日期：** 2026-10-28  
**规格：** `docs/superpowers/specs/2026-10-28-tool-routing-modes-design.md`  
**权威设计增补：** `docs/design/2026-10-09-oa-langgraph-design.md` §8.1.1  

---

## 1. 功能

1. 可配置路由模式（工作流发布快照优先，否则 runtime 全局默认）：`legacy_prompt` / `skill_then_tool` / `retrieve_then_tool` / `meta_search` / `deterministic_first` / `router_then_fill`。
2. 统一 `tool_routing.route()`；`oa_assistant.understand` 只走该入口；`deterministic_first` 真正调用 `plan_list_then_detail`。
3. `routing_trace_enabled` 时写入 `routing_*` 事件；关闭则仅保留既有 `tool_call_*`。
4. 管理端 monitor 组菜单「调用过程」`/routing`：过程明细 + 真实统计；无数据「暂无数据」。
5. API：`GET /v1/admin/routing/runs`、`.../runs/{run_id}`、`.../stats`；权限 `ops.run.view`。

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/oa_agent/config/schema.py` | runtime 路由字段 |
| `backend/oa_agent/config/service.py` | `validate_runtime_routing`（D 防递归） |
| `backend/oa_agent/runtime/releases.py` | workflows「工具路由」FIELDS + 校验 + `merge_release_config` |
| `backend/oa_agent/executor/tool_routing.py` | 统一 `route()` 与各模式 |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | DEFAULT_CONFIG 路由键；`_understand` 只调 `route()` |
| `backend/oa_agent/chat/service.py` | 注入 `runtime_routing` / 线程最近 Tool |
| `backend/oa_agent/admin/routing_api.py` | 管理端只读 API |
| `backend/oa_agent/main.py` | 注册 routing 路由 |
| `frontend/src/admin/router.ts` | 菜单 ROUTING |
| `frontend/src/admin/routing.ts` | 类型与格式化 |
| `frontend/src/admin/views/RoutingView.vue` | 两 Tab 页面 |
| `backend/tests/test_tool_routing.py` | 各 mode / 事件开关 / plan 调用 |
| `backend/tests/test_routing_api.py` | stats 一致 / 403 / 空库 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §8.1.1 |
| `docs/delivery/2026-10-28-tool-routing-modes-delivery.md` | 本文 |

未新增 Alembic 表/列（优先用 `agent_run_event`）。

---

## 3. 迁移说明

- 无库表迁移。
- 旧发布快照若未写出路由键：运行时叠 `runtime` 全局默认（热）；写出后以快照为准。
- 初始 seed 发布仍含完整 DEFAULT_CONFIG（含路由键）。

---

## 4. API 说明

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/v1/admin/routing/runs` | `ops.run.view` | 分页列表；筛选 run_id/oa/mode/tool/skill/clarified/fallback/时间 |
| GET | `/v1/admin/routing/runs/{run_id}` | `ops.run.view` | routing + tool_call 时间线；出站未配置显示「未使用 / 未配置」 |
| GET | `/v1/admin/routing/stats` | `ops.run.view` | 聚合；沿用 `stats_cache_seconds` / `p95_min_samples` |

写配置仍走 `/v1/admin/settings/runtime` 与 workflows 草稿发布。

---

## 5. 权限与安全

- 只读 API：`ops.run.view`；无权限 → 403。
- 路由不参与权限判定；写操作仍只走固定写 Workflow。
- 事件 metadata 不含 office token / 密钥 / 业务明细全文。
- 对外文案用「执行器 / 出站连接器」；不宣称 MCP 已通。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `tests/test_tool_routing.py`（各 mode、deterministic 不调选 Tool 模型、plan_list_then_detail、trace 开关、meta 元工具/多轮/超限澄清、配置优先级） | **自动化通过** |
| `tests/test_routing_api.py`（stats 与插入事件一致、空库、403） | **自动化通过** |
| `tests/test_prompt_guard.py`（understand 接入） | **自动化通过** |
| 真 LLM 端到端各 mode | **未执行 / 外部依赖未验证** |
| embedding 召回 | **未执行**（本期强制 keyword 降级） |
| 管理端「调用过程」页手工点选 | **未执行**（需本地起前后端） |
| 真实出站连接器时间线 | **外部依赖未验证**（无配置时展示「未使用 / 未配置」） |

---

## 7. 未完成项

- `retrieve_backend=embedding` 真实向量后端（STATUS **X2**）。
- ~~`router_model_id` 独立小模型调用~~ → **已接线**（`stage=router` / `stage=fill`；见 STATUS **X1**）。
- 可选：`agent_run` 冗余列 `routing_mode` 等以优化大列表。
- 误选启发式：统计页固定「未检测」。
- `meta_search` 真 LLM 多轮端到端（自动化已覆盖服务端推进与 llm meta 协议；真模型 **外部依赖未验证**）。

---

## 8. 下一阶段建议

见 [`docs/STATUS.md`](../STATUS.md)：

1. **X4** catalog 测试失败归属。  
2. **X3** 手工验收管理端两 Tab、配置中心 enum，以及 `meta_search` 真模型多轮。  
3. **X2** embedding 索引与密钥走现有 LLM/Vault。
