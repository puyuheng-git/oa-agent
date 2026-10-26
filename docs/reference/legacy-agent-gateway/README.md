# OA Agent Gateway (MVP-1)

独立部署的 Agent 网关：OA / 企微入口 → 会话 ticket → 规则编排 → MCP 调 office-api 行程报销只读接口。

## 快速启动

```bash
cd agent-gateway
cp .env.example .env
# 编辑 AGENT_GATEWAY_SECRET / OA_ASSERTION_HMAC_SECRET / OFFICE_API_BASE_URL / REDIS_URL
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8088
```

探活：`GET /healthz`

## 关键依赖

| 配置 | 说明 |
|------|------|
| `AGENT_GATEWAY_SECRET` | 与 office-api / Service `env('AGENT_GATEWAY_SECRET')` 一致 |
| `OA_ASSERTION_HMAC_SECRET` | 与 OA 薄桥环境变量一致 |
| `OFFICE_API_BASE_URL` | office-api 根地址 |
| `REDIS_URL` | 会话与 nonce |

office-api 需已部署：`POST /agent/token/mint`、AuthUser Authorization 优先、行程 detail 强制 oa。

## OA 入口

- 薄桥：`/general/ds/agent/bridge/ticket.php`
- 助手页：`/general/ds/agent/views/assistant.php`
- OA 环境变量：`AGENT_GATEWAY_URL`、`OA_ASSERTION_HMAC_SECRET`

## 企微

`/v1/wecom/callback` 目前为骨架（echostr 透传）；完整验签与绑定解析见计划 Task 10。

## Spec / Plan

- `docs/superpowers/specs/2026-09-21-oa-agent-travel-expense-design.md`
- `docs/superpowers/plans/2026-09-22-oa-agent-travel-expense.md`
