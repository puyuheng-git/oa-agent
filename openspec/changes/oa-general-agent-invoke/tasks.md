## 1. OA invoke skeleton

- [x] 1.1 Add `general/ds/agent/invoke.php` (PHP 5.2 / GBK) entry: read Authorization、网关密钥、`X-Agent-Target`、确认断言头
- [x] 1.2 Add helper(s) under `general/ds/agent/` or `helper/`：B2 校验（`ANew('oa/user')->checkLogin` + gateway secret）、错误用 `Api::err` 友好文案
- [x] 1.3 Implement `target` normalize + allowlist prefixes `general/` `inc/` `helper/` `task/` + exist `.php` check
- [x] 1.4 Request-local Session/`$LOGIN_*` bind；`ob` include 目标；剥离 `Set-Cookie`；覆盖身份参数并剔除敏感键

## 2. OA write confirm

- [x] 2.1 Parse/verify confirm HMAC（复用 assertion 密钥；`iss`/`aud` 与登录 assertion 区分；`oa` 与 Bearer 一致；`exp`）
- [x] 2.2 Redis nonce 一次性写入（确认 OA Redis 连接方式；不可用时写口失败可读）
- [x] 2.3 Gate：读不要求断言；非 GET / 高风险写无断言则拒绝

## 3. Agent connector & Tool

- [x] 3.1 Support OA Web upstream + Tool path `/general/ds/agent/invoke.php`；出站附加网关密钥与 `X-Agent-Target`（仅服务端配置）
- [x] 3.2 Ensure `target` / secrets 不进 `model_params`；读 GET、写高风险须确认
- [x] 3.3 After employee confirm, mint write confirm assertion and attach `X-Agent-Confirm-Assertion`
- [x] 3.4 Admin Tool probe：测试员工 mint + 网关密钥；写测调也带确认断言；无免鉴权调试口

## 4. Tests & docs

- [x] 4.1 OA：拒无票、拒无密钥、拒 `..`、拒前缀外路径、读成功 include、写无断言失败、断言 oa 不一致失败、nonce 重放失败（可用最小 stub 目标脚本）
- [x] 4.2 Agent：单元/集成测出站头、确认前不出站、确认后带断言、admin probe 写路径
- [x] 4.3 Update ops docs（`docs/ops` / 对接说明）：invoke 契约、头字段、前缀白名单、禁止直配旧 URL
- [ ] 4.4 Manual smoke：1 只读旧口 + 1 写旧口（确认卡 → invoke → 业务成功）
