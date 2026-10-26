# MCP / Skill 可见权限交付（2026-10-23）

| 项 | 内容 |
|----|------|
| 范围 | 平台路线图 **C**（MCP / Skill / Tool 职责与可见权限）Task 1–7 |
| Spec | `docs/superpowers/specs/2026-10-23-mcp-skill-visibility-design.md` |
| Plan | `docs/superpowers/plans/2026-10-23-mcp-skill-visibility.md` |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md` §8.1 用语 + §12 visibility API |

## 功能

- **职责定稿**：Tool（office-api 能力）、Skill（员工可见能力包）、**执行器**（包 `mcp` 内 Registry/Executor）、**出站连接器**（标准 MCP Client 适配层，本期 Noop）。
- **数据层**：表 `agent_skill_visibility_rule`（迁移 `0009`）；ORM `SkillVisibilityRule`。
- **领域层**：`VisibilityService` — D19=C（无规则不裁剪）、allow/deny 优先级、`oa` / `tag` 主体；`EmptyTagProvider` 恒返回空标签（OA 覆盖预留）。
- **运行时**：欢迎 `skills`、帮助文案、`understand` 候选 Tool、Executor 执行前二次门禁；不可见 → `TOOL_NOT_AVAILABLE` /「该功能未对你开放」，不上游 office-api。
- **管理 API**：按 Skill 名读/写可见规则（全量替换）、按 `oa` 预览可见 Skill 列表；权限 `ops.skill.manage`；写操作 CSRF + Idempotency-Key + 审计 `skill.visibility.update`。
- **出站 MCP**：`OutboundMcpClient` Protocol + `NoopOutboundMcpClient`（无真实出站流量）。

## 文件清单

| 类别 | 路径 | 说明 |
|------|------|------|
| 设计 | `docs/design/2026-10-09-oa-langgraph-design.md` | §8.1 执行器/连接器 + 可见性；§12 API |
| 交付 | `docs/delivery/2026-10-23-mcp-skill-visibility-delivery.md` | 本文 |
| ORM | `backend/oa_agent/db/models.py` | `SkillVisibilityRule` |
| 迁移 | `backend/migrations/versions/0009_skill_visibility.py` | 建表 |
| 可见性 | `backend/oa_agent/mcp/visibility.py` | `PrincipalContext`、`VisibilityService` |
| 标签 | `backend/oa_agent/mcp/tags.py` | `TagProvider` + `EmptyTagProvider` |
| 出站 | `backend/oa_agent/mcp/outbound.py` | Protocol + Noop |
| Chat | `backend/oa_agent/chat/service.py` | `skill_menu` / `visible_skills_for` 过滤 |
| 图 | `backend/oa_agent/runtime/graphs/travel_query.py` | RunContext 候选与帮助 |
| 引擎 | `backend/oa_agent/runtime/engine.py` | 注入已过滤 skills |
| 执行器 | `backend/oa_agent/mcp/executor.py` | 执行前可见性断言 |
| 配置 | `backend/oa_agent/config/schema.py` | 默认不可见文案 |
| 管理 | `backend/oa_agent/admin/catalog_api.py` | visibility GET/PUT、preview |
| 入口 | `backend/oa_agent/main.py` | 注册 `visibility_router` |
| 测试 | `backend/tests/test_skill_visibility.py` | 领域 + HTTP + 运行时 |
| 测试 | `backend/tests/test_outbound_mcp.py` | Noop 出站 |

## 迁移说明

1. 部署后端前 Alembic 升级至 **`0009_skill_visibility`**（在 `0008_chat_thread` 之后）。
2. 空表时行为与升级前一致（D19=C）；无需 Redis / 前端构建变更。
3. 规则不进 Workflow Release；改规则即时生效。

## API 说明

鉴权：管理端本地账号 RBAC；读 `admin_read(SKILL)`、写 `admin_write(SKILL)`（`ops.skill.manage`）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/admin/skills/{name}/visibility` | 返回 `{ name, rules[] }`（含 effect、principal_type/value、created_by/at） |
| PUT | `/v1/admin/skills/{name}/visibility` | body `{ "rules": [...], "reason"?: string }` **全量替换**；`rules: []` 关闭裁剪 |
| GET | `/v1/admin/visibility/preview?oa=` | `{ oa, skills: [name, ...] }`（TagProvider 本期空） |

员工侧无新路径；可见 Skill 仍嵌在 `POST /v1/chat/session` 的 `skills` 等字段。

规则字段：`effect` = `allow` | `deny`；`principal_type` = `oa` | `tag`；`principal_value` 非空字符串。

## 权限与安全

- 目录可见性**不**替代 office-api 数据权限；身份仅来自服务端 `session.oa`，丢弃客户端自报 `oa` / `tags`。
- 模型输出不参与权限判定；不可见 Skill 的错误文案不泄露他人规则细节。
- 管理写：权限 + CSRF + Idempotency-Key + 同事务审计；审计失败则整单失败。
- 出站 MCP：白名单与身份边界在 Protocol/Noop 层钉死；本期无真实连接。
- 密钥只写不读；日志/审计无明文密钥。

## 测试结果

| 项 | 结果 | 标注 |
|----|------|------|
| backend `pytest -q`（全量） | **208** collected，exit 0（含 `test_skill_visibility` 9、`test_outbound_mcp` 1） | **自动化通过** |
| frontend `npm test`（vitest） | **15** files / **84** tests passed | **自动化通过**（与 C 无前端变更，回归仍绿） |
| frontend `npx vue-tsc --noEmit` | exit 0 | **自动化通过** |
| 手工：OA 标签覆盖联调 | 无 office-api 标签接口 | **未执行**（外部依赖未验证） |
| 手工：真实出站 MCP Server | 本期 Noop | **未执行**（规格内不做） |
| 手工：管理端可见性编辑 UI | 本期仅 API | **未执行** |
| 手工：多员工 OA iframe 验证裁剪 | 未接 OA / LLM | **未执行**（外部依赖未验证） |

禁止将未执行项标为通过。

## 未完成项

- **OA 标签 / 可办事宜 HTTP 联调**（`TagProvider` 预留，默认空）。
- **真实出站 MCP Server** 对接与白名单运维。
- **管理端可见性规则编辑 UI**（另开任务；现用 API）。

## 下一阶段（A）

按 `docs/superpowers/plans/2026-10-23-platform-next-roadmap.md`：**子系统 A**（员工背景与长期记忆 / Profile 注入）。C 验收建议在真实 OA + office-api 环境配置 allow/deny 规则，核对欢迎页、对话与执行门禁一致。
