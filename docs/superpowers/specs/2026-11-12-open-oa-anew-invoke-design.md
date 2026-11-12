# open-oa ANew / Export 通用接入设计

| 项 | 内容 |
|----|------|
| 日期 | 2026-11-12 |
| 状态 | **已确认**（头脑风暴 §1–§4 用户通过） |
| 范围 | Export → open-oa 清单/通用 invoke → Agent Tool；mint 迁入 open-oa；行程报销改走 ANew；office-api Agent 路径本期强拆下线 |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md`（冲突时以该文档为准） |
| OA 落地仓库 | `D:\MYOA\webroot\puyueheng\site\open-oa`（**不写 office-api**） |
| 后续形态 | 本期方案 2；协议预留迁 MCP（方案 3），本期不实现 MCP Server |

### 已锁定决断

| ID | 选择 | 含义 |
|----|------|------|
| **D1** | 完整流水线 | Export → HTTP → Tool，并解决对话内选用/调用 |
| **D2** | Agent 后台为员工启用真相源 | catalog 有 ≠ 员工能用；勾选启用才进对话 |
| **D3** | 通用 invoke | `POST /agent/invoke`，body 含 `service` / `method` / `args` |
| **D4** | 读写均可（按登记） | 写必须确认 + 幂等 + Service 重校验 |
| **D5** | OA 提供清单 | `GET /agent/export-catalog`；Agent 勾选导入后再微调 |
| **D6** | 先方案 2，预留方案 3 | catalog 可留 MCP 扩展字段；本期不做 MCP Server |
| **D7** | 业务 HTTP 面 = open-oa | 原计划写在 office-api 的 Agent 能力全部平替到 open-oa；文案/配置字眼用 open-oa |
| **D8** | mint 迁 open-oa | `POST /agent/token/mint` 只在 open-oa |
| **D9** | 行程报销走 ANew | 业务在 Service；Agent 经 invoke 调用，不再经 office-api |
| **D10** | 本期强拆 | 下线 office-api 上对应 Agent 路由与 Agent 侧 office-api 业务依赖，不双轨 |

**实施路径：** open-oa 落地 mint + catalog + invoke；Service 为可暴露 Export 挂最小契约；Agent 上游改为 open-oa、catalog 导入 Tool/Skill；强拆 office-api Agent 路径；行程只读/写经 invoke 回归。

---

## 1. 背景与目标

**现状：**

- Agent 通过 HTTP Tool 调业务上游；历史上文档与实现多以 **office-api** 为面。
- OA Service 业务能力以 `ANew('module/service')->method` / `Export` 为真相；为 Agent 逐个写 Controller 成本高。
- 行程报销业务逻辑在 Service；继续为 Agent 维护 office-api 专用路由属于重复面。

**目标：**

1. 用 **open-oa** 作为 Agent 唯一业务 HTTP 面：换票、能力清单、通用调用。
2. 快速把已有 Export 按需标契约 → 进 catalog → Agent 勾选启用 → 对话可调。
3. 行程报销等能力经 ANew 调通后，Agent **不再依赖 office-api**；本期强拆对应旧路径。
4. 协议预留日后把同一批能力暴露为 MCP，本期不实现。

**非目标（本期）：**

- Agent 直连 `td_oa` 或进程内 `ANew`
- 用模型做权限判定
- 标准 MCP Server 入站全家桶
- 全量无差别暴露全部历史 Export

---

## 2. 总体架构

```text
员工对话
   ↓
Agent（LangGraph）
   ├─ 运行时只看到「已启用」的 Tool
   ├─ 读：直接 tool call
   └─ 写：确认 + Idempotency-Key 后再调
   ↓  员工 token（不下发浏览器）
open-oa
   ├─ GET  /agent/export-catalog
   ├─ POST /agent/invoke
   └─ POST /agent/token/mint
   ↓
Service：ANew(service)->method(...)
```

**硬边界：**

1. Agent **永不**直接 `ANew`，只调 open-oa。
2. invoke **只允许** 已标注契约且在运行时白名单内的方法。
3. 身份只信员工 token；模型/客户端自报 `oa` 等身份字段一律丢弃。

**命名：** 设计、配置、文档、实现中本链路一律称 **open-oa** / `open_oa`，不再用 office-api 称呼该上游。

---

## 3. 组件职责

### 3.1 open-oa

| 能力 | 路径 | 调用方 | 说明 |
|------|------|--------|------|
| 换票 | `POST /agent/token/mint` | 仅 Agent（`AGENT_GATEWAY_SECRET`） | `oa` 或 `wework_user_id` 二选一 → 员工 token |
| 清单 | `GET /agent/export-catalog` | Agent 管理端导入 | 可暴露的 `service.method` + 契约元数据 |
| 调用 | `POST /agent/invoke` | Agent 运行时（员工 token） | 白名单内转发 `ANew(service)->method(args)` |

路径前缀以 open-oa 路由惯例为准；语义不变。

### 3.2 Service / Export

- 为可暴露方法挂**最小契约**（见 §4）。
- 业务权限、数据范围、写路径重校验与幂等仍在 Service（如 `DuplicateSubmit`）。
- 未标注契约的方法：不进 catalog；invoke 拒绝。

### 3.3 Agent

- 业务上游配置指向 **open-oa**（`base_url`；mint 可同域）。
- 管理端：拉 catalog → 勾选 → 生成/更新 Tool → 绑定 Skill；**最终对员工是否启用由 Agent 决定**。
- Executor：读直调 invoke；写经确认后再调；按 `result_fields` 裁剪后再给模型。
- 预留：catalog 条目可含 MCP 扩展字段，供日后方案 3；本期不同步 MCP。

---

## 4. Export 最小契约

每条可暴露能力至少包含：

| 字段 | 含义 |
|------|------|
| `service` | ANew 名，如 `oa/travel_expense` |
| `method` | 方法名，如 `list` / `detail` |
| `op` | `read` \| `write` |
| `risk` | `low` \| `medium` \| `high` |
| `params` | 名称、类型、必填、说明（**不含**身份字段） |
| `returns` | 建议返回字段 / 列表列（Agent 白名单初值） |
| `summary` | 一句话说明 |
| `extensions`（可选） | 如 `mcp` 预留，本期可忽略 |

契约落地形态（注解 / 配置表 / 集中 manifest）在 **open-oa + Service 实现计划**中选定；须满足：catalog 可枚举、invoke 可校验。

---

## 5. catalog → Agent Tool 映射

导入时核心映射：

| Tool 字段 | 来源 |
|-----------|------|
| `name` | 规范化 `service_method`（如 `travel_expense_list`） |
| `upstream` | `open_oa` |
| 调用 | `POST /agent/invoke` |
| 固定载荷 | `{ service, method }`（模型不可改） |
| `model_params` | catalog.`params`（可后台微调） |
| `result_fields` | catalog.`returns`（可收紧；凭据类字段不得放入） |
| 风险 / 是否确认 | 由 `risk` + `op` 推导；`write` 默认要确认 |

**启用规则：** catalog 可见 ∧ Agent 启用 ∧（读免确认或写已确认）→ 才进入当次对话可用 Tool 集。

行程报销：用同一套导入替换原指向 office-api 的 list/detail 等 Tool；删除对旧 OpenAPI/office-api 路径的依赖。

---

## 6. 运行时 invoke

```text
Agent Executor
  → POST open-oa /agent/invoke
     Authorization: 员工 token
     Idempotency-Key:（仅 write）
     body: { service, method, args }  // args 已去掉身份字段
  → 校验：token、方法在白名单、风险策略
  → ANew(service)->method(...)
  → { code, msg, data } 信封
  → Agent 按 result_fields 裁剪 → 回图
```

响应信封与现网 Agent 解析约定对齐（成功码可配）；具体 profile 名在实现时改为面向 open-oa 的命名，避免再出现 office-api 字眼作为本上游的主称呼。

---

## 7. 写操作与确认

| op / risk | 对话行为 |
|-----------|----------|
| read + low | 直接 invoke |
| write + low/medium | 展示将执行内容 → 员工确认 → invoke |
| high | 默认关闭或强制确认 + 审计；可挂固定 Workflow |

- 确认前：**不调用** invoke。
- 确认后：服务端携带 Idempotency-Key；Service 重校验；不信任模型权限结论。
- 与现有写路径纪律（O2）一致，执行出口改为 open-oa invoke。

---

## 8. 错误处理

| 场景 | 上游 | 员工侧 |
|------|------|--------|
| token 无效 | 401 | 提示从 OA 重新进入 |
| 方法未标注 / 不在白名单 | 业务码（如 METHOD_NOT_ALLOWED） | 「该功能未开放」 |
| 无业务权限 / 非本人数据 | 业务码 + 可展示 msg | **原样展示** msg |
| 参数不合法 | 业务码 + msg | 追问或改参 |
| 写缺幂等键 / 幂等命中 | 明确错误码或同一成功结果 | 重试提示或静默成功 |
| open-oa 超时 / 5xx | 传输失败 | 沿用上游故障策略（提示 / 转人工） |

禁止向 Agent 回传 PHP 栈、SQL、密钥。

---

## 9. 白名单与权限归属

| 层 | 职责 |
|----|------|
| Service 契约 | 「技术上可暴露」；未标注 = 不存在 |
| open-oa | 运行时只调已标注方法；校验员工 token；写校验幂等 |
| Agent 后台 | 员工启用、Skill、文案/参数微调、确认策略 |
| 业务权限 | 仅 Service / Export 按员工身份判定 |

误开启用时：仍须过 Service 鉴权。未标注则无法导入且 invoke 失败。

---

## 10. 强拆与迁移

### 10.1 本期必须完成

1. open-oa：`mint`、`export-catalog`、`invoke` + 鉴权。
2. Service：行程相关及本期纳入的 Export 补契约；ANew 可调通。
3. Agent：上游改为 open-oa；catalog 导入 Tool/Skill；读/写确认跑通。
4. **强拆：** 配置与代码去除本链路对 office-api 的依赖；下线 office-api 上对应 Agent 路由（含原行程 Agent 调用面）；文档与用户可见文案改为 open-oa。
5. 回归：OA 宿主进对话、企微 mint、行程查询、写确认、故障提示、审计（service/method/员工/成败，无 token 明文）。

### 10.2 行程报销

```text
旧：Agent Tool → office-api → Service
新：Agent Tool → open-oa /agent/invoke → ANew(...) → 同一 Service 逻辑
```

旧 office-api 行程 Agent 路由本期下线，不保留双轨。

### 10.3 预留方案 3

catalog schema 预留 `extensions.mcp`（或等价字段）。本期不实现 MCP Server，不要求 Agent 出站 MCP 同步这些 Tool。

---

## 11. 验收清单

- [ ] 员工只能调用 Agent 已启用方法；未启用 / 未标注均不可用
- [ ] 篡改 args 中他人身份无效
- [ ] 行程只读经 invoke 与同账号旧行为数据一致
- [ ] 写：未确认不调用；确认后幂等不重复落单
- [ ] mint 仅在 open-oa；切断 office-api 后仍可换票并查行程
- [ ] 审计含 invoke 的 service/method/员工/成败，无 token 明文
- [ ] 代码/配置/面向用户的文档本链路不再以 office-api 为主称呼

---

## 12. 与既有文档关系

| 文档 | 关系 |
|------|------|
| `docs/design/2026-10-09-oa-langgraph-design.md` | 身份、Tool 纪律、确认写路径继续有效；**业务上游主称呼与落地由 office-api 改为 open-oa**（以本文 D7–D10 为准） |
| `docs/design/2026-10-09-oa-service-side-design.md` | mint / 企微签发语义保留；**HTTP 入口改为 open-oa** |
| `docs/ops/integrate-external-system.md` / `user-guide.md` | 实现后需同步改为 open-oa 表述与迁移说明 |

---

## 13. 建议实现切片（供 writing-plans）

1. open-oa：mint 平替 + 契约注册表骨架 + catalog + invoke（只读先通）
2. Service：行程 list/detail 契约与 ANew 通路
3. Agent：上游/文案迁 open-oa；catalog 导入；行程 Tool 切换；删 office-api 依赖
4. 写路径：确认 + Idempotency-Key + 一两个写方法样例
5. 强拆下线与全量回归；文档回写 STATUS
