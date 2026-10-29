# 交付说明：多系统平台 M2 — 信封可配 / 身份绑定 / 多凭证 / raw_json 验收

**日期：** 2026-10-28  
**规格：** `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`（M2）  
**计划：** `docs/superpowers/plans/2026-10-28-multi-system-m2-envelope.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md` §3.1  
**前置：** M1 已交付（`docs/delivery/2026-10-28-multi-system-m1-delivery.md`）

---

## 1. 功能

1. **`EnvelopeProfile`**：按名称解析上游响应；内置 `oa_office`（现网 `{code,msg,data}` + success_codes，错误码与 `OfficeApiError` 对齐）与 `raw_json`（HTTP 2xx 整段 JSON 为 data；4xx/5xx → `UPSTREAM_HTTP_ERROR`）。  
2. **`HttpJsonConnector`**：构造参数 `envelope_profile`（默认 `oa_office`）；`oa_office` + `OfficeApiClient` 仍委托现网客户端；其它 profile 自管 httpx + `parse_envelope`。  
3. **`identity_bindings`**：ToolSpec / catalog 支持 `[{param, from}]`；旧 `inject_identity_fields: [oa]` 运行时合成等价绑定；模型 args 含绑定目标参数名则丢弃。  
4. **Session 多 connector 凭证表**：`ChatSession.credentials[connector_id] → {authorization, expires_at}`；`office_token` 与 `credentials["office"]` 双写兼容；按 `connector_id` 取票，**禁止**把 office 票默发到未声明信任的独立 connector（如 demo）。  
5. **OA upstreams 信任域**：经 `OfficeApiClient` 委托装配的 peer（`shares_employee_token`）可回落 mint 员工票，现网多 upstream 同票行为不回退；执行前先校验上游是否配置，缺配置仍报 `UPSTREAM_NOT_CONFIGURED`。  
6. **验收**：respx mock 非 OA API + `raw_json` 只读 Tool 端到端通过；`tool_call` metadata 含 `connector_id`。

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/oa_agent/connectors/envelope.py` | `parse_envelope` / `get_profile` |
| `backend/oa_agent/connectors/profiles/__init__.py` | profile 包 |
| `backend/oa_agent/connectors/profiles/oa_office.py` | 现网信封 |
| `backend/oa_agent/connectors/profiles/raw_json.py` | 无业务 code 信封 |
| `backend/oa_agent/connectors/http_json.py` | profile 注入；`shares_employee_token` |
| `backend/oa_agent/executor/registry.py` | ToolSpec：`identity_bindings` / `envelope_profile` |
| `backend/oa_agent/executor/catalog.py` | 解析/兼容 inject → bindings |
| `backend/oa_agent/executor/executor.py` | 绑定注入；按 connector 选票；上游先于凭证校验 |
| `backend/oa_agent/executor/write_tools.py` | 写路径信任域回落 |
| `backend/oa_agent/auth/chat_launch.py` | `ChatSession.credentials` + office 双写 |
| `backend/oa_agent/chat/service.py` | Identity 带 credentials；缺票错误 |
| `backend/tests/test_envelope_m2.py` | envelope 单测 |
| `backend/tests/test_identity_bindings_m2.py` | 绑定与禁止模型覆盖 |
| `backend/tests/test_session_credentials_m2.py` | 多凭证 / 跨票拒绝 |
| `backend/tests/test_raw_json_mock_tool_m2.py` | raw_json + mock 非 OA 端到端 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §3.1 增补 |
| `docs/STATUS.md` | M2 状态 |
| `docs/delivery/2026-10-28-multi-system-m2-delivery.md` | 本文 |
| `docs/superpowers/plans/2026-10-28-multi-system-m2-envelope.md` | 计划勾选 |

无 Alembic 迁移；无强制对外 API 变更。

---

## 3. 迁移说明

无库表迁移。部署后：

- 未声明 `envelope_profile` 的 Tool / Connector **默认 `oa_office`**，行程相关行为与 M1 一致。  
- 未声明 `identity_bindings` 时仍按 `inject_identity_fields` 注入。  
- 旧会话 ticket 仅含 `office_token` 时，加载后自动填入 `credentials["office"]`。  
- OA「业务上游」目录内 peer 继续共享员工 token；独立 connector（非委托 OfficeApiClient）须在会话 `credentials` 中显式放票。

---

## 4. API 说明

**无新对外 HTTP API。** 既有 `/v1/chat/*`、launch redeem、管理端 Tool/上游配置路径不变。

内部契约扩展（执行层 / schema，非浏览器新路由）：

- Tool schema 可选：`identity_bindings`、`envelope_profile`（catalog 规范化；inject 合成不写入哈希以免现网漂移）。  
- 错误码：`CONNECTOR_CREDENTIAL_MISSING`（会话缺该 connector 凭证）；既有 `UPSTREAM_NOT_CONFIGURED` / `UPSTREAM_*` / `OFFICE_TOKEN_EXPIRED` 保持。

---

## 5. 权限与安全

- 硬约束不变：对 `td_oa` 零访问；业务数据只来自已配置上游 + 员工 Authorization；模型/客户端自报身份字段仍丢弃。  
- `identity_bindings` 目标参数名不得由模型写入；绑定值只由服务端 Identity 解析。  
- 多凭证：禁止跨信任域默认同票；OA upstreams 信任域（`shares_employee_token`）显式允许回落 office 票。  
- 密钥仍只写不读；日志/审计不含明文 Authorization。  
- 管理写操作链路未因 M2 放宽。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `cd backend && uv run pytest -q` 全量 | **自动化通过**（**518 passed，1 skipped，0 failed**） |
| `tests/test_envelope_m2.py` / `test_identity_bindings_m2.py` / `test_session_credentials_m2.py` / `test_raw_json_mock_tool_m2.py` | **自动化通过** |
| `tests/test_connectors_m1.py`、行程 / upstreams 相关回归 | **自动化通过** |
| 真实 office-api / OA 宿主页行程 list·detail 手工联调 | **手工未执行** |
| 真实非 OA 上游 + raw_json 生产配置 | **外部依赖未验证** |
| 真实 LLM / 企微 | **外部依赖未验证** |

**Task 7 回归摘要：** 全量 pytest exit code 0；**518 passed / 1 skipped / 0 failed**。skipped 为既有用例，与 M2 无关。Task 7 修复点：`validate_args` 对无 `identity_bindings` 的测试桩用 `getattr`；执行路径先判 `UPSTREAM_NOT_CONFIGURED` 再取凭证；OA peer `shares_employee_token` 回落 office 票。

---

## 7. 未完成项（M3+）

- **M3**：Domain Pack 目录加载 / 禁用 pack  
- **M4**：IdP 插件化 / OIDC（规格仅骨架）  
- **M5**：管理端连接器 UI 重做  
- embedding 路由、写 Workflow 真 OA 联调  
- 包名 `oa_agent` 重命名（后置）  
- Connector 级自定义 JMESPath / `json_api` profile（规格提及，M2 未做）

---

## 8. 下一阶段建议

确认本交付后开 **M3**（Domain Pack）；并行可继续 STATUS 中 X2 embedding、X3 调用过程手工验收等。
