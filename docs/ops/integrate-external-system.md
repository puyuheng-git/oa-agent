# 新系统接入手册

面向管理员与对接开发：把**已有稳定 HTTP JSON API** 的业务系统接到 Agent 平台（只读查询为主；写操作仍走固定 Workflow + 员工确认，本手册不展开写路径）。

**验收口径：** 有稳定 HTTP JSON API 时，按手册可在一个工作日内完成 Agent 侧接入（不含对方改接口）。

**前提（硬约束）：**

- Agent 与业务系统只走 HTTP；不得直连 OA 业务库 `td_oa`。
- 业务数据只来自已配置上游、且以**该员工会话凭证**调用返回的结果；模型或客户端自报的 `oa` / 身份字段一律丢弃。
- Tool 只存**上游标识 + 相对路径**，不得写完整 URL；多个上游须属于**同一信任域**（认同同一员工 Authorization），或各自独立换票（禁止默认同票跨域）。
- 密钥只写不读；管理写操作须权限 + CSRF + `Idempotency-Key` + 审计。

权威设计：`docs/design/2026-10-09-oa-langgraph-design.md`；平台 Pack / Connector 规格：`docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`。

---

## ① 配置 HTTP 上游与响应信封

1. 登录管理后台 → **连接配置** → 组 **业务上游 / 连接器（兼容原 OA 对接）**（配置 key 仍为 `oa`）。
2. 在 **业务上游地址** 增加一条（示例）：

   | 字段 | 示例 | 说明 |
   |------|------|------|
   | 标识 `key` | `crm` | Tool 引用此标识，创建后不宜随意改名 |
   | 名称 | CRM 查询面 | 展示用 |
   | 基址 `base_url` | `https://crm-api.example.com` | 不含具体接口路径 |

3. 若员工 token 由 OA / 统一入口签发：填写 **员工 token 签发地址**（`mint_base_url`）与 **AGENT_GATEWAY_SECRET**，与现网 OA 对接一致（见 [使用说明 §4](user-guide.md#4-oa-对接说明给-oa-开发)）。
4. **响应信封（envelope）** 决定如何把 HTTP 响应解析成 Tool 结果：

   | `envelope_profile` | 适用 API | 行为摘要 |
   |----------------------|----------|----------|
   | `oa_office`（默认） | `{code, msg, data}`，成功码可配 | 与现网 office-api 一致；`success_codes` 在连接配置中维护 |
   | `raw_json` | 无业务 `code` 字段，HTTP 2xx 即成功 | 响应体整段作为 `data`；4xx/5xx → 上游 HTTP 错误 |

   - 管理端 **连接器总览**（连接配置页）对 HTTP 上游当前展示为 `oa_office`；若 API 为纯 JSON，须在 **Tool 元数据** 中声明 `envelope_profile: raw_json`（OpenAPI / catalog 导入或 Tool 版本 schema；后台表单若尚未暴露该字段，可先导入带扩展字段的 catalog，或联系平台维护方）。
5. **身份注入**：只读 GET Tool 可在 schema 中配置 `inject_identity_fields` / `identity_bindings`，由服务端写入当前员工标识；禁止把身份参数交给模型填写。
6. 保存前会测试连接（若适用）；保存后 **热生效**。可在 **连接器总览**（`GET /v1/admin/connectors`，需 `sys.setting.view` 或 `ops.tool.manage`）核对 `health: configured|missing`。

---

## ② 注册能力：Tool / Skill 或 Domain Pack

任选一种（可组合：Pack 引用仓库内 openapi / skills，与后台编辑并存）。

### 路径 A — 管理后台（适合单个接口快速上线）

1. **Tool 管理** → 新建 Tool：选 **业务上游** = ① 中的 `key`；**接口路径** = 相对路径；方法仅 **GET**。
2. 配置参数白名单、返回字段、身份注入（见 [使用说明 §3.3](user-guide.md#33-tool-管理)）。
3. **Skill 管理** → 新建 Skill：说明、填参指引、示例问题，并勾选上一步 Tool。
4. 员工重新打开助手即可在欢迎页看到新 Skill（须已配置 LLM 或存在匹配的规则意图）。

### 路径 B — 本机 Domain Pack（适合一组 Skill / 规则 / 契约）

1. 在仓库 `packs/<pack_id>/` 新建 `pack.yaml`（可参考 `packs/oa_travel/pack.yaml`）：

   ```yaml
   id: my_crm
   display_name: CRM 查询
   version: "1"
   connectors: [crm]          # 与上游 key 一致
   default_enabled: false     # 新包建议默认关，验收后再启
   skills: ["../../skills/my_crm.yaml"]
   tools_openapi: ["../../openapi/my_crm.yaml"]
   rules: rules/intent.yaml   # 可选；仅规则模式时需要
   workflows: []
   ```

2. 重启或触发热加载路径（进程启动时扫描 `packs/`）；在 **领域包** 页确认包已发现且无 `validation_errors`。
3. 首次仍可通过 **从文件导入** 将 openapi 同步进 Tool 目录，之后以后台版本为准。

**Pack 与 Tool 关系：** 启用 Pack 会聚合其 Skill、意图规则与 Workflow 元数据；禁用 Pack 不删除 Tool 历史版本，但运行时不再暴露该包能力（见 M3 交付说明）。

---

## ③ 选择身份提供者（IdP）

| IdP | 渠道 | 配置位置 | 典型场景 |
|-----|------|----------|----------|
| `oa_assertion` | OA Web / iframe | OA 对接：assertion HMAC、允许嵌入域名；OA 宿主页 `POST /v1/chat/launch` | 生产员工从 OA 进入 |
| `wecom` | 企业微信单聊 | 连接配置 → 企业微信 BotID/Secret；OA 签发入口支持 `wework_user_id` mint | 生产移动办公 |
| `demo` | `demo` | 连接配置 → **IdP** 组：`demo_idp_enabled`、`demo_shared_secret` | **仅本机/演示**；默认关闭，生产勿开 |

- 渠道路由约定（代码默认）：`oa_web → oa_assertion`，`wecom → wecom`，`demo → demo`。
- Demo 会话不 mint office token；`credentials["demo"]` 由 Demo IdP 写入（默认 `Bearer demo-token`），供 `raw_json` 等非 OA 上游使用。详见 [Demo IdP 说明](demo-idp.md) 与 `packs/demo_http/README.md`。
- OIDC 适配器仅为骨架（`501 IDP_NOT_IMPLEMENTED`），勿用于生产。

---

## ④ 在管理后台启停领域包

1. 菜单 **领域包**（权限 `ops.tool.manage`）。
2. 列表字段：`id`、显示名、版本、`enabled`、`connectors`、`validation_errors`。
3. **启用 / 禁用**：写操作带 CSRF + `Idempotency-Key`，并刷新运行时 Registry。禁用会写入 `packs.disabled_ids`、移除同 id 的 `packs.enabled_ids`；启用会移除禁用覆盖，且对 `default_enabled: false` 的包写入 `packs.enabled_ids`，因此重载后仍保持启用。
4. 新系统独立 Pack 建议 **`default_enabled: false`**，联调通过后再启用；与现网 `oa_travel` 互不影响。

---

## ⑤ 验收清单

在**测试环境**逐项勾选（真实 OA / 对方生产 API 联调需各自环境验证，勿将未测项记为通过）。

| # | 项 | 通过标准 |
|---|----|----------|
| 1 | 进程健康 | `/healthz`、`/readyz` 正常 |
| 2 | 上游配置 | 连接器总览中目标 HTTP 上游 `health: configured` |
| 3 | Tool 注册 | Tool 管理列表为「已注册」；停用后员工提问提示功能未开放 |
| 4 | Skill 可见 | 员工会话欢迎页出现新 Skill / 示例问题（或规则命中） |
| 5 | 身份与权限 | 员工 A 只能看到 A 的数据；篡改参数中的他人标识无效 |
| 6 | 信封正确 | 成功/无数据/业务 `msg` 展示符合 [使用说明 §4](user-guide.md#4-oa-对接说明给-oa-开发) 或 `raw_json` 预期 |
| 7 | 可观测 | **运行记录** 有时间线；Tool 事件 metadata 含 `connector_id` |
| 8 | Pack 门禁 | 禁用 Pack 后能力消失，启用后恢复 |
| 9 | 审计 | 启停 Pack、改 Tool/Skill、改连接配置均有审计记录 |
| 10 | 安全 | 生产环境 `demo_idp_enabled = false`；日志与审计无明文密钥 |

**自动化参考（非替代手工验收）：** `backend/tests/test_raw_json_mock_tool_m2.py`、`backend/tests/test_demo_no_oa_m4.py` 覆盖 `raw_json` 与 Demo IdP 执行链；路径说明见 [`packs/demo_http/README.md`](../../packs/demo_http/README.md)。

---

## 附录：与 OA 行程包并存

- 现网 **`oa_travel`** 默认启用，连接器为 `office`；新系统使用**新 upstream key + 新 Pack** 即可并行。
- 无 OA 的纯演示：可启用 Demo IdP + `demo_http` Pack，并自建 mock HTTP（见 demo README）；**不表示**已与真实 OA 完成联调。
