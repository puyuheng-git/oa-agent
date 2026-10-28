# Multi-System Platform M1 — Connector/Principal 抽象（行为不变）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在**不改变现网行程报销对话行为**的前提下，引入 `Principal` / `Connector` 抽象，让 `OfficeApiClient` 成为第一个 `HttpJsonConnector` 实现，会话与执行路径双写兼容 `oa`。

**Architecture:** 按规格 [`2026-10-28-multi-system-platform-design.md`](../specs/2026-10-28-multi-system-platform-design.md) M1：Core 仍走原调用链，但经 Connector 接口；Identity 增加 `principal_id`（默认等于 `oa`）；事件 metadata 增加 `connector_id`（默认 `office`）。不做 envelope 可配、不做 Pack 加载器、不做 OIDC（属 M2+）。

**Tech Stack:** Python 3.11+、现有 pytest/respx、FastAPI、`oa_agent.executor` / `integrations.office_api`。

## Global Constraints

- 硬约束：对 `td_oa` 零访问；模型不参与权限；密钥只写不读；管理写=权限+CSRF+Idempotency-Key+审计。  
- M1 **禁止**改变员工可见回复语义、Tool 路径、mint 协议。  
- `oa` 字段保留可读可写；`principal_id` 缺省 = `str(oa)`。  
- 回复与文档中文；代码标识符英文。  
- 每 Task 结束：相关 pytest 绿；用户未要求则不 `git commit`（或仅在用户明确要求时提交）。

## File map（M1）

| 路径 | 职责 |
|------|------|
| `backend/oa_agent/identity/principal.py` | `Principal` / `PrincipalClaims` 数据类 |
| `backend/oa_agent/connectors/base.py` | `Connector` Protocol、`ConnectorResult`、`ConnectorError` |
| `backend/oa_agent/connectors/http_json.py` | 包装/委托现有 `OfficeApiClient` 的 HTTP Connector |
| `backend/oa_agent/connectors/hub.py` | `connector_id → Connector` 注册表（先内存，由 `upstream_clients` 填充） |
| `backend/oa_agent/integrations/office_api.py` | 保留；实现或被 `HttpJsonConnector` 委托；`DEFAULT_UPSTREAM` 即默认 `connector_id` |
| `backend/oa_agent/executor/executor.py` | `Identity` 增 `principal_id`；执行走 hub/connector；事件带 `connector_id` |
| `backend/oa_agent/auth/chat_launch.py` | `ChatSession` 增 `principal_id`（默认=oa） |
| `backend/oa_agent/chat/service.py` | 构造 Identity 时填 `principal_id`；clients 经 hub |
| `backend/tests/test_connectors_m1.py` | 新测 |
| `backend/tests/test_principal_session.py` | 新测 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | 增补「平台 vs Connector」短节（M0/M1 文档） |
| `docs/STATUS.md` | 登记 M1 |

---

### Task 1: Principal 数据类 + 会话双写字段

**Files:**
- Create: `backend/oa_agent/identity/__init__.py`
- Create: `backend/oa_agent/identity/principal.py`
- Modify: `backend/oa_agent/auth/chat_launch.py`（`ChatSession`）
- Test: `backend/tests/test_principal_session.py`

**Interfaces:**
- Produces: `Principal(principal_id: str, display_name: str = "", external_keys: dict[str, str] | None = None)`；`ChatSession.principal_id: str`（创建时若未传则 `principal_id = oa`）

- [x] **Step 1: 写失败测试** — `test_chat_session_principal_id_defaults_to_oa`：构造 `ChatSession(oa="u1", ...)` 断言 `principal_id == "u1"`；显式传入 `principal_id="p1"` 时保持 `p1` 且 `oa` 仍可用。

- [x] **Step 2: 跑测确认失败**

```bash
cd backend && uv run pytest tests/test_principal_session.py -q
```

- [x] **Step 3: 实现 `Principal` 与 `ChatSession.principal_id`（含 launch redeem 序列化往返若有）**

- [x] **Step 4: 跑测通过；全量相关 auth/chat 冒烟**

```bash
cd backend && uv run pytest tests/test_principal_session.py tests/test_chat.py tests/test_auth.py -q
```

- [ ] **Step 5:（可选）用户要求时再 commit**

---

### Task 2: Connector Protocol + ConnectorResult

**Files:**
- Create: `backend/oa_agent/connectors/__init__.py`
- Create: `backend/oa_agent/connectors/base.py`
- Test: `backend/tests/test_connectors_m1.py`

**Interfaces:**
- Produces:
  - `ConnectorError(code, message, http_status=None, user_message="")`
  - `ConnectorResult(data, http_status, duration_ms, message="")`
  - `Protocol Connector`: `id: str`, `invoke(method, path, *, params=None, json_body=None, authorization=str, timeout=None, idempotency_key=None) -> ConnectorResult`
  - 映射：现有 `OfficeApiError` code 与 `ConnectorError` code 对齐（同名字符串）

- [x] **Step 1: 写失败测试** — 用简单 fake Connector 实现 Protocol，断言 `invoke` 返回 `ConnectorResult`。

- [x] **Step 2: 跑测失败 → 实现 base → 跑通**

```bash
cd backend && uv run pytest tests/test_connectors_m1.py -q
```

---

### Task 3: HttpJsonConnector 委托 OfficeApiClient

**Files:**
- Create: `backend/oa_agent/connectors/http_json.py`
- Modify: `backend/tests/test_connectors_m1.py`
- Keep: `backend/oa_agent/integrations/office_api.py`（行为不变）

**Interfaces:**
- Produces: `HttpJsonConnector(connector_id: str, client: OfficeApiClient)`；`invoke("GET", path, params=..., authorization=...)` 内部调 `client.get`；`POST` 调 `client.post`；将 `OfficeApiError` 转为 `ConnectorError`（或让执行器仍捕获 `OfficeApiError`——**推荐 Connector 边界统一转 ConnectorError，executor 同时兼容两者一期**）

- [x] **Step 1: respx/mock 测 GET 成功与业务码失败与现网 `OfficeApiClient` 一致**

- [x] **Step 2: 实现委托包装**

- [x] **Step 3: pytest 绿**

---

### Task 4: ConnectorHub 由 upstream_clients 填充

**Files:**
- Create: `backend/oa_agent/connectors/hub.py`
- Modify: `backend/oa_agent/chat/service.py`（`tool_clients` / 装配）
- Modify: `backend/oa_agent/integrations/office_api.py`（可选：`upstream_connectors(settings) -> ConnectorHub`）
- Test: `backend/tests/test_connectors_m1.py`

**Interfaces:**
- Produces: `ConnectorHub.get(connector_id) -> Connector | None`；`ConnectorHub.from_office_settings(oa_settings) -> ConnectorHub`（内部仍调 `upstream_clients`）
- Consumes: Task 3 `HttpJsonConnector`

- [x] **Step 1: 测试 hub 含默认 `office` key**

- [x] **Step 2: 实现；`tool_clients` 可继续返回 `dict[str, OfficeApiClient]` **同时** 提供 `tool_connectors(rt) -> ConnectorHub`（双轨，避免一次改爆）**

- [x] **Step 3: pytest 绿**

---

### Task 5: Identity 扩展 + ToolExecutor 经 Connector 调用

**Files:**
- Modify: `backend/oa_agent/executor/executor.py`
- Modify: `backend/oa_agent/chat/service.py`（`Identity(oa=..., authorization=..., principal_id=session.principal_id)`）
- Modify: `backend/oa_agent/executor/write_tools.py`（若写路径也用 clients，同样可走 hub 或保持 client 字典兼容）
- Test: `backend/tests/test_connectors_m1.py` + 现有 `test_chat.py` / `test_runtime.py` / `test_write_workflow.py`

**Interfaces:**
- `Identity` 增加 `principal_id: str`（默认 factory：若未传则 `principal_id = oa`）
- `ToolExecutor.__init__`：保留 `clients: dict[str, OfficeApiClient]` **或** 增加可选 `hub: ConnectorHub | None`；若 hub 存在则 `spec.upstream` 当作 `connector_id` 取 Connector 再 `invoke`
- `tool_call_start/end` metadata 增加 `"connector_id": spec.upstream or "office"`

- [x] **Step 1: 单测** — executor 使用 hub 调 fake connector，事件 metadata 含 `connector_id`

- [x] **Step 2: 最小改动接通；无 hub 时回退 `clients`（行为与今日一致）**

- [x] **Step 3:**

```bash
cd backend && uv run pytest tests/test_connectors_m1.py tests/test_chat.py tests/test_runtime.py tests/test_write_workflow.py tests/test_catalog.py -q
```

---

### Task 6: 回归全量 + 文档

**Files:**
- Modify: `docs/design/2026-10-09-oa-langgraph-design.md`（短节：Principal/Connector；OA 为默认实现）
- Modify: `docs/STATUS.md`（M1 状态）
- Create: `docs/delivery/2026-10-28-multi-system-m1-delivery.md`（实施完成后填）

- [x] **Step 1:**

```bash
cd backend && uv run pytest -q
```

- [x] **Step 2: 修复偶发破坏（编码/导入环）**

- [x] **Step 3: 写交付说明：功能/文件/测试结果（区分自动化通过 vs 未执行手工）/未完成（M2）**

- [x] **Step 4: 更新 STATUS.md**

- [ ] **Step 5: 用户要求时再 commit**

---

## M1 明确不做

- envelope_profile / identity_bindings 可配（M2）  
- Domain Pack 目录加载（M3）  
- IdP 插件化 / OIDC（M4）  
- 管理端连接器 UI 重做（M5）  
- 重命名包名 `oa_agent`（可后置，避免 M1 爆炸）

## 验收口令

1. 全量 `pytest` 绿。  
2. 行程 list/detail 路径与身份注入行为与改前一致（自动化覆盖）。  
3. 代码中可 `from oa_agent.connectors import ConnectorHub` 且默认 office 可 invoke。  
4. Run 事件 metadata 可见 `connector_id`（有 tool_call 的测试断言）。  

完成后停下，等用户确认再开 **M2** 计划。
