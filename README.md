# oa-langGraph

OA 智能助手的 Agent 服务：员工在 OA 内通过 iframe 查询本人行程报销，LangGraph 负责编排，业务数据只来自 office-api；附带运营管理后台（监控、人工介入、Tool/Skill、流程配置版本、账号权限、审计）。

## 部署

需要 [uv](https://docs.astral.sh/uv/)、Node.js 18+（构建前端）、MySQL。

```powershell
.\scripts\start.ps1 -BindHost 0.0.0.0     # Linux: HOST=0.0.0.0 scripts/start.sh
```

首次启动进入安装向导 `/setup/`（安装令牌在 `data/setup.token`）。务必备份 `data/master.key`。员工入口是 OA 页面里的悬浮气泡（OA 粘贴 `embed.js` 代码，见使用说明 §4.1）。详见：

- [部署与运维手册](docs/ops/deployment.md)
- [使用说明](docs/ops/user-guide.md)
- [设计文档](docs/design/2026-10-09-oa-langgraph-design.md)
- [P3–P6 交付报告](docs/delivery/2026-10-09-p3-p6-delivery.md)

## 开发

```powershell
cd backend;  uv run pytest -p no:cacheprovider -q --basetemp=.pytest_tmp
cd frontend; npm test; npm run build
```
