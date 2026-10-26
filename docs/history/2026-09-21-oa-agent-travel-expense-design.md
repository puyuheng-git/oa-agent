# OA Agent 一期设计：行程报销只读查询

**日期：** 2026-09-21  
**状态：** 已认可；实现计划见 `docs/superpowers/plans/2026-09-22-oa-agent-travel-expense.md`  
**更新：** 2026-10-09 起 Agent 改为独立系统（LangGraph，仓库 `E:\python_project\oa-langGraph`），OA/Service 侧配套见 `2026-10-09-oa-agent-langgraph-ops-design.md`（本文身份/Tool 契约继续有效）  
**范围：** 大 · 双端入口 · Agent 独立部署  
**参考：** `cursor_oa_agent_mcp_prompt.md`（目标架构；本设计为其减肥落地版）

---

## 1. 背景与目标

用户通过**企业微信智能机器人**或 **OA 助手页**用自然语言查询本人行程报销单；Agent 部署在**独立新服务器**，不嵌入 OA 进程，不直连 OA 数据库，只经受控 API 访问业务数据。

**一期成功标准：**

> 员工在企微或 OA 说「查上周行程报销」→ 返回其本人行程报销列表/详情；伪造他人 `oa` 无效；未绑定企微账号有明确提示。

非目标（一期不做）：发票查询、金额试算、报销草稿、正式提交、管理者合并权限、`ai-api` 演示链路、Hermes 钉死为唯一运行时、OpenAPI 全自动 CI 同步。

---

## 2. 已锁定决策

| 项 | 结论 |
|----|------|
| 业务 | 只读「行程报销单」（`out_attendance_travel_expense`） |
| 权限（一期实际） | 本人（office-api 强制 `oa`）；OA 合并权限（管理员/部门）→ **二期** |
| 后端 | 复用 **office-api** `out_attendance/go_out_travel_expense` |
| 入口 | 企微机器人 + OA 助手页（同一 Agent） |
| 运行时 | **后定**；先定协议与契约；Orchestrator 可插拔（Hermes 为候选实现） |
| 身份 | 企微验签+绑定表；OA Session→assertion→Agent ticket→员工 office token |
| 架构风格 | 契约 + 最小 Agent 网关（相对纯文档或直接钉 Hermes） |
| office token 代换 | **方案 A**：Service 内网 `agentMintOfficeToken`（见 §7.4） |
| 排除 | `general/ai_api` 演示项目 |

与提示词文档的关系：采纳分层、MCP 通用执行、Skill 按场景、服务端鉴权、高风险确认等原则；**收窄**其「第一阶段」全流程报销；**禁止** invent `travel_records` 等平行表；OpenAPI 自动 MCP 先做最小加载器，discovery/CI 后置。

---

## 3. 系统边界

```text
[企微智能机器人] --验签/解密--> [Agent 网关 :新服务器]
[OA 助手页]     --Session--> [OA 薄桥] --assertion--> [Agent 网关]
                                      |
                                      | 对话编排（LLM 可插拔；一期可用规则桩）
                                      v
                              MCP Tool: list / detail
                                      |
                                      v
                         office-api (Authorization=该员工)
                         out_attendance/go_out_travel_expense/index|detail
```

硬规则：

1. 网关永不信任客户端自报的 OA 号作为最终身份。  
2. 调 office-api 的身份只来自：企微绑定解析，或 OA assertion 兑换结果。  
3. 一期工具仅行程报销 **列表 + 详情**（只读）。  
4. Agent/MCP 不直连业务库；不对公网暴露 `/_private/rpc`。

---

## 4. 身份与 ticket 契约

### 4.1 身份真相来源

| 入口 | 证明 | 解析主体 |
|------|------|----------|
| 企微 | 回调验签+解密，`FromUserName` → `wework_user_id` | 表 `user_to_wework_user` → OA 号 |
| OA | Session `LOGIN_USER_ID` / `LOGIN_UID` | 直接得 OA 号 |

### 4.2 多 OA 绑定（一期）

1. 仅 1 个 OA → 使用该账号  
2. 多个 → 取 `is_main_account=1` 对应 `oa`（与现网发消息一致）  
3. 无主账号 → 引导绑定，**不查数**  
4. 会话内切账号 → 二期  

### 4.3 凭证分层

| 层 | 凭证 | 签发 | 寿命（建议） | 用途 |
|----|------|------|--------------|------|
| L0 | 企微签名包 / OA Session | 企微 / OA | 入口侧 | 证明真人 |
| L1 | Agent ticket | 网关 | 15～30 分钟 | 对话与 Tool 鉴权 |
| L2 | office `Authorization` | Passport `TOKEN_BIZ_CODE_OFFICE` | ≤ ticket | 仅网关持有，调 office-api |

OA 薄桥：校验登录 → `POST /v1/auth/oa-exchange` 提交 HMAC assertion（`oa`,`uid`,`exp`,`nonce`,`iss`）→ 网关签发 ticket 并代换 office token（**token 不下发浏览器**）。

企微：回调内完成绑定解析 → 签发 ticket + 代换 office token。

### 4.4 安全底线

- ticket → Redis：`{oa, channel, office_token_ref}`；吊销即删  
- office token 禁止出现在企微消息、前端存储、Tool 模型参数  
- 网关调 API 时忽略任何自报 `oa`/`user_id`  
- assertion / 回调防重放（`nonce` + 短 `exp`）  

### 4.5 用户可见失败文案（示意）

| 情况 | 文案 |
|------|------|
| 企微未绑定 | 未绑定 OA 账号，请联系管理员 |
| 多账号无主账号 | 请先设置企微主账号后再查询 |
| OA 未登录 / assertion 过期 | 请重新打开 OA 助手页 |
| office token 失效 | 会话过期，请重试 |

---

## 5. 工具契约（MCP / OpenAPI）

### 5.1 注册 Tool（仅 2 个）

| operationId | HTTP | 风险 |
|-------------|------|------|
| `query_my_travel_expense_list` | `GET .../go_out_travel_expense/index` | low |
| `query_my_travel_expense_detail` | `GET .../go_out_travel_expense/detail` | low |

不注册：无分页 `list`、`store`、`delete`。

现网路由前缀：`out_attendance/go_out_travel_expense`（`site/office-api/route/app.php`）。  
底层 Service：`ANew('out_attendance/go_out_application')` → `getTravelExpensePageList` / `getTravelExpenseOneByParams`。

### 5.2 身份注入

- `oa`：**仅** MCP/网关从 Session 注入；模型 Schema **不含** `oa`  
- `Authorization`：网关持有，不进 Tool 入参  

**已知缺口：** 现网 `GoOutTravelExpense::detail()` 未像 `index` 那样强制写入 `queryParams['oa']`。一期 MCP 调 detail **必须**附带与 token 一致的 `oa`；二期应在 office-api `detail` 补强制过滤。

### 5.3 模型可见入参

**list：** `date_gte`, `date_lte`（`YYYY-MM-DD`）, `status`（0 未报销 / 1 已报销）, `fiscal_year`, `source`（1 外出 / 2 191请款）, `page`（默认 1）, `limit`（默认 10，**MCP 上限 20**）。

**detail：** `id`（必填）。

自然语言时间（上周/上月）由编排层解析为日期区间后再调 Tool。

### 5.4 HTTP 映射

office-api 使用 GET + `queryParams` JSON 字符串：

```http
GET /out_attendance/go_out_travel_expense/index?page=1&limit=10&queryParams={...含注入oa...}
Authorization: <office token>
```

```http
GET /out_attendance/go_out_travel_expense/detail?queryParams={"id":12345,"oa":"<injected>"}
Authorization: <office token>
```

### 5.5 返回精简视图

列表项：`id`, `date`, `client_name`, `total_amount`, `status`, `status_text`, `source`, `source_text`, `transport_types_desc`, `remark`（截断 100 字）。

详情另加：`travel_route`, `is_meal_allowance`, `run_id`, `out_attendance_application_id`, `fiscal_year`。

统一包装：

```json
{
  "ok": true,
  "capability": "query_my_travel_expense_list",
  "data": { "list": [], "total": 0, "page": 1, "limit": 10 },
  "message": ""
}
```

### 5.6 OpenAPI `x-agent`（示意）

```yaml
x-agent:
  enabled: true
  domain: travel_reimbursement
  capability: query_my_travel_expense_list
  risk_level: low
  requires_confirmation: false
  audit_required: true
  idempotent: true
  visibility: user
  timeout_seconds: 10
  inject_identity_fields: [oa]
```

写接口即使进入 OpenAPI 也必须 `enabled: false` 或 high + 确认流（一期不暴露）。

### 5.7 Tool 审计字段

`ticket_id`, `oa`, `capability`, 入参摘要, `http_status`, 耗时, `result_count`/`id`, 是否截断。不记 Authorization 与超大原始响应。

### 5.8 与提示词能力名映射

| 提示词 | 一期 |
|--------|------|
| `query_my_travel_records` | → list / detail |
| `query_travel_invoices` 等 | 不做 |

---

## 6. 双入口消息协议与网关 API

### 6.1 对外 API

| 方法 | 路径 | 调用方 |
|------|------|--------|
| `POST` | `/v1/auth/oa-exchange` | OA 薄桥 |
| `POST` | `/v1/wecom/callback` | 企微 |
| `POST` | `/v1/chat` | OA 助手页（Bearer ticket） |
| `GET` | `/v1/session` | OA 助手页 |
| `POST` | `/v1/session/refresh` | OA / 内部 |
| `GET` | `/healthz` | 探活 |
| `POST` | `/internal/mcp/invoke` | 仅 Orchestrator |

### 6.2 OA 聊天

- Exchange 成功返回：`ticket`, `expires_in`, `display_name`（无 office token）  
- `POST /v1/chat`：`message` + `client_msg_id`（去重）  
- 响应内部结构：`reply_type`（`markdown`|`text`|`error`）, `content`, `meta.tool_calls`  

### 6.3 企微

- 入站：验签解密 → `wework_user_id` + 文本 + `msg_id` 去重  
- 出站：统一先产内部 `reply`，再 `WeComReplyAdapter` → `markdown` /（可选）`template_card`  
- 耗时：优先被动回复；超过约 4s 则短应答 + **主动回复**补全  

### 6.4 会话模型

`Session { ticket_id, oa, channel: oa_web|wecom, wework_user_id?, office_token_ref, created_at, expire_at }`

### 6.5 网关错误码

`UNAUTHENTICATED` | `WECOM_NOT_BOUND` | `WECOM_NO_MAIN` | `RATE_LIMITED` | `UPSTREAM_ERROR` | `EMPTY_RESULT`  

限流建议：按 `oa` 约 30 次/分钟；`client_msg_id` / 企微 `msg_id` 去重窗口 ≥ 5 分钟。

---

## 7. 部署与信任边界

### 7.1 组件放置

| 组件 | 位置 |
|------|------|
| Agent 网关 + MCP + 编排槽位 | 新服务器（一期可同机） |
| OA 薄桥 | 现有 OA Web |
| office-api | 现有 Service 机房 |
| MySQL | 仅 PHP/Service |

### 7.2 网络

- 公网主要暴露：网关企微回调 `:443`  
- OA 页经同源反代持 ticket 调 `/v1/chat` 为佳  
- 网关出站：office-api、企微 API、（可选）LLM  
- 禁止：公网 office-api / `_private/rpc` / DB；浏览器持 office token  

### 7.3 密钥（环境变量）

`OA_ASSERTION_HMAC_SECRET`、企微 Token/AESKey/Secret、`OFFICE_API_BASE_URL`、token 铸造密钥、LLM Key（若启用）。

### 7.4 office token 代换（方案 A）

新增 **仅内网** Service 能力（名称实现时确定，语义固定）：校验网关密钥后为指定 `oa` 签发 `TOKEN_BIZ_CODE_OFFICE`，全量审计。Token 只存网关 Redis，TTL ≤ ticket。

不采用：网关裸复用 Passport 密钥无审计（B）；旁路 office-api 自建带 `oa` 参数的专用 API 作为一期主路径（C）。

### 7.5 超时

| 链路 | 超时 |
|------|------|
| OA exchange | 3s |
| office-api | 8～10s |
| `/v1/chat` 同步 | ≤ 15s |
| 企微被动 | ~4s 后转主动 |

### 7.6 信任边界一句话

公网只信验签后的企微用户与 HMAC 后的 OA assertion；业务数据只信 office-api 以该员工 token 返回的结果；模型与 Skill 不在信任边界内。

---

## 8. 路线图（本设计之外）

| 阶段 | 内容 |
|------|------|
| MVP-1（本设计） | 双入口 + 身份 + 只读 list/detail |
| MVP-2 | 发票关联、金额试算（先确认现网 API，禁止 invent） |
| MVP-3 | 草稿 + 确认 + 提交；Workflow 状态机；高风险确认 |
| 权限二期 | 下沉 OA `getMergePermissionParams` 到 Domain API；office-api detail 强制 `oa` |
| 平台二期 | OpenAPI refresh/CI、多账号会话切换、编排换 Hermes 等 |

---

## 9. 测试要点（验收）

- 正常：有数据 / 无数据列表  
- 日期区间、status 过滤  
- detail 本人 id 成功；**仅他人 id 且未注入正确 oa 时不得返回数据**（依赖 MCP 注入；二期 API 加固）  
- 企微未绑定 / 无主账号  
- OA assertion 过期、伪造 HMAC  
- ticket 过期、限流、office-api 超时  
- `client_msg_id` / `msg_id` 去重  
- 模型传入 `oa` 被忽略且不能越权  

---

## 10. 实现时涉及的现网锚点

| 锚点 | 路径 |
|------|------|
| office-api 控制器 | `site/office-api/app/controller/out_attendance/GoOutTravelExpense.php` |
| 路由 | `site/office-api/route/app.php` |
| Service Export | `service/.../out_attendance/go_out_application/Export.php` |
| 表 | `out_attendance_travel_expense`（`td_oa`） |
| 状态常量 | `framework/com-lib/src/constant/out_attendance/OutAttendanceTravelExpenseConst.php` |
| 企微绑定 | `user_to_wework_user`；OA `UserToWeworkUserService` / Service `wework/common` |
| office 登录校验 | `oa/user` + `LoginConst::TOKEN_BIZ_CODE_OFFICE` |
| 目标架构提示词 | `puyueheng/cursor_oa_agent_mcp_prompt.md` |

---

## 11. 规格自检记录

- 无 TBD 阻塞一期范围；token 代换已选定 A  
- 权限「合并」与「office-api 本人」已用一期/二期拆开，不矛盾  
- 范围可单独立项写实现计划（网关 + 薄桥 + mint token + OpenAPI 小文件 + MCP）  
- `detail` 越权缺口已写明缓解与二期修复  
