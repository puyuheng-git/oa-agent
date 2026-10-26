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
