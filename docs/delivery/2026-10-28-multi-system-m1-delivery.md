# 交付说明：多系统平台 M1 — Principal / Connector（行为兼容）

**日期：** 2026-10-28  
**规格：** `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`（M1）  
**计划：** `docs/superpowers/plans/2026-10-28-multi-system-m1-connectors.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md` §3.1  

---

## 1. 功能

1. 引入 **`Principal`** 与会话 / `Identity` 双写字段 **`principal_id`**（缺省 = `oa`）；员工可见对话语义与 Tool 路径不变。  
2. 引入 **`Connector` Protocol**、`ConnectorResult` / `ConnectorError`；现网 office 上游经 **`HttpJsonConnector`** 委托既有 `OfficeApiClient`。  
3. **`ConnectorHub`** 由 `upstream_clients` / OA 配置装配；`tool_clients` 与 `tool_connectors` 双轨并存。  
4. **`ToolExecutor`** 优先经 hub `invoke`，否则回退 `clients`；`tool_call` 事件 metadata 增加 `connector_id`（默认 `office`）。  
5. **无新对外 HTTP API**；mint / 会话 / 管理端契约保持兼容。

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/oa_agent/identity/__init__.py` | 包导出 |
| `backend/oa_agent/identity/principal.py` | `Principal` 数据类 |
| `backend/oa_agent/connectors/__init__.py` | 包导出 |
| `backend/oa_agent/connectors/base.py` | Protocol / Result / Error |
| `backend/oa_agent/connectors/http_json.py` | 委托 `OfficeApiClient` |
| `backend/oa_agent/connectors/hub.py` | `ConnectorHub` |
| `backend/oa_agent/integrations/office_api.py` | `upstream_connectors` 辅助 |
| `backend/oa_agent/auth/chat_launch.py` | `ChatSession.principal_id` |
| `backend/oa_agent/executor/executor.py` | `Identity.principal_id`；hub 调用路径 |
| `backend/oa_agent/chat/service.py` | 装配 hub；构造 Identity |
| `backend/tests/test_connectors_m1.py` | Connector / hub / executor 单测 |
| `backend/tests/test_principal_session.py` | 会话 principal 双写 |
| `backend/tests/test_outbound_mcp.py` | write context 兼容 hub stub |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §3.1 增补 |
| `docs/STATUS.md` | M1 状态 |
| `docs/delivery/2026-10-28-multi-system-m1-delivery.md` | 本文 |

无 Alembic 迁移；无对外 API 变更。

---

## 3. 迁移说明

无。部署后行为与改前一致；新字段仅内部双写。

---

## 4. API 说明

**无新对外 API。** 既有 `/v1/chat/*`、launch redeem、管理端上游配置路径不变；`oa` 仍可读可写，`principal_id` 仅服务端会话 / 执行层使用。

---

## 5. 权限与安全

- 硬约束不变：对 `td_oa` 零访问；业务数据只来自已配置上游 + 员工 Authorization；模型/客户端自报 `oa` 仍丢弃。  
- `principal_id` 不得由客户端覆盖为越权身份；缺省跟随会话 `oa`。  
- Connector 错误码与 `OfficeApiError` 同名对齐；密钥仍只写不读，日志/审计不含明文。  
- 管理写操作链路未因 M1 放宽。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `cd backend && uv run pytest -q` 全量 | **自动化通过**（485 passed，1 skipped，0 failed；Task 6 回归） |
| `tests/test_connectors_m1.py` / `tests/test_principal_session.py` | **自动化通过** |
| 真实 office-api / OA 宿主页行程 list·detail 手工联调 | **手工未执行** |
| 真实 LLM / 企微 | **外部依赖未验证** |

---

## 7. 未完成项（M2+）

- M2：envelope_profile / identity_bindings 可配  
- M3：Domain Pack 目录加载  
- M4：IdP 插件化 / OIDC  
- M5：管理端连接器 UI  
- 包名 `oa_agent` 重命名（后置）

---

## 8. 下一阶段建议

确认本交付后开 **M2** 计划；并行可继续 STATUS 中 X2 embedding、X3 调用过程手工验收等。
