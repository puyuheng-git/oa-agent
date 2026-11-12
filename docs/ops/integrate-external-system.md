# 新系统接入手册

面向管理员与对接开发：把**已有稳定 HTTP JSON API** 的业务系统接到 Agent 平台（只读查询为主；写操作仍走固定 Workflow + 员工确认，本手册不展开写路径）。

**验收口径：** 有稳定 HTTP JSON API 时，按手册可在一个工作日内完成 Agent 侧接入（不含对方改接口）。

**前提（硬约束）：**

- Agent 与业务系统只走 HTTP；不得直连 OA 业务库 `td_oa`。
- 业务数据只来自已配置上游、且以**该员工会话凭证**调用返回的结果；模型或客户端自报的 `oa` / 身份字段一律丢弃。
- Tool 只存**上游标识 + 相对路径**，不得写完整 URL；多个上游须属于**同一信任域**（认同同一员工 Authorization），或各自独立换票（禁止默认同票跨域）。
- 密钥只写不读；管理写操作须权限 + CSRF + `Idempotency-Key` + 审计。

权威设计：`docs/design/2026-10-09-oa-langgraph-design.md`。

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

## ② 注册能力：Tool / Skill

1. **Tool 管理** → 新建 Tool：选 **业务上游** = ① 中的 `key`；**接口路径** = 相对路径；方法仅 **GET**。
2. 配置参数白名单、返回字段、身份注入（见 [使用说明 §3.3](user-guide.md#33-tool-管理)）。也可 **从文件导入** OpenAPI / catalog。
3. **Skill 管理** → 新建 Skill：说明、填参指引、示例问题，并勾选上一步 Tool。
4. 员工重新打开助手即可在欢迎页看到新 Skill（须已配置 LLM 或存在匹配的规则意图）。

---

## ③ 选择身份提供者（IdP）

| IdP | 渠道 | 配置位置 | 典型场景 |
|-----|------|----------|----------|
| `oa_assertion` | OA Web / iframe | OA 对接：assertion HMAC；宿主页 `POST /v1/chat/launch` 后 302 到独立对话站点。嵌入白名单在该站点的 `frame-ancestors` | 生产员工从 OA 进入 |
| `wecom` | 企业微信单聊 | 连接配置 → 企业微信 BotID/Secret；OA 签发入口支持 `wework_user_id` mint | 生产移动办公 |
| `demo` | `demo` | 连接配置 → **IdP** 组：`demo_idp_enabled`、`demo_shared_secret` | **仅本机/演示**；默认关闭，生产勿开 |

- 渠道路由约定（代码默认）：`oa_web → oa_assertion`，`wecom → wecom`，`demo → demo`。
- Demo 会话不 mint office token；`credentials["demo"]` 由 Demo IdP 写入（默认 `Bearer demo-token`），供 `raw_json` 等非 OA 上游使用。详见 [Demo IdP 说明](demo-idp.md)。
- OIDC 适配器仅为骨架（`501 IDP_NOT_IMPLEMENTED`），勿用于生产。

---

## ④ 验收清单

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
| 8 | 审计 | 改 Tool/Skill、改连接配置均有审计记录 |
| 9 | 安全 | 生产环境 `demo_idp_enabled = false`；日志与审计无明文密钥 |

**自动化参考（非替代手工验收）：** `backend/tests/test_raw_json_mock_tool_m2.py`、`backend/tests/test_demo_no_oa_m4.py` 覆盖 `raw_json` 与 Demo IdP 执行链。
