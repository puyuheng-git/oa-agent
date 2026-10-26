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
