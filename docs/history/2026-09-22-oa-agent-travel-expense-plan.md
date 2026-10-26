# OA Agent MVP-1（行程报销只读）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 员工在企微或 OA 用自然语言查询本人行程报销列表/详情；Agent 独立部署，经身份契约调 office-api，禁止伪造他人 `oa`。

**Architecture:** Service 补齐 office token 铸造与 Auth 兼容；新服务器 Python Agent 网关（会话 + 规则编排 + 通用 MCP HTTP 执行器）；OA 薄桥做 assertion；企微回调验签后解析绑定。LLM/Hermes 一期用规则桩，接口预留。

**Tech Stack:** Service PHP 7.2 ThinkPHP6 UTF-8；OA PHP 5.2 GBK；Agent 网关 Python 3.10+ FastAPI + Redis + httpx；office-api 现网行程接口。

**Spec:** `docs/superpowers/specs/2026-09-21-oa-agent-travel-expense-design.md`

## Global Constraints

- Service 只写 `D:\MYOA\webroot\puyueheng\...`，禁止 `D:\39.102.37.69\puyueheng\...`
- 改 PHP 前读 `service-php73-architect` + `oa-php52-legacy`；改后跑 `stack-code-review`
- OA 新 PHP：GBK、`array()`、无闭包/短数组/`??`、文件头完整
- 写接口须 `DuplicateSubmit::assert`；本计划 mint 为受控内网写（签发 token），须 assert + 审计日志
- Agent/MCP **禁止**直连 MySQL；禁止公网暴露 `/_private/rpc`
- 模型可见 Tool Schema **不含** `oa`；`oa` 仅网关注入
- 一期不做：发票、草稿、提交、合并权限、ai-api、Hermes 钉死
- **不要自动 git commit**，除非用户明确要求
- 现网事实（实现必须处理）：
  1. `LoginConst::TOKEN_BIZ_CODE_OFFICE` **当前未定义**，但 `oa/user::checkLogin` 已引用
  2. office-api `AuthUser`：路径不在 `user.login_white_urls` 时用 **GET/POST `user_id`**，行程接口走该分支；须改为「有 Authorization 则走 token」，且兼容旧 `user_id` 客户端
  3. `GoOutTravelExpense::detail` **未强制** `queryParams.oa`；MCP 必须注入，且本计划补强制

## File map

| 文件 | 职责 |
|------|------|
| Modify: `framework/com-lib/src/constant/user/LoginConst.php` | 定义 `TOKEN_BIZ_CODE_OFFICE` 与过期 |
| Modify: `service/.../oa/user/Export.php` + 新增 logic | `checkLogin` 修正；`agentMintOfficeToken` |
| Create: `service/.../oa/user/Error.php` 或复用既有 Error | mint 错误码 |
| Create: `site/office-api/app/controller/agent/Token.php` + route | 内网 mint HTTP |
| Modify: `site/office-api/app/middleware/AuthUser.php` | Authorization 优先 |
| Modify: `site/office-api/app/controller/out_attendance/GoOutTravelExpense.php` | detail 强制 oa |
| Create: `agent-gateway/`（新目录，部署到新服务器） | FastAPI 网关+MCP+编排 |
| Create: `agent-gateway/openapi/travel_expense.yaml` | 两只读 operation + x-agent |
| Create: `D:\MYOA\webroot\general\ds\agent\bridge\ticket.php` | OA 薄桥 |
| Create: `D:\MYOA\webroot\general\ds\agent\views\assistant.php` | OA 助手最小页 |

---

### Task 1: LoginConst + 修正 `oa/user::checkLogin` + `agentMintOfficeToken`

**Files:**
- Modify: `D:\MYOA\webroot\puyueheng\framework\com-lib\src\constant\user\LoginConst.php`
- Modify: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\user\Export.php`
- Create: `D:\MYOA\webroot\puyueheng\service\service-app\src\service\oa\user\logic\AgentTokenImpl.php`
- Modify or create Error codes under `oa/user` / `lib\constant` 按现有模块习惯

**Interfaces:**
- Consumes: `Passport::genAuthorization`, `Passport::checkLogin`, `UserImpl::getUserInfo($uid, $fields)`
- Produces:
  - `LoginConst::TOKEN_BIZ_CODE_OFFICE = 'office'`
  - `Export::checkLogin(string $token, bool $refreshExpire, array $fields): array|false` — 返回 **DB 用户行**（含 `UID`,`USER_ID`,`NOT_LOGIN`,…）
  - `Export::agentMintOfficeToken(string $oa, string $gatewaySecret, string $operateUser = 'agent-gateway'): array{authorization:string,uid:int,oa:string,expire:int}`

**Steps:**

- [ ] **Step 1: 在 LoginConst 增加 OFFICE 常量**

```php
const TOKEN_BIZ_CODE_OFFICE = 'office';
const LOGIN_EXPIRE_OFFICE = 1800; // 与 Agent ticket 对齐量级，可按需调

// TOKEN_EXPIRE 数组增加：
self::TOKEN_BIZ_CODE_OFFICE => self::LOGIN_EXPIRE_OFFICE,
```

- [ ] **Step 2: 修正 checkLogin（按 UID 取用户并返回 DB 行）**

将 `Export::checkLogin` 中错误的 `getUserInfoByUserId($uid)` 改为 `UserImpl::getUserInfo($uid, $fields)`，空则 false；**成功返回 `$user`（DB 行）**，不要只返回 Passport 载荷。保证 AuthUser 能读 `$userInfo['USER_ID']` / `UID`。

- [ ] **Step 3: 实现 AgentTokenImpl::mint**

逻辑要点：

1. `hash_equals(env('AGENT_GATEWAY_SECRET'), $gatewaySecret)`，失败 `Exception::user`
2. `DuplicateSubmit::assert($operateUser, 'oa.user.agentMintOfficeToken', 3)`
3. 按 `USER_ID=$oa` 查用户；空或不存在 / `NOT_LOGIN` 则 clear + 抛错
4. 构造 Passport 载荷至少含：`id` => UID（Passport 缓存键用）、以及签发后 checkLogin 能还原用户
5. `$token = Passport::genAuthorization(LoginConst::TOKEN_BIZ_CODE_OFFICE, ['id' => (int)$uid, /* 可附带 oa */])`
6. 写审计日志（oa、uid、operateUser、时间）；return `authorization/uid/oa/expire`

- [ ] **Step 4: Export 暴露 `agentMintOfficeToken`**

委托 Impl；注释符合项目 Comments 规范。

- [ ] **Step 5: 本地用 think / 临时脚本或 PHPUnit 风格冒烟（若无测试框架则写 `site/tool` 只读校验脚本，不入库）**

验证：错误 secret 失败；正确 secret 返回 token；`checkLogin(token)` 得到 USER_ID=该 oa。

- [ ] **Step 6: 跑 stack-code-review 检查清单（本 Task 改动的 PHP）**

---

### Task 2: office-api 内网 mint 路由

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\site\office-api\app\controller\agent\Token.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\office-api\route\app.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\office-api\config\noneedverifylogin.php`（将 mint 列入免员工登录，改用网关密钥）
- Optional: IP 中间件或控制器内校验 `AGENT_MINT_ALLOW_IPS`

**Interfaces:**
- Consumes: `ANew('oa/user')->agentMintOfficeToken($oa, $secret)`
- Produces: `POST /agent/token/mint` body `{oa, gateway_secret}` → `{authorization, uid, oa, expire}`

**Steps:**

- [ ] **Step 1: 控制器**

```php
// POST only；从 post 取 oa、gateway_secret
// 调用 Export；suc 返回
```

- [ ] **Step 2: 路由 + 免登录白名单**

确保该 path 不走员工 `user_id` 分支；仅密钥鉴权。

- [ ] **Step 3: curl 冒烟（内网）**

```bash
curl -X POST "$OFFICE_API/agent/token/mint" -d "oa=某测试工号&gateway_secret=$SECRET"
```

Expected: code 成功且返回 authorization。

---

### Task 3: AuthUser「Authorization 优先」+ detail 强制 oa

**Files:**
- Modify: `D:\MYOA\webroot\puyueheng\site\office-api\app\middleware\AuthUser.php`
- Modify: `D:\MYOA\webroot\puyueheng\site\office-api\app\controller\out_attendance\GoOutTravelExpense.php`（`detail` 方法）

**Interfaces:**
- Produces: 请求带 `Authorization` 时一律 `checkLogin`；无头时保持原 `user_id` 行为
- Produces: `detail` 内 `$queryParams['oa'] = $this->request->oa`

**Steps:**

- [ ] **Step 1: 改 AuthUser 分支**

在已通过 `noneedverifylogin` 检查之后：

```php
$authorization = $request->header('Authorization');
if (!empty($authorization)) {
    $userInfo = $userService->checkLogin($authorization, true, $userFields);
} elseif (in_array($path, $loginWhiteUrls)) {
    // 保留旧：白名单强制 token（若仍需要）
    ...
} else {
    // 原 user_id 逻辑
}
```

补齐 hr_dept_id 逻辑与现网一致；空用户抛 `USER_NOT_LOGIN`。

- [ ] **Step 2: detail 强制 oa**

与 `index`/`list` 相同：`$queryParams['oa'] = $this->request->oa;`

- [ ] **Step 3: 验证**

1. 旧客户端仅 `user_id` 仍可访问 list（回归）  
2. 仅 Authorization（mint 出的 token）可访问 index/detail，且 detail 他人 id 返回空/失败  

---

### Task 4: OpenAPI 契约文件（两只读）

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\agent-gateway\openapi\travel_expense.yaml`

**Interfaces:**
- Produces: `operationId`: `query_my_travel_expense_list` / `query_my_travel_expense_detail`；含 `x-agent` 块（见 spec §5.6）

**Steps:**

- [ ] **Step 1: 编写 YAML**

- servers.url = `{OFFICE_API_BASE}`  
- paths:
  - `GET /out_attendance/go_out_travel_expense/index`
  - `GET /out_attendance/go_out_travel_expense/detail`  
- parameters：page/limit/queryParams（说明 oa 由适配器注入）  
- `x-agent.inject_identity_fields: [oa]`  
- store/delete **不要** enabled  

- [ ] **Step 2: 人工校对 operationId 与 spec 一致**

---

### Task 5: Agent 网关脚手架 + Session 存储

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\agent-gateway/`（pyproject/requirements、README、`.env.example`）
- Create: `agent-gateway/app/main.py`, `config.py`, `session_store.py`

**Interfaces:**
- Produces: FastAPI app；Redis Session：`ticket → {oa, channel, office_token, expire_at, wework_user_id?}`
- Produces: `GET /healthz` → `{"ok": true}`

**Steps:**

- [ ] **Step 1: 依赖** `fastapi uvicorn httpx redis pyyaml pydantic python-dotenv`

- [ ] **Step 2: SessionStore**

`create(oa, channel, office_token, ttl=1800) -> ticket`  
`get(ticket) -> session|None`  
`refresh` / `delete`

- [ ] **Step 3: 启动 healthz 本地验证**

```bash
cd agent-gateway && uvicorn app.main:app --port 8088
curl http://127.0.0.1:8088/healthz
```

Expected: `{"ok":true}`

---

### Task 6: `/v1/auth/oa-exchange` + mint 联调

**Files:**
- Create: `agent-gateway/app/auth/assertion.py`, `agent-gateway/app/auth/routes.py`
- Create: `agent-gateway/app/clients/office_mint.py`

**Interfaces:**
- Consumes: HMAC assertion；`POST {OFFICE_API}/agent/token/mint`
- Produces: `POST /v1/auth/oa-exchange` → `{ticket, expires_in, display_name}`

**Steps:**

- [ ] **Step 1: 校验 assertion**

payload JSON：`oa, uid, exp, nonce, iss=oa-bridge`；`hmac_sha256(secret, body)`；校验 exp/nonce 防重放（Redis SETNX nonce）。

- [ ] **Step 2: mint + 建 session**；office_token 只进 Redis

- [ ] **Step 3: 用测试 HMAC 调通；错误 secret / 过期 exp 分别返回 UNAUTHENTICATED**

---

### Task 7: MCP 通用执行器（list/detail）

**Files:**
- Create: `agent-gateway/app/mcp/openapi_loader.py`, `schema_builder.py`, `executor.py`, `policy.py`, `routes_internal.py`

**Interfaces:**
- Consumes: `travel_expense.yaml`；Session.office_token
- Produces: `invoke(capability, args, session) -> {ok, capability, data, message}`
- 强制：丢弃 args 中的 `oa`；注入 session.oa；limit max 20；裁剪返回字段（spec §5.5）

**Steps:**

- [ ] **Step 1: loader 读 YAML，只注册 `x-agent.enabled: true`**

- [ ] **Step 2: executor 用 httpx GET + Header Authorization + queryParams JSON**

- [ ] **Step 3: 单测/脚本**

对 mint 得到的真实用户：list 上周；detail 自己的 id；传入伪造 `oa` 确认被覆盖且不能看到他人数据。

---

### Task 8: 规则编排 + `/v1/chat`

**Files:**
- Create: `agent-gateway/app/orchestrator/rule_travel.py`, `app/chat/routes.py`
- Create: `agent-gateway/app/reply/types.py`

**Interfaces:**
- Consumes: ticket Bearer；用户 `message`；MCP invoke
- Produces: `{reply_type, content, meta}`

**Steps:**

- [ ] **Step 1: 意图规则（一期够用即可）**

- 匹配「行程|报销」+ 可选「上周|上月|未报销|已报销」→ 算 date_gte/lte、status → `query_my_travel_expense_list`  
- 匹配「详情|单号|#数字」→ `query_my_travel_expense_detail`  
- 否则 markdown 提示可问内容  

- [ ] **Step 2: `/v1/chat`**

校验 ticket；`client_msg_id` 去重；限流按 oa；调用编排；审计日志。

- [ ] **Step 3: 手工对话验收**「帮我查上周行程报销」

---

### Task 9: OA 薄桥 + 最小助手页

**Files:**
- Create: `D:\MYOA\webroot\general\ds\agent\bridge\ticket.php`（GBK）
- Create: `D:\MYOA\webroot\general\ds\agent\views\assistant.php`（GBK）

**Interfaces:**
- Consumes: OA Session；`OA_ASSERTION_HMAC_SECRET`；`AGENT_GATEWAY_URL`
- Produces: 浏览器获得 `ticket`；页内 fetch `/v1/chat`

**Steps:**

- [ ] **Step 1: ticket.php**

`include auth`；构造 assertion；curl POST 网关 `/v1/auth/oa-exchange`；`Api::suc` 返回 ticket。

- [ ] **Step 2: assistant.php**

简单输入框 + 调用 bridge 取 ticket + chat；展示 markdown（可用预格式化文本）。聊天写操作不适用；若日后有提交按钮再加 `runWithClickGuard`。

- [ ] **Step 3: 浏览器登录 OA 后打开助手页冒烟**

---

### Task 10: 企微回调入口

**Files:**
- Create: `agent-gateway/app/wecom/crypto.py`（或复用官方回调逻辑的 Python 移植）
- Create: `agent-gateway/app/wecom/routes.py`
- Create: `agent-gateway/app/clients/wework_bind.py`（调 Service/OA 已有绑定查询；推荐新增薄 Export 或复用 OA `UserToWeworkUserService` 经内网 HTTP）

**Interfaces:**
- Produces: `POST /v1/wecom/callback` URL 验证 + 消息；解析 `wework_user_id` → 主 oa → mint → session → 编排 → 被动 markdown JSON

**Steps:**

- [ ] **Step 1: 绑定解析**

0 条 → WECOM_NOT_BOUND；多条无主账号 → WECOM_NO_MAIN；否则主 oa。

- [ ] **Step 2: 同步被动回复**；超时策略可二期再上主动回复（一期文档允许先同步）

- [ ] **Step 3: 企微管理后台配回调 URL 到网关，用测试账号发「查行程报销」**

---

### Task 11: 端到端验收清单（对照 spec §9）

**Files:** 无代码；产出验收记录（可写在 PR 描述或 `agent-gateway/docs/smoke.md`）

**Steps:**

- [ ] **Step 1: 逐条执行**

| # | 场景 | 期望 |
|---|------|------|
| 1 | OA 助手查有数据区间 | 列表 markdown |
| 2 | 无数据区间 | 友好空结果 |
| 3 | detail 本人 id | 详情 |
| 4 | detail 他人 id（已登录 A） | 无数据/失败 |
| 5 | chat 传入伪装 oa | 无效 |
| 6 | 伪造 assertion | 401 |
| 7 | 企微未绑定 | 提示文案 |
| 8 | client_msg_id 重复 | 不重复查或幂等返回 |
| 9 | office-api 停掉 | UPSTREAM_ERROR 文案 |

- [ ] **Step 2: 更新 spec 状态为「已实现 MVP-1」或开 OpenSpec change 归档（若团队要求）**

---

## Spec coverage 自检

| Spec 章节 | Task |
|-----------|------|
| §3 系统边界 | 5–10 |
| §4 身份 ticket | 1–2, 6, 9–10 |
| §5 Tool 契约 | 4, 7；detail 强制 oa → 3 |
| §6 网关 API | 5–8, 10 |
| §7 部署 / mint A | 1–2, 5；README 写清 env |
| §9 测试 | 11 |
| 合并权限 / 发票 / 提交 | 明确不在本计划 |

## 执行建议拆分

若并行人力不足，可先合并交付 **Task 1–3 + 7 脚本验权**（无 UI），再上网关与双入口。

---

Plan complete and saved to `docs/superpowers/plans/2026-09-22-oa-agent-travel-expense.md`.

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每任务新开子代理，任务间审查  
2. **Inline Execution** — 本会话按 `executing-plans` 连续做并设检查点  

选哪一种？若先只做 Service 鉴权底座（Task 1–3），也可以说。
