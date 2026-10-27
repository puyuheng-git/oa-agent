# MCP 内置 Tool · 出站连接 · Guard 交付（2026-10-27）

| 项 | 内容 |
|----|------|
| 范围 | `docs/superpowers/plans/2026-10-27-mcp-builtin-tool-guard.md`（进行中） |
| Spec | `docs/superpowers/specs/2026-10-27-mcp-builtin-tool-guard-design.md` |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md` |

> 本文随 Task 逐步追加；Task 8 先落 Step 3 手工验收清单。

## Task 8：MCP 连接前端页（McpServersView）

### 手工验收清单（Step 3）

| # | 项 | 状态 |
|---|-----|------|
| 1 | 无 `ops.mcp.manage` 的账号看不到菜单，直访被重定向。 | **未执行** |
| 2 | 未配白名单时新建远程连接 → 后端 422 提示；配 allowlist 后可创建。 | **未执行** |
| 3 | 编辑不回填密钥；留空保存后掩码仍为「已设置」；勾选清除后变「未设置」。 | **未执行** |
| 4 | 切换 transport 保存后对应字段/密钥符合后端规则。 | **未执行** |
| 5 | 测试连接 / 同步 Tools 成功与失败（错误文本已脱敏）均能显示；列表 last_sync_* 刷新。 | **未执行** |
| 6 | 同步后到 Tool 管理启用 → Skill 绑定 → 对话可调。 | **未执行** |

**前置：** 后端已启、管理端可登录；远程 MCP 或 stdio fixture；Settings 中 MCP 地址白名单（`mcp` 配置组）。

**自动化（Task 8 报告）：** `npm run test`（含 mcpForm 4 例）、`vue-tsc --noEmit` exit 0 — **自动化通过**。浏览器手工项见上表 — **未执行**。

禁止将未执行项标为通过。
