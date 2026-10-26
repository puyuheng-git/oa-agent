### Task 4: OpenAPI 契约文件（两只读）

**Files:**
- Create: `D:\MYOA\webroot\puyueheng\agent-gateway\openapi\travel_expense.yaml`

**Interfaces:**
- Produces: `operationId`: `query_my_travel_expense_list` / `query_my_travel_expense_detail`；含 `x-agent` 块（见 spec §5.6）

**Steps:**

- [ ] **Step 1: 编写 YAML**

- servers.url = `{OFFICE_API_BASE}`  
- paths:
  - `GET /out_attendance/go_out_travel_expense/index`
  - `GET /out_attendance/go_out_travel_expense/detail`  
- parameters：page/limit/queryParams（说明 oa 由适配器注入）  
- `x-agent.inject_identity_fields: [oa]`  
- store/delete **不要** enabled  

- [ ] **Step 2: 人工校对 operationId 与 spec 一致**

---
