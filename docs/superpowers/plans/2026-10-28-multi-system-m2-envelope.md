# Multi-System Platform M2 — 信封可配 / 身份绑定 / 非 OA mock 验收

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 HTTP Connector 的响应信封与身份注入可配置，并用 **raw_json + mock 非 OA API** 跑通只读 Tool，证明平台可脱离 office `{code,msg,data}` 独立工作。

**Architecture:** 基于 M1 的 `HttpJsonConnector` / `ConnectorHub` / `Identity`：抽出 `EnvelopeProfile` 解析器；ToolSpec（或 connector 配置）声明 `envelope_profile` 与 `identity_bindings`；Session 支持多 connector 凭证表（KV）。现网 `oa_office` profile 行为与今日一致。不做 Pack 加载器（M3）、不做 IdP 插件化（M4）。

**Tech Stack:** Python 3.11+、pytest、respx、现有 `oa_agent.connectors` / `executor` / `chat_launch`。

**规格：** [`docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`](../specs/2026-10-28-multi-system-platform-design.md) §4 / §9 M2  
**前置：** M1 已交付（`docs/delivery/2026-10-28-multi-system-m1-delivery.md`）

## Global Constraints

- 硬约束：对 `td_oa` 零访问；模型不参与权限；密钥只写不读；管理写=权限+CSRF+Idempotency-Key+审计。  
- **现网行程 Tool**（`oa_office` 信封 + `inject_identity_fields=[oa]`）行为不得回退。  
- `identity_bindings` / 注入字段仍只由服务端填充；模型参数名不得包含身份绑定目标。  
- 多凭证：禁止把 A connector 的票默发到未声明信任的 B（M2 至少：按 `connector_id` 取票；跨票拒绝并记事件）。  
- 中文文档；英文标识符。用户未要求则每个 Task 可不单独 commit；整阶段结束再统一提交。

## File map（M2）

| 路径 | 职责 |
|------|------|
| `backend/oa_agent/connectors/envelope.py` | `EnvelopeProfile` 名 → 解析成功/失败/提示语 |
| `backend/oa_agent/connectors/http_json.py` | 可注入 profile；或拆「传输」与「unwrap」 |
| `backend/oa_agent/connectors/profiles/oa_office.py` | 现网 `{code,msg,data}` + success_codes（从 OfficeApiClient._unwrap 抽出或委托） |
| `backend/oa_agent/connectors/profiles/raw_json.py` | HTTP 2xx 即成功，body 整段为 data；无业务 code |
| `backend/oa_agent/executor/registry.py` / catalog | Tool schema 支持 `envelope_profile`、`identity_bindings`；兼容旧 `inject_identity_fields` |
| `backend/oa_agent/executor/executor.py` | `build_request` 按 bindings 注入；执行用 profile |
| `backend/oa_agent/auth/chat_launch.py` / `chat/service.py` | Session `credentials: dict[connector_id, {authorization, expires_at}]`；默认 `office` ← 现 `office_token` |
| `backend/tests/test_envelope_m2.py` | profile 单测 |
| `backend/tests/test_identity_bindings_m2.py` | 绑定与禁止模型覆盖 |
| `backend/tests/test_raw_json_mock_tool_m2.py` | respx mock 非 OA + raw_json Tool 端到端 |
| `docs/delivery/2026-10-28-multi-system-m2-delivery.md` | 交付说明 |
| `docs/STATUS.md` | 更新 M2 |

---

### Task 1: EnvelopeProfile 抽象 + oa_office 等价现网

**Files:**
- Create: `backend/oa_agent/connectors/envelope.py`
- Create: `backend/oa_agent/connectors/profiles/__init__.py`
- Create: `backend/oa_agent/connectors/profiles/oa_office.py`
- Test: `backend/tests/test_envelope_m2.py`

**Interfaces:**
- `parse_envelope(profile: str, status_code: int, body: object, *, success_codes: set[str], hint_max: int) -> tuple[object, str]` 成功返回 (data, hint)；失败抛 `ConnectorError`
- Profiles: `oa_office`（对齐今日 `_unwrap`）、注册表 `get_profile(name)`

- [x] **Step 1: 写失败测试** — 同一 JSON 用 oa_office：成功码取 data；错误码 `UPSTREAM_BIZ_ERROR`；401→`OFFICE_TOKEN_EXPIRED`（或统一为 `UPSTREAM_AUTH` 但 **M2 保持与 OfficeApiError 同名 code** 以免破坏文案映射）

- [x] **Step 2: 实现 oa_office（可从 OfficeApiClient 抽逻辑，client 改调 profile 或保持委托二选一：优先抽共享函数避免双份）**

- [x] **Step 3:** `uv run pytest tests/test_envelope_m2.py -q`

---

### Task 2: raw_json profile

**Files:**
- Create: `backend/oa_agent/connectors/profiles/raw_json.py`
- Modify: `backend/tests/test_envelope_m2.py`

**Interfaces:**
- HTTP status &lt; 400：data = 解析后的 JSON（或 raw text 策略：仅 JSON）；hint=""  
- 4xx/5xx：`UPSTREAM_HTTP_ERROR`（4xx 可带清洗后的 body 片段作 user_message，5xx 不展示堆栈）

- [x] **Step 1–3: TDD + pytest 绿**

---

### Task 3: HttpJsonConnector 使用 profile（默认 oa_office）

**Files:**
- Modify: `backend/oa_agent/connectors/http_json.py`
- Modify: `backend/oa_agent/integrations/office_api.py`（若抽共享 unwrap，保持对外行为）
- Test: 扩展 `tests/test_connectors_m1.py` 或 `test_envelope_m2.py` — 默认 profile 下与改前 GET 业务错误一致

- [x] **Step 1: Connector 构造增加 `envelope_profile: str = "oa_office"`、`success_codes`**
- [x] **Step 2: invoke 在拿到 httpx 响应后走 profile（若仍委托 OfficeApiClient.get，则需让 Client 可切换 profile，或 Connector 自己发 HTTP——推荐：**Connector 自管 httpx、profile 解析**，OfficeApiClient 薄封装调同一底层，避免分叉。若改动过大，M2 允许：OfficeApiClient 仍 oa_office；HttpJsonConnector(raw_json) 走独立 httpx 路径。**）**
- [x] **Step 3: pytest connectors + envelope 绿**

---

### Task 4: identity_bindings（兼容 inject_identity_fields）

**Files:**
- Modify: `backend/oa_agent/executor/registry.py`（ToolSpec 字段）
- Modify: `backend/oa_agent/executor/catalog.py`（解析/兼容：旧 `inject_identity_fields: [oa]` ⇒ bindings `[{param: oa, from: principal.external_key.oa | principal_id}]`）
- Modify: `backend/oa_agent/executor/executor.py` — `build_request` / validate 丢弃绑定目标参数名
- Test: `backend/tests/test_identity_bindings_m2.py`

**Interfaces:**
- `identity_bindings: list[{param: str, from: str}]`  
  - `from` 允许：`principal_id`、`principal.external_keys.<key>`、`credential.authorization`（一般不注入 query）、现网等价：`oa` ← `identity.oa` / `principal_id`
- 模型 args 含绑定 param → 丢弃并记 dropped

- [x] **Step 1: 单测旧 inject 与新 bindings 注入结果一致**
- [x] **Step 2: 实现**
- [x] **Step 3: catalog / chat 相关测不破**

---

### Task 5: Session 多 connector 凭证表

**Files:**
- Modify: `backend/oa_agent/auth/chat_launch.py` — `credentials: dict` 默认；序列化兼容旧 ticket（仅 office_token → `credentials["office"]`）
- Modify: `backend/oa_agent/chat/service.py` — `Identity.authorization` 取自 `credentials[connector_id]`；缺票 → 清晰错误
- Test: `backend/tests/test_principal_session.py` 或新 `test_session_credentials_m2.py`

**Interfaces:**
- `ChatSession.credentials: dict[str, dict]` 形如 `{ "office": {"authorization": "...", "expires_at": int} }`  
- 属性兼容：`office_token` property 读写映射到 `credentials["office"]`（减少调用点爆炸）或双写字段一期并存

- [x] **Step 1–3: TDD；launch/redeem/refresh 冒烟 `tests/test_chat.py tests/test_auth.py`**

---

### Task 6: 验收 — raw_json mock 非 OA 只读 Tool

**Files:**
- Create: `backend/tests/test_raw_json_mock_tool_m2.py`（respx mock `https://mock.example/api/items`）
- 测试内注册临时 ToolSpec：`upstream/connector_id=demo`、`envelope_profile=raw_json`、无 oa 注入或绑定 demo_user
- Hub 含 `HttpJsonConnector("demo", ...)` 指向 mock base_url

**验收断言：**
1. execute 成功返回白名单字段  
2. 不经过 office success_codes  
3. 事件 metadata `connector_id=demo`

- [x] **Step 1: 写测 → 红**
- [x] **Step 2: 补齐装配缺口 → 绿**
- [x] **Step 3:** `uv run pytest tests/test_raw_json_mock_tool_m2.py tests/test_envelope_m2.py tests/test_identity_bindings_m2.py tests/test_connectors_m1.py -q`

---

### Task 7: 全量回归 + 文档

- [x] **Step 1:** `cd backend && uv run pytest -q`
- [x] **Step 2: 写 `docs/delivery/2026-10-28-multi-system-m2-delivery.md`**
- [x] **Step 3: 更新 STATUS；权威设计 §3.1 补 envelope/bindings 一句**
- [ ] **Step 4: 用户要求时再 commit / push**

---

## M2 明确不做

- Domain Pack 目录 / 禁用 pack（M3）  
- IdP 插件 / OIDC（M4）  
- 管理端连接器 UI 重做（M5）  
- embedding 路由、写 Workflow 真 OA 联调  

## 验收口令

1. 全量 pytest 绿；行程相关测不失败。  
2. `raw_json` + mock 非 OA Tool 单测绿。  
3. 旧 Tool 无 `envelope_profile` 时默认 `oa_office`。  
4. 文档标明手工/外部依赖未验证项。  

完成后停下等用户确认再开 **M3**。
