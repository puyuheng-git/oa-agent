# 交付说明：多系统平台 M3 — Domain Pack 加载器（oa_travel 下沉）

**日期：** 2026-10-28  
**规格：** `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`（M3）  
**计划：** `docs/superpowers/plans/2026-10-28-multi-system-m3-packs.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md` §3.1（Domain Pack）  
**前置：** M1–M2 已交付

---

## 1. 功能

1. **Domain Pack 目录加载**：扫描仓库根 `packs/*/pack.yaml`；`PackManifest` 校验 id/connectors/skills/tools/rules/workflows；引用路径可指向仓库既有 `skills/`、`openapi/`、`contracts/`。  
2. **内置包 `oa_travel`**：行程报销 Skill / OpenAPI / 写契约 / 意图规则 / 写 Workflow 元数据下沉为 Pack；默认启用，行为与改前一致。  
3. **`PackRegistry`**：启停状态（`settings.packs.disabled_ids`）；聚合已启用包的 `rule_tools`、Skill 过滤、Workflow 可用性。  
4. **规则外置**：`packs/oa_travel/rules/intent.yaml`；`tool_routing` 读 Registry 聚合 map，核心不再硬编码行程 Tool 名。  
5. **运行时门禁**：禁用 `oa_travel` 后欢迎页 Skill 无行程、deterministic/rules 不选行程 Tool、写 workflow `available=false`（`pack_disabled`）；再启用恢复。  
6. **管理 API**：`GET /v1/admin/packs`、`POST .../enable|disable`（CSRF + Idempotency-Key + 审计）。

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `packs/oa_travel/pack.yaml` | 行程报销包清单 |
| `packs/oa_travel/rules/intent.yaml` | list/detail → Tool 名与意图规则 |
| `backend/oa_agent/packs/__init__.py` | 包导出 |
| `backend/oa_agent/packs/schema.py` | `PackManifest` / `load_manifest` |
| `backend/oa_agent/packs/loader.py` | 扫描、路径校验 |
| `backend/oa_agent/packs/registry.py` | 启停、聚合 rules/skills/workflows |
| `backend/oa_agent/packs/state.py` | `packs.disabled_ids` 读写 |
| `backend/oa_agent/packs/rules_load.py` | 加载 intent.yaml |
| `backend/oa_agent/admin/packs_api.py` | 领域包列表与启停 API |
| `backend/oa_agent/config/schema.py` | settings 组 `packs` |
| `backend/oa_agent/runtime_state.py` | boot 挂载 PackRegistry |
| `backend/oa_agent/main.py` | 注册 packs 路由 |
| `backend/oa_agent/chat/service.py` | Registry 注入；Skill/规则过滤 |
| `backend/oa_agent/executor/tool_routing.py` | 读聚合 rule_tools |
| `backend/oa_agent/runtime/workflow_catalog.py` | pack 禁用 → available=false |
| `backend/oa_agent/admin/workflows_api.py` | 列表传 pack_registry |
| `backend/tests/test_packs_m3.py` | schema / loader / registry |
| `backend/tests/test_pack_disable_travel_m3.py` | 禁用后无行程能力 |
| `backend/tests/test_packs_api_m3.py` | 管理 API |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §3.1 Domain Pack |
| `docs/STATUS.md` | M3 状态 |
| `docs/delivery/2026-10-28-multi-system-m3-delivery.md` | 本文 |
| `docs/superpowers/plans/2026-10-28-multi-system-m3-packs.md` | 计划勾选 |
| `docs/superpowers/specs/2026-10-28-multi-system-platform-design.md` | 下一步 M4 |

无 Alembic 迁移；无 Pack zip 上传；无管理端精美前端（API 验收）。

---

## 3. 迁移说明

无库表迁移。部署后：

- 默认 **`oa_travel` 启用**（`disabled_ids` 为空），行程 list/detail / Skill / 写 workflow 元数据与改前一致。  
- 启停写入 settings 组 **`packs.disabled_ids`**（热生效，刷新进程内 Registry）。  
- 禁用 Pack **不**物理删除 Tool/Skill 历史版本；仅运行时聚合与可见性排除。  
- `pack.yaml` 相对路径引用现有仓库文件，catalog sync 仍可按原路径导入。

---

## 4. API 说明

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/v1/admin/packs` | `ops.tool.manage`（读） | 列表：id、display_name、version、enabled、connectors、validation_errors |
| POST | `/v1/admin/packs/{id}/enable` | `ops.tool.manage`（写链） | CSRF + Idempotency-Key + 审计 `pack.enable` |
| POST | `/v1/admin/packs/{id}/disable` | 同上 | 审计 `pack.disable` |

员工侧既有 `/v1/chat/*` 路径不变；禁用后 Skill/规则/Workflow 候选自动收缩。

内部：settings 组 `packs.disabled_ids: list[str]`。

---

## 5. 权限与安全

- 硬约束不变：对 `td_oa` 零访问；模型不参与权限；密钥只写不读。  
- M3 管理启停权限 **复用 `ops.tool.manage`**（避免新增 `ops.pack.manage` 迁移噪音）；后续可迁独立权限点。  
- 写操作 = 权限 + CSRF + `Idempotency-Key` + 审计；审计失败则操作失败。  
- 禁用 Pack ≠ 绕过 office-api 授权；启用后业务授权仍在上游。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `cd backend && uv run pytest -q` 全量 | **自动化通过**（**539 passed，1 skipped，0 failed**） |
| `tests/test_packs_m3.py`（11） | **自动化通过** |
| `tests/test_pack_disable_travel_m3.py`（7） | **自动化通过** |
| `tests/test_packs_api_m3.py`（3） | **自动化通过** |
| 行程 / tool_routing / workflow 相关回归 | **自动化通过** |
| 真实 OA 宿主页禁用/启用 `oa_travel` 手工联调 | **手工未执行** |
| 真实 LLM / 企微 / office-api | **外部依赖未验证** |

skipped 为既有用例，与 M3 无关。

---

## 7. 未完成项（M4+）

- **M4**：IdP 插件化 / OIDC（规格仅骨架）  
- **M5**：管理端连接器 UI 重做、命名去 OA 中心化、演示 Pack  
- Pack zip 上传；`ops.pack.manage` 独立权限点  
- 管理端领域包精美前端  
- 包名 `oa_agent` 重命名  
- embedding 路由、写 Workflow 真 OA 联调  

---

## 8. 下一阶段建议

确认本交付后开 **M4**（IdP 插件化 / OIDC 骨架）；并行可继续 STATUS 中 X2 embedding、X3 调用过程手工验收等。
