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
