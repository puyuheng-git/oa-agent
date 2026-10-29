# 交付说明：多系统平台 M4 — IdP 插件化（OA / 企微 / demo + OIDC 骨架）

**日期：** 2026-10-29  
**规格：** `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`（M4）  
**计划：** `docs/superpowers/plans/2026-10-29-multi-system-m4-idp.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md` §3.1 / §6  
**前置：** M1–M3 已交付

---

## 1. 功能

1. **IdP Protocol + PrincipalClaims**：`identity/idp.py`、`claims.py`；失败优先复用 `AppError` / `OfficeApiError`。  
2. **正式适配器**：`oa_assertion`（委托现有 assertion 校验）、`wecom`（委托 `mint_by_wework`）、`demo`（共享口令，默认关）。  
3. **OIDC 骨架**：`OidcIdP.verify` → `501 IDP_NOT_IMPLEMENTED`（非 500 堆栈）。  
4. **IdentityBroker**：`verify` → `session_from_claims`（双写 `oa` / `principal_id` / `credentials`）；`ensure_office_credentials`；默认 registry。  
5. **现网 shim**：`chat_launch` 行为不变；企微 `wecom_session` mint 路径经 **`WeComIdP.verify`** 再落会话（外部协议与员工可见文案不变）。  
6. **demo 无 OA**：settings `idp.demo_idp_enabled`（默认 False）+ `demo_shared_secret`；`packs/demo_http`；无 office 配置下 Session + raw_json Tool 自动化测通过。  
7. **渠道路由 map**：配置字段 `idp.channel_idp_map` / `default_for_channel` **未加**（FieldDef 尚无 `dict` kind）；约定默认 `oa_web→oa_assertion`、`wecom→wecom`、`demo→demo`，留待 schema 支持后再配置化。

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/oa_agent/identity/claims.py` | `PrincipalClaims` |
| `backend/oa_agent/identity/idp.py` | `IdP` Protocol / `IdPContext` |
| `backend/oa_agent/identity/broker.py` | `IdentityBroker` + 默认 registry |
| `backend/oa_agent/identity/adapters/oa_assertion.py` | OA assertion IdP |
| `backend/oa_agent/identity/adapters/wecom.py` | 企微 IdP |
| `backend/oa_agent/identity/adapters/demo.py` | Demo IdP |
| `backend/oa_agent/identity/adapters/oidc.py` | OIDC 骨架 |
| `backend/oa_agent/channels/wecom.py` | mint 经 WeComIdP |
| `backend/oa_agent/config/schema.py` | settings 组 `idp` |
| `packs/demo_http/` | 最小 demo pack |
| `backend/tests/test_idp_m4.py` | 适配器与 Broker |
| `backend/tests/test_demo_no_oa_m4.py` | 无 office demo 会话 + Tool |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §3.1 / §6 IdP 增补 |
| `docs/STATUS.md` | M4 状态 |
| `docs/delivery/2026-10-29-multi-system-m4-delivery.md` | 本文 |
| `docs/superpowers/plans/2026-10-29-multi-system-m4-idp.md` | 计划勾选 |
| `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md` | 下一步 M5 |

无 Alembic 迁移；无完整 OIDC 联调；无管理端连接器 UI（M5）。

---

## 3. 迁移说明

无库表迁移。部署后：

- 现网 OA iframe launch / 企微 mint **外部协议不变**。  
- `idp.demo_idp_enabled` 默认 **False**；生产勿开启。  
- Demo 开启后仍须匹配 `demo_shared_secret` 才可建会话。  
- 渠道路由仍由代码约定（见上）；Broker 可供调用；企微渠道已走 WeComIdP。

---

## 4. API 说明

无新增对外 HTTP 路径。内部：

| 组件 | 说明 |
|------|------|
| settings 组 `idp` | `demo_idp_enabled: bool`；`demo_shared_secret: str` |
| `IdentityBroker.verify(idp_id, payload, ctx=...)` | 返回 `PrincipalClaims` |
| `OidcIdP` | `501` / `IDP_NOT_IMPLEMENTED` |

员工侧 `/v1/chat/*`、企微长连接协议不变。

---

## 5. 权限与安全

- 硬约束不变：对 `td_oa` 零访问；模型不参与权限；密钥只写不读；浏览器仍只持平台 ticket。  
- Demo IdP 默认关闭；共享口令仅限本机。  
- 下游 token 只在服务端 `credentials` / `office_token`。  
- OIDC 未实现，不会误开生产联调路径。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `cd backend && uv run pytest -q` 全量 | **自动化通过**（**557 passed，1 skipped，0 failed**） |
| `tests/test_idp_m4.py`（13） | **自动化通过** |
| `tests/test_demo_no_oa_m4.py`（5） | **自动化通过** |
| `tests/test_auth.py` / `tests/test_wecom.py` 回归 | **自动化通过** |
| 真实 OA assertion / 企微 / office-api 联调 | **手工未执行** / **外部依赖未验证** |
| 完整 OIDC 授权码流 | **未执行**（规格仅骨架） |

skipped 为既有用例，与 M4 无关。

---

## 7. 未完成项（M5+）

- **M5**：管理端连接器 / 包管理 UI、命名去 OA 中心化、演示 Pack 产品化  
- `idp.channel_idp_map`（dict）配置化（待 schema）  
- 完整 OIDC 联调  
- 包名 `oa_agent` 重命名  
- 真 OA / 真企微手工联调  

---

## 8. 下一阶段建议

确认本交付后开 **M5**（管理端连接器/包产品化）；并行可继续 STATUS 中 X2 embedding、X3 调用过程手工验收等。
