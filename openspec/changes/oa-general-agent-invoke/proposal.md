## Why

新建 Agent Tool 需要复用 OA 端已有接口（多为 `general/` 等依赖 `inc/auth.php` / `helper/auth_login.php` 的 Session 鉴权）。Agent 是独立服务、无浏览器 Cookie，不能照搬 Session，也不能去掉鉴权裸奔。需要统一、可治理的出站入口，在不改旧接口代码的前提下完成员工身份与写操作确认。

## What Changes

- OA 新增统一入口 `/general/ds/agent/invoke.php`：校验员工 `Authorization` + 网关密钥；写操作另校验短时确认 HMAC 断言（复用 assertion HMAC 密钥，换 `iss`/`aud`）+ Redis nonce 防重；本请求绑定 Session（不向 Agent 下发登录 Cookie）；按 Tool 配置的 `target` include 旧脚本并回传响应。
- `target` 经规范化后必须落在允许根前缀：`general/`、`inc/`、`helper/`、`task/`；禁止 `..` 与绝对路径；业务参数走 query/body，身份相关键由服务端覆盖。
- Agent：业务上游可指向 OA 源站；Tool 统一打 `invoke`；读 GET；写标高风险，确认后出站携带确认断言；管理端测调与现网同闸（测试员工票 + 网关密钥，写测调也要确认断言）。
- **不改**既有业务接口文件本身（零改旧代码；用请求内 Session + include 兼容）。
- Non-goals：抽公共函数重构旧口（C2）、一旧对一新 `*_agent_api.php`、OA 回调 Agent 核销 confirm、新独立 confirm HMAC 密钥、直连 `td_oa`。

## Capabilities

### New Capabilities

- `oa-general-agent-invoke`：OA 统一 invoke 鉴权、路径护栏、Session 绑定 include、写确认断言
- `agent-oa-web-connector`：Agent 侧上游/Tool 出站、确认断言签发、管理端测调同闸

### Modified Capabilities

- （无既有 `openspec/specs/`；行为记入上述新 capability）

## Impact

- **OA（`D:\MYOA\webroot`）**：新建 `general/ds/agent/invoke.php` 及辅助 include；Redis nonce；复用 `OA_ASSERTION_HMAC_SECRET` / 与 Agent `assertion_hmac_secret` 对齐；`ANew('oa/user')->checkLogin`
- **oa-langGraph**：Connector/出站头（网关密钥、`target`、确认断言）、高风险写 Tool 确认后附断言、管理端 HTTP 测调、配置/文档
- **oa-agent-chat**：通常无改（确认 UI 若已有可复用）
- 风险：`include` 旧口耦合 `auth.php` 行为；`inc/`/`helper/` 非入口脚本勿配为 `target`
