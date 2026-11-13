# open-oa ANew / Export 通用接入 — 交付说明

**日期：** 2026-11-12  
**规格：** `docs/superpowers/specs/2026-11-12-open-oa-anew-invoke-design.md`  
**计划：** `docs/superpowers/plans/2026-11-12-open-oa-anew-invoke.md`

## 已交付

| 层 | 内容 |
|----|------|
| Service | `oa/agent_bridge`：注册表 + `listAgentExports` / `invokeAgentExport`（行程 list/detail） |
| open-oa | `POST /agent/token/mint`、`GET /agent/export-catalog`、`POST /agent/invoke`、`AuthAgentBearer` |
| office-api | Agent mint 路由下线（强拆） |
| Agent | `integrations/open_oa.py`；`kind=open_oa_invoke`；catalog 导入 API；行程 OpenAPI 改 invoke |

## 测试

- Agent：`test_open_oa_*.py`、行程 harness、chat 主路径等已在本地 pytest 通过。
- Service / open-oa：PHP 语法检查通过；**真机 ANew / HTTP 联调未执行**（外部依赖未验证）。

## 运维注意

1. Agent 配置 `mint_base_url` / 上游基址指向 **open-oa**。
2. open-oa 环境变量：`AGENT_GATEWAY_SECRET`、可选 `AGENT_MINT_ALLOW_IPS`。
3. 管理端：Tools 页「从 open-oa 清单导入」——`GET /v1/admin/tools/import/open-oa-catalog` 预览 + `POST` 勾选导入。
4. 写路径确认 + Idempotency-Key：注册表已预留；完整写样例可后续加。

## 未做 / 后续

- ~~管理端「从 open-oa 清单导入」UI~~（Tools 页已上）
- MCP Server 同步（catalog `extensions.mcp` 预留）
- 真环境联调与 GitLab 受保护 `master` 推送
