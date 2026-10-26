### Task 8: 规则编排 + `/v1/chat`

**Files:**
- Create: `agent-gateway/app/orchestrator/rule_travel.py`, `app/chat/routes.py`
- Create: `agent-gateway/app/reply/types.py`

**Interfaces:**
- Consumes: ticket Bearer；用户 `message`；MCP invoke
- Produces: `{reply_type, content, meta}`

**Steps:**

- [ ] **Step 1: 意图规则（一期够用即可）**

- 匹配「行程|报销」+ 可选「上周|上月|未报销|已报销」→ 算 date_gte/lte、status → `query_my_travel_expense_list`  
- 匹配「详情|单号|#数字」→ `query_my_travel_expense_detail`  
- 否则 markdown 提示可问内容  

- [ ] **Step 2: `/v1/chat`**

校验 ticket；`client_msg_id` 去重；限流按 oa；调用编排；审计日志。

- [ ] **Step 3: 手工对话验收**「帮我查上周行程报销」

---
