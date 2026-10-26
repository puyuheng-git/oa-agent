### Task 11: 端到端验收清单（对照 spec §9）

**Files:** 无代码；产出验收记录（可写在 PR 描述或 `agent-gateway/docs/smoke.md`）

**Steps:**

- [ ] **Step 1: 逐条执行**

| # | 场景 | 期望 |
|---|------|------|
| 1 | OA 助手查有数据区间 | 列表 markdown |
| 2 | 无数据区间 | 友好空结果 |
| 3 | detail 本人 id | 详情 |
| 4 | detail 他人 id（已登录 A） | 无数据/失败 |
| 5 | chat 传入伪装 oa | 无效 |
| 6 | 伪造 assertion | 401 |
| 7 | 企微未绑定 | 提示文案 |
| 8 | client_msg_id 重复 | 不重复查或幂等返回 |
| 9 | office-api 停掉 | UPSTREAM_ERROR 文案 |

- [ ] **Step 2: 更新 spec 状态为「已实现 MVP-1」或开 OpenSpec change 归档（若团队要求）**

---
