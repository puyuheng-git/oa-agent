# Multi-System Platform M4 — IdP 插件化（OA / 企微适配 + OIDC 骨架 + demo 无 OA 可聊）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将「证明对话者是谁」从 `chat_launch` / 企微 mint 硬编码抽成 **Identity Provider 适配器**；现网 OA assertion + 企微行为不变；提供 **demo IdP + demo pack** 在无 OA/office 时也能建立 Session 并走 raw_json Tool；**OIDC 仅骨架**（规格锁定）。

**Architecture:** `identity/` 增加 `IdP` Protocol 与 `IdentityBroker`：入站 assertion/code → `PrincipalClaims` → 创建/刷新 `ChatSession` + 按需 `Connector.ensure_credential`。OA / WeCom 为两个正式适配器（委托现有逻辑）；`demo` 适配器签发本地 principal + 静态/mock bearer。渠道（iframe/企微）只调 Broker，不直调 office mint。

**Tech Stack:** Python 3.11+、pytest、现有 `auth/chat_launch.py`、`channels/wecom.py`、`packs/`、`connectors/`。

**规格：** [`docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`](../specs/2026-10-28-multi-system-platform-design.md) §3 / §9 M4  
**前置：** M1–M3 已交付。  
**评审锁定：** OIDC **仅骨架**；Pack 仍本机目录。

## Global Constraints

- 硬约束：对 `td_oa` 零访问；模型不参与权限；密钥只写不读；管理写=权限+CSRF+Idempotency+审计。  
- **不得改变**现网 OA iframe launch / 企微 mint 的外部协议与员工可见错误文案（除明确兼容增强）。  
- 浏览器仍只持平台 ticket；下游 token 只在服务端 credentials。  
- demo 模式默认关闭（配置/环境开关）；生产勿默认开启。  
- 中文文档；英文标识符。用户未要求不强制每 Task commit。

## File map（M4）

| 路径 | 职责 |
|------|------|
| `backend/oa_agent/identity/claims.py` | `PrincipalClaims` 数据类 |
| `backend/oa_agent/identity/idp.py` | `IdP` Protocol：`id`, `verify(...) -> PrincipalClaims` |
| `backend/oa_agent/identity/broker.py` | `IdentityBroker.create_session` / refresh credentials |
| `backend/oa_agent/identity/adapters/oa_assertion.py` | 包装现有 assertion 校验 |
| `backend/oa_agent/identity/adapters/wecom.py` | 包装企微 userid → mint |
| `backend/oa_agent/identity/adapters/demo.py` | 本地 demo 主体 |
| `backend/oa_agent/identity/adapters/oidc.py` | **骨架**：接口 + NotImplemented/配置缺省错误 |
| `backend/oa_agent/auth/chat_launch.py` | 薄委托 Broker（shim 保测） |
| `backend/oa_agent/channels/wecom.py` | 经 Broker / wecom IdP |
| `packs/demo_http/` | 最小 pack + raw_json tool 声明（可引用 fixtures） |
| `backend/tests/test_idp_m4.py` | 适配器与 Broker |
| `backend/tests/test_demo_no_oa_m4.py` | 无 office 配置下 demo 会话 + tool（respx） |
| `docs/delivery/2026-10-29-multi-system-m4-delivery.md` | 交付 |
| `docs/STATUS.md` | 更新 |

---

### Task 1: PrincipalClaims + IdP Protocol

**Files:**
- Create: `backend/oa_agent/identity/claims.py`
- Create: `backend/oa_agent/identity/idp.py`
- Modify: `backend/oa_agent/identity/__init__.py`
- Test: `backend/tests/test_idp_m4.py`

**Interfaces:**
- `PrincipalClaims(principal_id: str, display_name: str = "", external_keys: dict[str, str] | None = None, channel: str = "", raw: dict | None = None)`
- `Protocol IdP`: `id: str`; `verify(payload: dict, *, ctx: IdPContext) -> PrincipalClaims`  
  - `IdPContext` 可含 kv、secrets getter、now、clock skew  
- 失败抛现有 `AppError` 或统一 `IdPError` 再映射（优先复用 AppError 以少改路由）

- [ ] **Step 1: 写 FakeIdP 测 Protocol**
- [ ] **Step 2: 实现**
- [ ] **Step 3:** `uv run pytest tests/test_idp_m4.py -q`

---

### Task 2: OA assertion 适配器（行为对齐 chat_launch.verify）

**Files:**
- Create: `backend/oa_agent/identity/adapters/__init__.py`
- Create: `backend/oa_agent/identity/adapters/oa_assertion.py`
- Modify: `chat_launch.verify_assertion` 可委托适配器，或适配器调用现有 verify 再映射 Claims（**推荐适配器调现有函数**，零行为漂移）
- Test: 复用/扩展 assertion 测；`test_idp_m4.py` 断言 claims.principal_id == oa

- [ ] **Step 1–3: TDD；`tests/test_auth.py` 仍绿**

---

### Task 3: WeCom 适配器

**Files:**
- Create: `backend/oa_agent/identity/adapters/wecom.py`
- 输入：`wework_user_id` + gateway；输出 Claims（oa 来自 mint 结果）  
- 委托现有 `OfficeApiClient.mint_by_wework`  
- wecom channel 路径改为经适配器/Broker（最小改动：提函数供 channel 调用）

- [ ] **Step 1–3:** `uv run pytest tests/test_wecom.py tests/test_idp_m4.py -q`（按现有 wecom 测文件名调整）

---

### Task 4: IdentityBroker — Session + credentials

**Files:**
- Create: `backend/oa_agent/identity/broker.py`
- Modify: `chat_launch.create_launch` / `redeem` / refresh 走 Broker 或并行 shim

**Interfaces:**
- `Broker.create_from_idp(idp_id, payload, *, channel) -> launch_code or ChatSession`  
- `ensure_connector_credentials(session, connector_ids: list[str])` — OA pack 依赖 office：调 mint；demo：写入静态 token  
- Session 继续双写 `oa` / `principal_id` / `credentials`

- [ ] **Step 1: 测 Broker + oa IdP 产生与现网同构 session 字段**
- [ ] **Step 2: 实现**
- [ ] **Step 3:** `tests/test_chat.py tests/test_auth.py` 绿

---

### Task 5: demo IdP + packs/demo_http

**Files:**
- Create: `backend/oa_agent/identity/adapters/demo.py`
- Create: `packs/demo_http/pack.yaml` + `rules/intent.yaml`（可空规则）+ 可选 tools 指向测试 openapi 片段或仅运行时注册
- Config: `runtime.demo_idp_enabled` bool default False；或 settings group `idp.demo_enabled`
- Test: `test_demo_no_oa_m4.py` — 开启 demo 后：verify demo payload → session；Hub 仅 demo connector + raw_json respx Tool execute 成功；**不配置 office_api_base_url**

**demo verify 约定（测试用）：**
```json
{"principal_id": "demo_user", "display_name": "Demo", "secret": "<from settings>"}
```
HMAC 或共享口令二选一；简单口令即可（仅本地）。

- [ ] **Step 1–3: 无 OA 依赖的端到端测绿**

---

### Task 6: OIDC 骨架

**Files:**
- Create: `backend/oa_agent/identity/adapters/oidc.py`
- `verify` → `AppError(501, "IDP_NOT_IMPLEMENTED", "OIDC 适配器尚未实现")` 或配置缺失 503  
- 注册到 IdP registry 但默认不启用  
- Test: 调用即得到明确错误码（非 500 堆栈）

- [ ] **Step 1–3: pytest 绿**

---

### Task 7: 渠道路由配置 + 全量回归 + 文档

**Files:**
- settings：`idp.default_for_channel` 可选 map：`oa_web -> oa_assertion`, `wecom -> wecom`, `demo -> demo`
- Docs: delivery + STATUS（M4 已交付；下一刀 M5）  
- 权威设计 §6 身份增补「IdP 适配器」一句  
- Plan checkboxes

- [ ] **Step 1:** `cd backend && uv run pytest -q`
- [ ] **Step 2: 交付说明（手工/外部依赖未验证分列）**
- [ ] **Step 3: 用户要求时再 commit/push**

---

## M4 明确不做

- 完整 OIDC 授权码/联调（仅骨架）  
- 管理端连接器/包 UI 产品化（M5）  
- 去掉 `oa` 字段或重命名 `oa_agent` 包  
- 真 OA / 真企微手工联调（交付标未执行）

## 验收口令

1. 现网 assertion + 企微相关自动化测通过。  
2. `demo_idp_enabled` + demo pack：无 office 配置下 Session + raw_json Tool 测通过。  
3. OIDC 适配器返回明确未实现错误。  
4. 全量 pytest 绿。  

完成后停下，等用户确认再开 **M5**。
