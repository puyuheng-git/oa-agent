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
