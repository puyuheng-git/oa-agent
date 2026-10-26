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
