# OA Agent（LangGraph 独立系统）— OA / Service 侧配套设计

**日期：** 2026-10-09
**状态：** 设计待确认
**权威设计：** [`2026-10-09-oa-langgraph-design.md`](2026-10-09-oa-langgraph-design.md)
**说明：** 本文所述代码改动在 OA / puyueheng 仓库执行，文中路径均相对于 `D:\MYOA\webroot\puyueheng` 或 `D:\MYOA\webroot`。

Agent 已定为**独立系统**（Python + LangGraph，独立仓库、独立部署、独立 MySQL `agent_ops`、独立管理后台账号体系）。本文只记录 OA 与 Service 需要承担的部分。

---

## 1. 与既有文档关系

| 文档 | 关系 |
|------|------|
| `2026-09-21-oa-agent-travel-expense-design.md` | 身份契约、Tool 契约继续有效；网关部分由独立仓库重写 |
| `plans/2026-09-22-oa-agent-travel-expense.md` | Task 1–3（Service/office-api）仍在本仓库执行；Task 5–8、10 由独立仓库重写；Task 9 改为 iframe 宿主页（§3.3） |
| `agent-gateway/`（puyueheng 内旧骨架） | 不再演进，仅作参考；独立仓库可用后另行确认是否删除 |

---

## 2. 盘点发现（2026-10-09）

1. **Task 1 不在磁盘上**：`LoginConst::TOKEN_BIZ_CODE_OFFICE`、`oa/user Export::agentMintOfficeToken`、`logic/AgentTokenImpl.php`、`oa/user/Error.php` 均不存在；`Export::checkLogin` 仍用 uid 调 `getUserInfoByUserId` 并返回 Passport 载荷。
2. **现网风险**：`site/office-api/app/middleware/AuthUser.php` 已改为「有 Authorization 即 checkLogin」，而 checkLogin 引用未定义常量 → 带该头的请求致命错误；`/agent/token/mint` 调用不存在的方法。
3. 已落地且保留：`controller/agent/Token.php` + 路由 + `noneedverifylogin` 白名单；`GoOutTravelExpense::detail` 强制 `oa`。
4. OA 薄桥 / 助手页未落地。

---

## 3. OA / Service 侧职责

### 3.1 Service（PHP 7.2）— 身份签发与校验（公用，重做计划 Task 1）

Authorization **签发与 checkLogin 的真相源在 Service**，不在某一个业务域名：

- `LoginConst`：`TOKEN_BIZ_CODE_OFFICE = 'office'`、`LOGIN_EXPIRE_OFFICE = 1800`，加入 `TOKEN_EXPIRE`（biz code 名可保留历史值，语义是「员工助手用 Passport」，不绑定 office-api 域名）。
- `oa/user Export::checkLogin`：按 UID 取 DB 用户行并返回该行。
- `oa/user Export::agentMintOfficeToken($oa, $gatewaySecret, $operateUser)` + `logic/AgentTokenImpl` + `Error`：`hash_equals` 校验 `AGENT_GATEWAY_SECRET`、`DuplicateSubmit::assert`、用户存在且可登录、Passport 签发、审计日志。
- 各业务 HTTP 面（office-api、service-api、open-oa 等，**名称不写死**）中间件统一：有 `Authorization` → 调 Service 校验身份 → **再**做该接口的业务授权与数据范围。入口（OA 宿主 / 企微 mint）只证明「是谁」，不一次放开全部业务接口。

### 3.2 业务上游 HTTP 面（含 office-api）与 mint 入口

- 核对各域 `AuthUser`（或等价中间件）与 Task 1 契约一致：认同同一 Passport；按 token 解析员工后再做业务校验。
- **mint HTTP**：现挂在 office-api `/agent/token/mint`；宜迁到更中性的公用入口（如 service-api 或独立鉴权路径），避免「只有 office 能签发」的错觉。`AGENT_MINT_ALLOW_IPS`、审计随入口迁移。Agent 配置上签发地址与业务上游目录已拆分，物理迁移可后置。
- office-api 业务接口（如行程 detail）继续按员工 token 强制身份，不信任客户端/模型自报 `oa`。

### 3.3 OA（PHP 5.2, GBK）— iframe 宿主页

- 新文件 `general/ds/agent/assistant_host.php`：`inc/auth.php` 登录校验 → 服务端构造 assertion `{oa, uid, display_name, exp≤60s, nonce, iss:"oa-host", aud:"oa-langgraph"}` 并 HMAC-SHA256 签名 → 服务端 POST Agent `/v1/chat/launch` 换一次性 `launch_code` → 输出 `<iframe src="{AGENT_URL}/chat/?launch=CODE">`。
- assertion 与 office token 均不进浏览器；OA 环境变量：`AGENT_URL`、`OA_ASSERTION_HMAC_SECRET`（与 Agent 后台配置一致）。
- 菜单入口由 OA 管理员按现有菜单机制挂载（整页方式，可选）。
- **悬浮挂件方式**：同一文件支持 `?mode=embed`——登录校验与签名、换码流程不变，最后改为 `302` 跳转到 `{AGENT_URL}/chat/?launch=CODE&embed=1`；未登录时返回提示文本。OA 公共页面引入 `window.oaAgentConfig = { hostUrl: '/general/ds/agent/assistant_host.php?mode=embed' }` 与 `<script src="{AGENT_URL}/embed.js" charset="utf-8" defer>`，脚本只负责气泡与 iframe，不携带任何身份或密钥。

#### 3.3.1 接口契约（Agent P1 已实现，以 Agent 代码为准）

**assertion 线格式**：`base64url(UTF-8 JSON，去掉 = 填充) + "." + hex小写(HMAC-SHA256(secret, base64url部分))`

| 字段 | 要求 |
|------|------|
| `oa` | 当前登录用户 OA 账号（Agent 只信任这里的 oa） |
| `uid` | 整数，可选 |
| `display_name` | 显示名；**必须先 `iconv('GBK', 'UTF-8', ...)`**，否则 PHP 5.2 `json_encode` 返回 null |
| `exp` | Unix 秒，`time() + 50` 左右；Agent 拒绝已过期（允许 30 秒时钟偏差）或超过 60 秒后的值 |
| `nonce` | ≥ 8 字符随机串，Agent 端一次性（重放返回 401 `ASSERTION_REPLAYED`） |
| `iss` / `aud` | 固定 `"oa-host"` / `"oa-langgraph"` |

**换启动码**：服务端 `POST {AGENT_URL}/v1/chat/launch`，`Content-Type: application/json`，body `{"assertion": "..."}`。
成功 `200 {"launch_code": "...", "expires_in": 60}`；失败 `{"error": {"code", "message"}}`，常见 401 `ASSERTION_INVALID|ASSERTION_EXPIRED|ASSERTION_REPLAYED`、502 `MINT_FAILED`、503 `OA_NOT_CONFIGURED|OFFICE_API_NOT_CONFIGURED`。宿主页失败时显示「助手暂不可用」，不要把错误体原样输出给用户。

`launch_code` 60 秒内一次有效；iframe 页读取后立即从地址栏移除，换得的 chat ticket 只存在浏览器内存（刷新需从 OA 重新进入）。

**PHP 5.2 参考写法**（`json_encode` / `hash_hmac` 均为 5.2 可用函数）：

```php
$payload = array(
    'oa' => $oa, 'uid' => (int)$uid,
    'display_name' => iconv('GBK', 'UTF-8//IGNORE', $user_name),
    'exp' => time() + 50, 'nonce' => md5(uniqid(mt_rand(), true)),
    'iss' => 'oa-host', 'aud' => 'oa-langgraph',
);
$body = rtrim(strtr(base64_encode(json_encode($payload)), '+/', '-_'), '=');
$assertion = $body . '.' . hash_hmac('sha256', $body, OA_ASSERTION_HMAC_SECRET);
// curl POST AGENT_URL/v1/chat/launch，超时 5 秒，取 launch_code
```

**嵌入白名单**：Agent 后台「OA 对接 → 允许嵌入的 OA 域名」填写 OA 的 origin（如 `https://oa.example.com`），否则 `/chat` 的 CSP `frame-ancestors 'none'` 会拒绝嵌入。

**mint 响应（office-api `/agent/token/mint`）**：Agent 按 `{code, msg, data: {authorization, uid, oa, expire}}` 解析，`code` 成功值在 Agent 后台「office-api 成功码」配置（默认 `0`、`200`）；`expire` 为剩余秒数或 Unix 时间戳均可；返回的 `oa` 必须与请求一致。**此格式尚未与现网联调确认。**

### 3.4 企业微信入口：mint 支持 `wework_user_id`（Agent、OA 均已实现，待联调）

Agent 通过企业微信智能机器人长连接收到员工消息，只拿到企业微信 `userid`。由 OA 解析绑定并签发 token，Agent 不做映射：

- **请求**：`POST /agent/token/mint`，表单 `wework_user_id`、`gateway_secret`；与 `oa` **二选一**，同时出现或都缺失时返回参数错误。鉴权、IP 白名单、`DuplicateSubmit`、审计与按 `oa` 签发一致。
- **解析**：`WeworkUserImpl::getMainUserIdByWeworkIds([$weworkUserId])` 取主账号；无主账号时用 `getUserIdsByWeworkId`：只绑定一个 OA 则用该账号，未绑定 → `AGENT_WEWORK_NOT_BOUND`，绑定多个 → `AGENT_WEWORK_NO_MAIN`；之后校验账号存在且可登录。
- **成功响应**：`{code: 0, data: {authorization, uid, oa, display_name, expire}}`，`oa` 为解析出的 OA 账号（Agent 以此作为员工身份），`display_name` 为 `USER_NAME`（按 `oa` 签发也会返回）。
- **失败响应**：`{code: 非成功码, msg: "给员工看的提示"}`，`msg` 会**原样展示给员工**，不放内部信息：

| 错误码 | 常量 | msg |
| --- | --- | --- |
| 1002600005 | `AGENT_WEWORK_NOT_BOUND` | 你的企业微信尚未绑定 OA 账号，请联系管理员 |
| 1002600006 | `AGENT_WEWORK_NO_MAIN` | 你的企业微信绑定了多个 OA 账号但未设置主账号，请联系管理员 |
| 1002600002 / 1002600003 | `AGENT_MINT_USER_NOT_FOUND` / `AGENT_MINT_USER_DENY_LOGIN` | 用户不存在 / 该账号已禁止登录 |

- **审计**：`[agent_mint]` 日志记录 `operate_user`、解析出的 `oa`、`uid`、`wework_user_id`，不记录 token；未绑定 / 多账号无主账号也会记日志。
- **实现位置**：office-api `app/controller/agent/Token.php::mint`；Service `oa/user/Export::agentMintOfficeTokenByWework` → `logic/AgentTokenImpl::mintOfficeTokenByWework`；错误码在 `oa/user/Error.php`。
- 注意：智能机器人若不是企业超级管理员创建，`userid` 为企业主体下的加密 userid，需确认现有绑定表能否匹配；不能时请由超级管理员创建机器人。

### 3.5 后续（随 Agent 阶段推进）

- MVP-3：报销草稿 / 提交业务 API（含幂等键、草稿版本、服务端重校验）。

**写 API 契约（Agent O2 / MVP-3，2026-10-26 增）：**

| 项 | 约定 |
|----|------|
| 草稿 | `POST .../go_out_travel_expense/submit/draft`（路径以 office-api 为准）；Body 仅含业务字段，**禁止**信任客户端/模型自报 `oa`、员工身份或权限结论 |
| 提交 | `POST .../go_out_travel_expense/submit`；须带 **`Idempotency-Key`**（Agent 管理写与员工确认提交均服务端生成/校验） |
| 身份 | 仅使用 office-api 以**该员工** token 解析出的身份；自报 `oa` 一律丢弃 |
| 幂等 | 重复 `Idempotency-Key` 返回同一业务结果，不重复落单 |
| 校验 | 草稿版本、字段、状态由 Service 重校验；Agent/LangGraph 不参与权限判定 |


---

## 4. 约束

- Agent 不访问 `td_oa`；所有业务数据经已配置的业务上游以员工 Authorization 获取；仅调用 Agent 侧已声明的 Tool/写契约。
- OA 侧代码遵守 PHP 5.2 / GBK / 文件头；Service 侧遵守 service-php73-architect，写路径 `DuplicateSubmit`。
- 改动后执行 stack-code-review。
