## Context

员工对话经 OA assertion → mint 员工 `Authorization`（只存 Agent Redis）。业务 Tool 现网主路径是 open-oa / office-api 等认 Passport 的 HTTP 面。大量存量能力仍在 OA Webroot 脚本上，依赖 `inc/auth.php` / `helper/auth_login.php` 的 PHP Session。Agent 无浏览器 Cookie，不能直打旧口；又要求**不改旧接口源码**。grill-me 结论：统一 `invoke` 反代 + 请求内绑 Session + include。

利益相关：OA（PHP 5.2 GBK）、Agent（oa-langGraph）、运营配 Tool 的管理员。

## Goals / Non-Goals

**Goals:**

- 单一 OA 入口承接 Agent 对存量脚本的调用，鉴权不裸奔
- 读：员工票 + 网关密钥；写：再加短时确认 HMAC（与对话确认闭环衔接）
- 零改旧业务文件；身份以 Bearer/`checkLogin` 为准并覆盖请求中的身份参数
- `target` 路径护栏；管理端测调与现网同闸

**Non-Goals:**

- 重构旧口为显式 `$oa`/`$uid` 函数（真 C2）
- 一旧对一新 `*_agent_api.php`
- OA 回调 Agent 核销 confirm；独立 confirm HMAC 密钥
- Agent 直连 `td_oa`；把旧 URL 直接配成 Tool 路径（绕过 invoke）

## Decisions

### D1. 统一 `invoke.php`，不改旧文件

- **选择：** `/general/ds/agent/invoke.php` 鉴权后本请求写 `$_SESSION`/`$LOGIN_*`，`include` Tool 配置的相对路径，剥离 `Set-Cookie` 后回传。
- **相对：** 抽公共函数（改动面大）；HTTP 子请求打旧 URL（仍缺 Session，更绕）。
- **理由：** 满足「零改旧代码」且复用既有 `auth.php` 校验路径。

### D2. 鉴权强度 B2 + 写确认 E2/F2/G2

- **读：** `Authorization` → `ANew('oa/user')->checkLogin` + `X-Agent-Gateway-Secret`（与配置 `AGENT_GATEWAY_SECRET` / Agent 侧一致）。
- **写：** 另要求确认断言头；断言由 Agent 在员工确认后签发；OA 本地 HMAC 验签（复用 `assertion_hmac_secret` / `OA_ASSERTION_HMAC_SECRET`），`iss`/`aud` 与登录 assertion 区分（建议 `iss=oa-langgraph`，`aud=oa-general-write`）；`oa` 必须与 Bearer 一致；`nonce` 进 Redis，TTL ≥ 断言寿命，一次性。
- **相对：** 仅 Bearer（任意持票客户端可打）；回调 Agent 核销（多一跳）。
- **理由：** 对齐 open-oa agent invoke 的双因子思路，写操作纵深。

### D3. `target` 来自 Tool 配置（J2）+ 前缀白名单（K3）

- **允许根：** `general/`、`inc/`、`helper/`、`task/`（可配置扩展，默认这四类）。
- **校验：** URL 解码、统一分隔符、拒 `..`、拒绝对路径、必须 `.php` 且实文件存在。
- **传递（L1）：** `X-Agent-Target` 或约定参数 `target`；业务参数走原生 query/body；合并前剔除 `gateway_secret`、确认断言、`target`；覆盖 `oa`/`user_id` 等身份键。
- **`target` 不得进入 `model_params`。**

### D4. Agent 出站与挂载

- 上游：OA Web 源站 peer（如 `oa_web`）或复用已有 OA 域名条目；Tool **路径固定**为 `/general/ds/agent/invoke.php`。
- Connector 自动附加网关密钥；写 Tool 确认通过后附加确认断言。
- 读 GET；写允许 POST（或与旧口一致的方法），须标高风险并走确认。
- 管理端测调（M1）：同一 invoke；测试员工 mint + 网关密钥；写测调也签发短时确认断言。

### D5. 头与断言字段（约定）

| 项 | 约定 |
|----|------|
| 员工票 | `Authorization: <token>`（与现网 mint 一致，不必强制 Bearer 前缀若现网无前缀） |
| 网关密钥 | `X-Agent-Gateway-Secret` |
| 目标脚本 | `X-Agent-Target: general/ds/.../foo_api.php` |
| 确认断言 | `X-Agent-Confirm-Assertion: <base64url>.<hmac_hex>`（形态对齐登录 assertion） |
| 断言 payload | `oa`, `uid?`, `action`（Tool 稳定 id 或约定动作名）, `exp`, `nonce`, `iss`, `aud` |

## Risks / Trade-offs

- [include 触发 auth.php 非 Ajax 输出 HTML] → invoke 将请求标为 Ajax / 适当 `ob`，并测典型旧口
- [绑 Session 产生 Set-Cookie] → 响应剥离所有 Set-Cookie；session_write_close；不向 Agent 客户端暴露
- [inc/helper 非 HTTP 入口被配成 target] → 文档警告；运营评审；前缀白名单不替代「只配真实入口」
- [复用 assertion 密钥] → 依赖不同 `aud`/`iss`；轮换时登录与写确认同时受影响（已知取舍 G2）
- [旧口内部信任 Session 后再信参数 oa] → invoke 强制覆盖身份参数；无法修旧口逻辑缺陷时需业务评估
- [Redis 不可用导致写全失败] → 写口明确错误；读不受影响；运维监控 Redis

## Migration Plan

1. OA 部署 `invoke.php` + Redis nonce 键约定；确认与 Agent 共享 assertion HMAC、网关密钥。
2. Agent 发布 Connector/确认断言签发与测调；配置 OA Web 上游。
3. 先接 1 个只读旧口验证 Session include；再接 1 个写口验证确认断言。
4. 回滚：下线 Tool / 关掉上游；OA 删除或拒绝 `invoke.php` 即可，旧口未改无需回滚。

## Open Questions

- OA 本机 Redis 连接是否已有现成 helper，还是经 Service 小接口写 nonce（实现期确认）。
- 写操作判定：按 HTTP 方法 ≠ GET，还是 Tool 风险等级 / 显式头（实现期与执行器对齐，默认「非 GET 或高风险须断言」）。
