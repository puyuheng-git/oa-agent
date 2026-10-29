# demo_http — 无 OA 演示包

最小 **Domain Pack**：可被扫描发现、默认启用，声明依赖连接器标识 `demo`。不含预置 Tool/Skill（`tools_openapi` / `skills` 为空），意图规则为空，用于验证 Pack 注册与「非 office 连接器」组合。

## 快速开关

| 步骤 | 操作 |
|------|------|
| 1 | 管理后台 → **连接配置** → **IdP**：开启 `demo_idp_enabled`，设置 `demo_shared_secret`（勿用于生产） |
| 2 | **领域包**：确认 `demo_http` 为 **启用**（`default_enabled: true`；若曾禁用，点启用并填操作原因） |
| 3 | （可选）禁用 `oa_travel`，避免无 office 配置时出现行程相关校验噪音 |

IdP 细节见 [`docs/ops/demo-idp.md`](../../docs/ops/demo-idp.md)。

## 跑通 raw_json Tool（mock 上游）

平台自动化用例（`backend/tests/test_demo_no_oa_m4.py`）的做法可复现为：

1. 启动任意返回 JSON 的 mock HTTP，例如 `GET /api/items` → `{"items":[{"id":1,"name":"alpha"}],"total":1}`。
2. **连接配置** → **业务上游**：增加标识 **`demo`**，基址指向 mock 根 URL（与 Pack 中 `connectors: [demo]` 一致）。
3. **Tool 管理** 新建只读 Tool：`upstream`/`业务上游` = `demo`，路径 `/api/items`，`envelope_profile` = **`raw_json`**（若表单无该字段，用带扩展的 catalog/OpenAPI 导入，见手册）。
4. 配 Skill 或依赖 LLM 选 Tool；Demo 会话凭证会作为 `Authorization` 发往 mock（默认 `Bearer demo-token`）。

> **说明：** 员工侧 `demo` 渠道的完整对话入口随产品演进可能仍依赖 OA launch；当前仓库以 Broker + Executor 自动化测试验收 Demo IdP 与 `demo` connector。端到端 UI 联调请在测试环境按 **[新系统接入手册](../../docs/ops/integrate-external-system.md)** 执行，**勿声称**已与真实 OA 联调通过。

## 文件

| 文件 | 作用 |
|------|------|
| `pack.yaml` | Pack 清单 |
| `rules/intent.yaml` | 空规则占位，保证 Pack 可聚合 |

## 延伸阅读

- **[新系统接入手册](../../docs/ops/integrate-external-system.md)** — 生产/测试环境接入外部 HTTP 系统的完整步骤与验收清单。
