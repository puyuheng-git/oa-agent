### Task 7: MCP 通用执行器（list/detail）

**Files:**
- Create: `agent-gateway/app/mcp/openapi_loader.py`, `schema_builder.py`, `executor.py`, `policy.py`, `routes_internal.py`

**Interfaces:**
- Consumes: `travel_expense.yaml`；Session.office_token
- Produces: `invoke(capability, args, session) -> {ok, capability, data, message}`
- 强制：丢弃 args 中的 `oa`；注入 session.oa；limit max 20；裁剪返回字段（spec §5.5）

**Steps:**

- [ ] **Step 1: loader 读 YAML，只注册 `x-agent.enabled: true`**

- [ ] **Step 2: executor 用 httpx GET + Header Authorization + queryParams JSON**

- [ ] **Step 3: 单测/脚本**

对 mint 得到的真实用户：list 上周；detail 自己的 id；传入伪造 `oa` 确认被覆盖且不能看到他人数据。

---
