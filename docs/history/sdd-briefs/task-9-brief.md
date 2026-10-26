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
