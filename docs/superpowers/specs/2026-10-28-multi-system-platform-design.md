# 多系统可插拔 Agent 平台架构（效果优先）

**日期：** 2026-10-28  
**状态：** 已确认（2026-10-28，按推荐锁定）  
**决策：** 身份模型 **C**（平台统一会话；下游鉴权由 Connector 换票）；演进路径 **渐进剥离到清晰四层**（效果优先，不因成本压缩抽象）  
**权威设计关系：** 本规格定义**目标平台架构**；现网 OA/office-api/行程报销降级为 **第一个 Domain Pack + 默认 Connector 实现**。冲突时：硬安全约束仍服从 [`docs/design/2026-10-09-oa-langgraph-design.md`](../../design/2026-10-09-oa-langgraph-design.md)；命名与模块边界以本规格为准并回写权威设计。

### 评审锁定补充（2026-10-28）

| 项 | 锁定 |
|----|------|
| 四层 + D1–D6 | 同意 |
| M0–M5 顺序 | 同意 |
| `oa` 过渡双写 | 同意（新字段 `principal_id` + 兼容读 `oa`） |
| M4 OIDC | **仅骨架**，不上真联调 |
| Pack 分发 | **本机目录 + 后台启用**；不上传 zip（M5 后再议） |

---

## 1. 问题与目标

### 1.1 现状耦合（诊断）

| 耦合面 | 表现 | 后果 |
|--------|------|------|
| 身份 | 会话字段 `oa`、assertion `iss: oa-host`、mint 绑 office-api | 换一个系统就要改核心 |
| 上游 | `OfficeApiClient` + `{code,msg,data}` 信封写死 | ERP/CRM/自建 API 难复用 |
| 业务 | `RULE_TOOLS`、写 Workflow、openapi 种子绑行程报销 | 「平台」实为「报销助手」 |
| 命名 | 包名/产品文案大量 OA | 对外无法宣称通用平台 |
| 信任域 | 「同一员工 token 多 upstream」假设 | 多系统各发 token 时模型崩 |

### 1.2 目标（成功标准）

1. **平台核能在无 OA 依赖下启动**：可只配「演示 Connector + 演示 Domain Pack」跑通对话选 Tool。  
2. **接入新外部操作系统** = 新增/配置：**Identity Provider（可选）+ Connector + Domain Pack**，不改 `runtime/graphs` 核心与路由内核。  
3. **现网 OA 行程报销** = 一等公民插件，行为不回退；迁移期双读兼容。  
4. 硬约束保留：模型不参与权限；业务授权在下游；密钥只写不读；管理/员工两套主体；不伪造指标。

### 1.3 非目标（本期规格不展开）

- 拖拽可视化编排 IDE  
- Agent 直连任意业务库  
- 标准 MCP 入站作为主入口  
- 多租户计费/SaaS 商业化（`tenant_id` 仍保留隔离钩子）

---

## 2. 目标分层

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Platform Core                         │
│  Chat · Channels · Threads · Memory · Run/State · Routing       │
│  Skill/Tool Catalog · Workflow Engine · Admin · Observability   │
│  Principal（平台主体）· Session（平台会话）                        │
└───────────────┬─────────────────────────────┬───────────────────┘
                │                             │
     ┌──────────▼──────────┐       ┌──────────▼──────────┐
     │  Identity Broker    │       │  Connector Hub      │
     │  IdP 适配器插件      │       │  Connector 插件     │
     │  断言校验 · 换会话   │       │  换票 · 调用 · 解析 │
     └──────────┬──────────┘       └──────────┬──────────┘
                │                             │
                └──────────┬──────────────────┘
                           ▼
              ┌────────────────────────────┐
              │  Domain Pack（可插拔）       │
              │  Skills · Tools · Rules    │
              │  Write Workflows · Prompts │
              └────────────────────────────┘
                           │
                    外部操作系统 API
```

**一句话：** Core 不懂 OA；Connector 不懂「报销」；Domain Pack 不懂「怎么签名 HTTP」。

---

## 3. 身份模型 C（平台会话 + Connector 换票）

### 3.1 概念

| 概念 | 含义 | 今日映射 |
|------|------|----------|
| **Principal** | 平台认定的对话主体 | 近似 `oa`，但中性命名 |
| `principal_id` | 租户内稳定 ID（ULID 或外部稳定键的哈希/映射） | 现网可用 `oa` 字符串作 `external_key` |
| **Session** | 平台 ticket；只证明 Principal，**不**等于下游 token | Chat ticket |
| **Credential handle** | 会话内对「某 connector 可用凭证」的引用（存 KV，不下发浏览器） | `office_token` |
| **IdP（Identity Provider）** | 证明人是谁：OA assertion / 企微 / OIDC / … | `chat_launch` + wecom mint |
| **Connector** | 对某一外部系统说话：换票 + 调 API | `OfficeApiClient` |

### 3.2 登录时序（统一）

```text
渠道入站（iframe / 企微 / 将来 OIDC）
  → IdP Adapter.verify(assertion|code) → PrincipalClaims
  → Identity Broker.create_session(principal, channel)
  → 按 Domain/菜单需要的 connector：Connector.ensure_credential(session)
       （OA Pack：调用 mint；OIDC Pack：用 refresh；静态：服务账号）
  → 返回平台 ticket（浏览器只持有平台会话）
```

规则：

1. 模型与客户端**永远不能**提交 `principal_id` / 下游账号冒充；只认 Session。  
2. Tool 执行时：`Identity` 由 Session + Connector 解析，**注入映射表**由 Tool/Connector 配置，不写死字段名 `oa`。  
3. 一个 Session 可绑定 **多个** connector 凭证（多系统并行）；调用时按 Tool 的 `connector_id` 取对应凭证。  
4. 管理员会话与员工会话仍隔离；管理员不能代 Principal 确认业务写操作。

### 3.3 兼容迁移

- DB/事件中过渡期保留列名 `oa` 作 `principal.external_key` 别名，或新增 `principal_id` 双写。  
- API 对外逐步用 `principal_id`；旧字段只读兼容一个大版本。

---

## 4. Connector Hub（对接任意外部系统的关键）

### 4.1 Connector 插件接口（逻辑契约）

每个 Connector 实现：

| 方法 | 职责 |
|------|------|
| `id` / `kind` | 如 `http_json`、`mcp`、`soap`（后置） |
| `ensure_credential(session, secrets) -> Credential` | 换票/刷新；失败给员工可读原因 |
| `invoke(spec, args, credential, correlation_id) -> ConnectorResult` | 真正调用 |
| `parse_envelope(raw) -> (ok, data, user_message, error_code)` | **可插拔信封**，禁止全局写死一种 `{code,msg,data}` |
| `health_check()` | 给 readyz / 配置「测试连接」 |

### 4.2 HTTP JSON Connector（内置第一种）

配置（管理后台，非代码）：

- `base_url`、超时、TLS  
- `auth`：`bearer_from_credential` | `header_template` | `query`（谨慎）  
- `envelope_profile`：`oa_office`（现网）| `raw_json` | `json_api` | 自定义 JMESPath/成功码列表  
- `success_codes`、`message_paths`、`data_path`  
- **信任域**：该 connector 允许的凭证来源（只能用本 IdP 换出的票，或显式服务账号）

Tool 只存：`connector_id` + `method` + `path`（相对）+ schema；**禁止**完整 URL。

### 4.3 MCP Connector

沿用现有出站 MCP Client，升级为 Connector `kind=mcp`：同一套注册表、事件、可见性；不再特殊成「第二套执行器旁路」。

### 4.4 Builtin Connector

`kind=builtin`：时间/计算/导出等，无外部 OS；沙箱策略仍按现网高风险默认关。

### 4.5 多系统同时在线

- Session 持有 `credentials: { connector_id: handle }`  
- Domain Pack 声明依赖哪些 `connector_id`  
- 路由/Skill 可见性可按「凭证是否可用」裁剪（凭证失败 ≠ 权限放开）

---

## 5. Domain Pack（业务可插拔）

### 5.1 包内容

一个 Domain Pack = 目录或后台导入包：

```text
packs/oa_travel/
  pack.yaml          # id, display_name, connectors[], idp_optional
  skills/*.yaml
  tools/*.yaml       # 或 openapi + x-agent
  contracts/write_*.yaml
  workflows/         # 固定写图注册元数据（代码图仍可在 pack 插件入口注册）
  rules/intent.yaml  # 可选：确定性意图
  prompts/*.md       # 可选 persona 片段
```

### 5.2 包生命周期

1. **安装**：校验 connectors 已配置；导入 Skill/Tool 版本；注册 Workflow 到 `workflow_catalog`  
2. **启用/停用**：影响可见性与路由候选，不删历史 run  
3. **卸载**：需无运行中依赖；保留审计  

### 5.3 平台核心禁止出现的内容

- 硬编码 Tool 名 `query_my_travel_expense_*`（应在 pack 的 rules 里）  
- 写死 mint 路径 `/agent/token/mint`（应在 OA HTTP Connector / IdP 适配器配置）  
- 默认 persona「你是 OA 助手」作为唯一内置（改为平台中性默认 + pack 覆盖）

### 5.4 第一个 Pack：`oa_travel`（现网下沉）

把现有行程只读 Tool、写契约、`intent_rules` 行程部分、`travel_reimburse_submit` 图、OA assertion + office mint **全部标为该 Pack 的实现**，平台只保留钩子。

---

## 6. Platform Core 改造点

### 6.1 会话与 Run

- `ChatSession`：`principal_id`, `display_name`, `channel`, `tenant_id`, `credential_refs`, （兼容）`external_keys.oa`  
- `Run`：绑定 `principal_id`、`domain_pack_ids[]` 或主 `pack_id`、`workflow_id`、`routing_mode`  
- Identity 传给执行器：`PrincipalContext` + `ConnectorCredential`，取代仅 `(oa, authorization)`

### 6.2 Tool / Skill / 路由

- ToolSpec：`connector_id` 取代「默认 office upstream」语义；`upstream` 兼容别名  
- `inject_identity_fields` → `identity_bindings: [{param, from: "principal.external_key|credential.claim"}]`  
- 路由六模式保留；规则引擎读 **已启用 Pack 的 rules**，不读全局硬编码  
- 多 Agent Domain ≈ Pack 或 Pack 内 profile；与 Connector 解耦

### 6.3 渠道

- Channel 只负责：收消息、调 IdP、调 `handle_message`  
- OA iframe / 企微 = **渠道适配器**，不是业务内核

### 6.4 配置中心分组重命名（效果优先可一次改文案）

| 现分组 | 目标 |
|--------|------|
| OA 对接 | **连接器 / IdP**（列表） |
| office 主地址 | 某条 HTTP Connector 的实例 |

---

## 7. 安全与信任（多系统后更重要）

1. **模型不参与权限** — 不变。  
2. **凭证不出浏览器、不进模型提示、不进审计明文** — 不变。  
3. **Connector 信任域**：禁止把 A 系统员工票发到未声明信任的 B 系统。跨系统须显式「二次换票」或「用户确认绑定」。  
4. **写操作**：仍仅固定 Workflow + 员工确认；Pack 声明 `risk`；平台执行门禁。  
5. **越权探针**：按 Connector 注册「探针套件」（OA Pack 提供「改 external_key 必须失败」）。  
6. **可见性 ≠ 授权** — 不变；TagProvider 可来自任意 Connector 的画像 API。

---

## 8. 仓库与模块目标结构

```text
backend/oa_agent/
  platform/           # 可选：会话、run、chat 门面（或保留 chat/ 渐进搬）
  identity/           # Broker + IdP adapters（oa_assertion, wecom, oidc…）
  connectors/         # Hub + http_json, mcp, builtin
  packs/              # 加载器；oa_travel 作为内置 pack
  executor/           # 目录、路由、执行（对 connector 调度）
  runtime/            # 图引擎；通用 assistant 图；pack 注册写图
  admin/              # connectors、packs、routing、…
integrations/office_api.py  → 迁入 connectors/http_profiles/oa_office.py（兼容 shim）
```

前端：连接配置改为「连接器实例」；新增「领域包」管理页；调用过程页展示 `connector_id` / `pack_id`。

---

## 9. 实施阶段（效果优先排序，非成本压缩）

| 阶段 | 内容 | 验收 |
|------|------|------|
| **M0 规格冻结** | 本文确认；权威设计增补「平台 vs Pack」 | 评审勾选 |
| **M1 抽象不改行为** | `Principal`/`Connector` 接口；`OfficeApiClient` 实现 `HttpJsonConnector`；Session 双字段；事件多打 `connector_id` | 全量 pytest 绿；现网行程对话行为一致 |
| **M2 信封/身份可配** | envelope_profile；identity_bindings；多 connector 凭证表 | 用 raw_json 接一个 mock 非 OA API 跑通只读 Tool |
| **M3 Pack 加载器** | `oa_travel` 下沉；规则/写图从 pack 注册 | 禁用 pack 后行程能力消失；启用恢复 |
| **M4 IdP 插件化** | OA assertion / 企微分适配器；OIDC 适配器可先骨架 | 无 OA 时用 demo IdP + demo pack 可聊 |
| **M5 产品化** | 管理端连接器/包管理；文档与演示 Pack；命名去 OA 中心化 | 新系统接入手册 &lt; 1 天（有 API） |

**演示 Pack（效果展示用）：** `packs/demo_http` + 本地 mock server，证明「零 OA」可运行。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 大重构破坏现网 | M1 必须行为黄金集（行程 list/detail/写 flag 关） |
| 抽象泄漏（Core 又出现 oa） | CI grep 禁令：`runtime/` `executor/tool_routing` 核心禁 `office-api`/`travel_expense` 字符串（测试与 pack 目录除外） |
| 多票会话复杂度 | 先支持「每 Session 多 connector 凭证」，UI 后期再做「连接状态」 |
| 包版本与 Tool 版本双轨 | Pack 版本钉死所含 Skill/Tool content_hash；发布仍走现有版本机制 |

---

## 11. 决断记录

| ID | 决断 |
|----|------|
| D1 | 身份模型 **C** |
| D2 | 四层：Core / Identity Broker / Connector Hub / Domain Pack |
| D3 | 效果优先：允许一次改名与模块搬迁；用 shim 保兼容 |
| D4 | OA 行程 = 内置 Pack，不是平台内核 |
| D5 | 多系统 = 多 Connector 凭证，禁止默认同票跨信任域 |
| D6 | 路由/观测已有能力保留，扩展维度 `pack_id`/`connector_id` |

---

## 12. 评审清单

- [x] 同意四层划分与 D1–D6  
- [x] 同意 M0–M5 阶段顺序（尤其 M2 用非 OA mock 验收「可独立存在」）  
- [x] 同意过渡期 `oa` 字段双写兼容  
- [x] M4 OIDC **仅骨架**  
- [x] Pack：**本机目录 + 后台启用**（暂不上传 zip）

- M1：[`multi-system-m1-connectors`](../plans/2026-10-28-multi-system-m1-connectors.md) · [`multi-system-m1-delivery`](../../delivery/2026-10-28-multi-system-m1-delivery.md)  
- M2：[`multi-system-m2-envelope`](../plans/2026-10-28-multi-system-m2-envelope.md) · [`multi-system-m2-delivery`](../../delivery/2026-10-28-multi-system-m2-delivery.md)  
- M3：[`multi-system-m3-packs`](../plans/2026-10-28-multi-system-m3-packs.md) · [`multi-system-m3-delivery`](../../delivery/2026-10-28-multi-system-m3-delivery.md)  
- M4：[`multi-system-m4-idp`](../plans/2026-10-29-multi-system-m4-idp.md) · [`multi-system-m4-delivery`](../../delivery/2026-10-29-multi-system-m4-delivery.md)（OIDC 仅骨架）  
- **下一步 M5：** 管理端连接器/包产品化、命名去 OA 中心化、演示 Pack（见 §9）
