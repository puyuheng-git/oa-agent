# MCP 内置 Tool · 出站连接 · Guard 交付（2026-10-27）

| 项 | 内容 |
|----|------|
| 范围 | `docs/superpowers/plans/2026-10-27-mcp-builtin-tool-guard.md` Task 1–13（P0–P3） |
| Spec | `docs/superpowers/specs/2026-10-27-mcp-builtin-tool-guard-design.md`（D18′ / D20–D23） |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md` §8.1（本次已回写摘要） |
| 状态 | 代码与自动化测试完成；**真实 MCP Server、真实搜索供应商、浏览器手工验收均未验证**（见测试表） |

## 1. 功能

| 阶段 | 内容 |
|------|------|
| P0 | `agent_tool.kind`（`office` / `builtin` / `mcp`）+ `agent_mcp_server` 表 + 权限点 `ops.mcp.manage`；`ToolSpec.kind` 与注册条件按 kind 分叉；`prompt_guard` 骨架接入用户消息 / 历史 / 记忆；Skill/Tool 页职责说明与 Tool `kind` 筛选 |
| P1 | MCP 连接 CRUD / test / sync API；真实出站 MCP Client（stdio / http，sse 兼容）+ 会话池；Executor `kind=mcp` 分发；管理端「MCP 连接」页 |
| P2 | `BUILTIN_CATALOG` + 启动幂等 upsert；`BuiltinRuntime`：低风险 `sys.time/calc/export/memory` 可用；高风险 `sys.http/web_search/fs_read/fs_write/cron` 默认关，无 `sandbox_policy` 即 `SANDBOX_REQUIRED` |
| P3 | `prompt_guard` 加深：base64（含 urlsafe、套娃一层）/ hex / 百分号编码解码预览（每候选 2KB）；`scrub_html_with_flags`（去脚本/注释/隐藏块/标签，`web_induction`）；`guard_flags` 写入 `tool_call_end` 事件元数据；mcp/builtin 结果统一围栏；设计 §8.1 回写 |

要点：
- **D18′**：出站 MCP 由「仅接口 + Noop」演进为可配置真实 Client，Noop 仅作未配置回退。
- 同步来的 MCP Tool 一律 `enabled=false`；员工界面不出现 MCP / builtin 字样；可见性仍只挂 Skill（D17）。
- 硬约束不变：OA 仅 HTTP、`td_oa` 零访问、密钥只写不读、管理写 = 权限点 + CSRF + `Idempotency-Key` + 审计。

## 2. 文件清单（相对 `af1586d` 初始提交，主要文件）

| 区域 | 文件 |
|------|------|
| 迁移 | `backend/migrations/versions/0011_tool_kind_mcp_server.py` |
| 模型 / 权限 / 配置 | `backend/oa_agent/db/models.py`、`auth/perms.py`、`config/schema.py`（`mcp.allowed_origins`、`runtime.http_allow_hosts`） |
| 执行器 | `executor/registry.py`、`catalog.py`、`executor.py`、`outbound.py`、`mcp_pool.py`、`mcp_runtime.py`、`mcp_sync.py`、`builtin_catalog.py`、`builtin_runtime.py` |
| 安全 | `security/prompt_guard.py`、`security/__init__.py`、`chat/memory_guard.py` |
| 管理 API | `admin/mcp_servers_api.py`（新）、`admin/catalog_api.py`（kind 筛选）、`main.py`（挂载） |
| 对话接入 | `chat/service.py`（注入 `BuiltinRuntime` / `mcp_client`）、`runtime/graphs/oa_assistant.py`（Task 3 扩展范围，见 `.superpowers/sdd/task-3-extra-scope.md`）、`runtime_state.py` |
| 前端 | `McpServersView.vue`、`mcpForm.ts(.spec.ts)`、`AbilityHelpBanner.vue`、`ToolsView.vue`、`SkillsView.vue`、`router.ts`、`ops.ts` |
| 测试 | `test_tool_kind.py`、`test_prompt_guard.py`、`test_mcp_servers_api.py`、`test_outbound_mcp.py`、`test_builtin_tools.py`、`test_catalog.py` 等 |
| 文档 | 设计 §8.1、roadmap D18 注记、本文 |

依赖：`backend/pyproject.toml` + `uv.lock` 新增 MCP SDK。

## 3. 迁移说明

- 新迁移 `0011_tool_kind_mcp_server`（不改写已发布迁移）：`agent_tool` 增 `kind`（默认 `office`）、`builtin_id`、`mcp_server_id`、`mcp_tool_name`、`sandbox_policy_json`；新表 `agent_mcp_server`；种子权限点 `ops.mcp.manage`。
- 旧 office Tool 行 `kind` 默认 `office`，行为不变；builtin 行在启动时由 `ensure_builtin_tools` 补插（已存在的不覆盖）。
- 回滚：降级迁移删除新列/表；已落库的 builtin / mcp Tool 行与 Skill 绑定需先清理。**降级未在真实 MySQL 上演练**（见测试表）。
- 新增配置：`mcp.allowed_origins`（远程 MCP 白名单，空 = 全拒）、`runtime.http_allow_hosts`（`sys.http` 全局白名单，空且 Tool 未配 = `SANDBOX_REQUIRED`）。

## 4. API 说明

| 路径 | 权限 | 说明 |
|------|------|------|
| `GET/POST /v1/admin/mcp-servers`、`GET/PUT/DELETE /v1/admin/mcp-servers/{name}` | `ops.mcp.manage` | 连接 CRUD；密钥（headers / env）只写不读，响应仅掩码；写操作 CSRF + `Idempotency-Key` + 审计 |
| `POST /v1/admin/mcp-servers/{name}/test` | `ops.mcp.manage` | 真实 `initialize`；失败如实返回脱敏原因 |
| `POST /v1/admin/mcp-servers/{name}/sync` | `ops.mcp.manage` | `tools/list` → upsert `kind=mcp`（`enabled=false`）；映射 `inputSchema` 到 `model_params` |
| `GET /v1/admin/tools?kind=` | `ops.tool.manage` | 新增 `kind` 筛选；builtin / mcp 不可改核心实现字段 |
| 对话 | 员工 | 无新增端点；Tool 经 Skill 暴露，结果统一围栏回图 |

## 5. 权限与安全

- 新权限点 `ops.mcp.manage`（与 `ops.tool.manage` 分离）。
- MCP：远程 URL 须命中 `mcp.allowed_origins`；stdio 命令须绝对路径（预置二进制白名单一期为空）且禁 shell 元字符；结果默认截断 32KB；默认不向 MCP 传员工 `oa` / token；错误信息脱敏。
- builtin 高风险：默认关 + 必须有沙箱策略；http 白名单主机、默认 GET、不跟随重定向、不带员工 Authorization、响应限字节；fs 限 `data/sandbox/{tenant}/` 并 resolve 后复核；cron 只登记已发布 workflow，不执行；web_search 密钥取 Vault，不进结果/错误。
- prompt_guard：围栏 + 规范化 + 标志；标志不含原文；**检测仅辅助，不参与权限判定**。
- 模型输出不参与权限；可见性与执行前门禁仍在服务端。

## 6. 测试结果

分类：**自动化通过** / **手工** / **未执行** / **外部依赖未验证** / **自动化失败（非本功能范围，待确认）**。

| # | 项 | 分类 | 说明 |
|---|----|------|------|
| 1 | 后端 `tests/test_prompt_guard.py`、`test_builtin_tools.py`、`test_memory_guard.py`（含 §6.4 三条：零宽+忽略以上、base64 包 ignore previous、HTML 脚注诱导留在围栏且 `web_induction`） | 自动化通过 | Task 12 提交后复跑 |
| 2 | 后端 `test_tool_kind.py`、`test_mcp_servers_api.py`、`test_outbound_mcp.py`（MCP 用 fake opener / respx，非真实 Server） | 自动化通过 | 全量 pytest 中通过 |
| 3 | 后端全量 `pytest`（2026-10-27） | 自动化通过（除下一行） | 1 项 skip（符号链接用例，无权限环境） |
| 4 | `tests/test_catalog_admin.py::test_tool_form_validation`、`::test_tool_edit_follows_version_rules`（`POST /v1/admin/tools` 返回 422 / 404） | **自动化失败（待确认）** | 疑似工作区他人未提交的 `catalog_api.py` / `catalog.py` WIP；**未在干净 HEAD 复验**，不得视为通过 |
| 5 | 前端 `npm run test`：16 个文件 91 例（含 `mcpForm.spec.ts` 4 例） | 自动化通过 | 工作区含他人 WIP 改动 |
| 6 | 前端 `vue-tsc --noEmit` | 自动化通过 | exit 0 |
| 7 | MCP 连接页浏览器手工验收（见下清单 6 项） | **未执行** | 手工勾选前保持未执行 |
| 8 | 真实 MCP Server（stdio 本机进程 / 远程 Streamable HTTP / SSE）端到端：test → sync → 启用 → Skill 绑定 → 对话调用 | **外部依赖未验证** | 仅 fake / mock 验证 |
| 9 | 真实搜索供应商 `sys.web_search` | **外部依赖未验证** | 仅 respx 模拟；供应商 key 后台录入入口未做 |
| 10 | 真实网页 / 外部站点上的 `sys.http` + 诱导页面 | **外部依赖未验证** | 仅 respx 模拟 |
| 11 | MySQL 上迁移 `0011` 升级 / 降级 | **未执行** | 自动化仅 SQLite 内存库跑 Alembic |
| 12 | Redis 下 `sys.cron` 登记持久化 | **未执行** | 测试用 MemoryKV |
| 13 | 多实例 / 并发下 MCP 会话池与定时任务 | **未执行** | 非目标（规格 §1） |
| 14 | 企微 / OA iframe 真实入口下的 guard 行为 | **未执行** | — |
| 15 | 安全评审（独立 review-security） | **未执行** | — |

### Task 8 手工验收清单（MCP 连接页）

| # | 项 | 状态 |
|---|-----|------|
| 1 | 无 `ops.mcp.manage` 的账号看不到菜单，直访被重定向。 | **未执行** |
| 2 | 未配白名单时新建远程连接 → 后端 422 提示；配 allowlist 后可创建。 | **未执行** |
| 3 | 编辑不回填密钥；留空保存后掩码仍为「已设置」；勾选清除后变「未设置」。 | **未执行** |
| 4 | 切换 transport 保存后对应字段/密钥符合后端规则。 | **未执行** |
| 5 | 测试连接 / 同步 Tools 成功与失败（错误文本已脱敏）均能显示；列表 last_sync_* 刷新。 | **未执行** |
| 6 | 同步后到 Tool 管理启用 → Skill 绑定 → 对话可调。 | **未执行** |

**前置：** 后端已启、管理端可登录；远程 MCP 或 stdio fixture；Settings 中 MCP 地址白名单（`mcp` 配置组）。禁止将未执行项标为通过。

## 7. 未完成项 / 已知风险

- **真实联调缺失**：MCP Server、搜索供应商、真实站点均未联调（测试表 8–10）。
- `sys.http`：无 DNS rebinding / 私网 IP / 云元数据地址拦截，依赖管理员白名单；规格「平台级拒绝名单」未做。
- `sys.cron`：只登记不调度（一期）；MemoryKV 下重启丢失。
- fs 沙箱按 **tenant** 隔离，同租户员工共享目录（符合规格 `data/sandbox/{tenant}/`；若需按员工隔离须另行设计）。
- Settings UI 对 `http_allow_hosts` 只读提示未做；web_search 供应商 key 后台录入入口未做（目前经 Vault 写入）。
- prompt_guard：仅覆盖 base64 / hex / 百分号；未覆盖 rot13 / 图片文字；隐藏块剥离用正则（嵌套同名标签有残余，仍被扫描并留在围栏内）；`guard_flags` 仅入事件元数据，未驱动 UI 告警；**office 结果暂未强制围栏**（Task 12 Step 3 可选项未做）。
- stdio「预置二进制白名单」一期为空，仅允许绝对路径命令。
- `test_catalog_admin` 2 项失败待确认归属（见测试表 4）。
- 规格 §5.3：`sys.fs_write` / 非 GET http 的确认流未就绪，保持默认关；启用前须评估。
- 设计 §1 仍写「一期只做只读查询」：高风险 builtin（fs_write / cron）默认关，未改该句，后续启用高风险写类能力时再同步。

## 8. 下一阶段计划

1. 手工勾选 MCP 页 6 项；用真实 MCP Server（本机 stdio + 一个远程 http）走完整链路并记录。
2. 接入一个搜索供应商并补后台录入密钥入口；对 `sys.http` 补私网 / 元数据地址拒绝名单与 DNS 解析后校验。
3. 澄清并修复 `test_catalog_admin` 2 项失败（确认是否 WIP 引入）。
4. 评估 office 结果围栏、`guard_flags` 告警展示、cron 调度器与按员工隔离沙箱。
5. 跑一次独立安全评审（review-security）后再开放高风险 builtin 给生产 Skill。
