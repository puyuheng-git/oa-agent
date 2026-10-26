# MVP-1 Smoke checklist

| # | 场景 | 期望 | 结果 |
|---|------|------|------|
| 1 | `GET /healthz` | ok | |
| 2 | mint wrong secret | 失败 | |
| 3 | mint + Authorization list | 本人数据 | |
| 4 | detail 他人 id | 空/失败 | |
| 5 | OA assertion 过期 | 401 | |
| 6 | chat「查上周行程报销」 | markdown 列表 | |
| 7 | chat 伪装 oa | 无效 | |
| 8 | client_msg_id 重复 | 去重提示 | |
| 9 | 企微未绑定 | Task10 后验 | |

环境：Redis、office-api、`AGENT_GATEWAY_SECRET` 已配置。
