# Multi-System Platform M3 — Domain Pack 加载器（oa_travel 下沉）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引入 Domain Pack 目录加载与启用/禁用；把行程报销只读 Tool、Skill、确定性规则与写 Workflow 元数据下沉为内置包 `oa_travel`；**禁用该包后员工侧行程能力消失，启用后恢复**。

**Architecture:** 仓库根（或 `backend/oa_agent/packs/`）放置 `pack.yaml` + 资源；`PackRegistry` 启动扫描、校验 connectors 依赖、向 Skill/Tool 同步钩子与 `workflow_catalog` / 规则提供者注册。平台核心（`tool_routing` / `oa_assistant`）只消费「已启用 Pack 聚合出的 rules/tools/workflows」，不再硬编码 `query_my_travel_expense_*`。M3 **不**做 IdP 插件（M4）、**不**做连接器管理 UI 大改（M5）；管理端仅最小「领域包」列表+启停 API（可无精美前端，但验收需 API）。

**Tech Stack:** Python 3.11+、PyYAML、pytest、现有 catalog sync / workflow_catalog / tool_routing。

**规格：** [`docs/superpowers/specs/2026-10-28-multi-system-platform-design.md`](../specs/2026-10-28-multi-system-platform-design.md) section 5 / section 9 M3  
**前置：** M1–M2 已交付。

## Global Constraints

- 硬约束：对 `td_oa` 零访问；模型不参与权限；密钥只写不读；管理写=权限+CSRF+Idempotency-Key+审计。  
- Pack 分发：**本机目录 + 后台启停**；不上传 zip（规格已锁定）。  
- 禁用 Pack ≠ 物理删除 Tool 历史版本；运行时候选与规则聚合排除即可。  
- 现网默认：**`oa_travel` 启用**，行为与改前一致（行程可查）。  
- `runtime/`、`executor/tool_routing.py` 核心禁止新增硬编码行程 Tool 名（测试与 `packs/oa_travel/` 除外）；可用 CI 注释/文档约束，M3 至少测试断言禁用后规则不再命中行程 Tool。  
- 中文文档；英文标识符。用户未要求不强制每 Task commit。

## File map（M3）

| 路径 | 职责 |
|------|------|
| `packs/oa_travel/pack.yaml` | 包元数据：id、connectors、skills/tools/contracts/rules/workflows |
| `packs/oa_travel/skills/` | 迁移或引用现 `skills/travel_expense_query.yaml` |
| `packs/oa_travel/openapi/` 或 tools | 迁移/引用 `openapi/travel_expense.yaml` |
| `packs/oa_travel/contracts/` | 引用/迁入 `contracts/travel_expense_write.yaml` |
| `packs/oa_travel/rules/intent.yaml` | 行程 list/detail 规则与 Tool 名映射（替代全局 RULE_TOOLS） |
| `backend/oa_agent/packs/__init__.py` | 包 |
| `backend/oa_agent/packs/schema.py` | PackManifest 校验 |
| `backend/oa_agent/packs/loader.py` | 扫描目录、加载、依赖检查 |
| `backend/oa_agent/packs/registry.py` | 启用状态、聚合 tools/skills/rules/workflows |
| `backend/oa_agent/packs/state.py` | 持久化启停（`agent_setting` 或新表 `agent_domain_pack`；优先 setting JSON 以少迁移） |
| `backend/oa_agent/admin/packs_api.py` | GET 列表 / POST enable|disable |
| `backend/oa_agent/runtime/workflow_catalog.py` | 写图由 pack 注册，禁用则 available=false |
| `backend/oa_agent/executor/tool_routing.py` | RULE_TOOLS / deterministic 改为读 PackRegistry.rules |
| `backend/oa_agent/runtime/intent_rules.py` | 可保留纯解析；Tool 名映射外置 |
| `backend/tests/test_packs_m3.py` | 加载、启停、聚合 |
| `backend/tests/test_pack_disable_travel_m3.py` | 禁用后无行程规则/Skill 候选 |
| `docs/delivery/2026-10-28-multi-system-m3-delivery.md` | 交付 |
| `docs/STATUS.md` | 更新 |

根目录现有 `skills/`、`openapi/`、`contracts/`：**M3 允许 pack 内相对路径指向仓库原文件**（`source: ../../openapi/travel_expense.yaml`）或复制进 pack；推荐 **pack.yaml 声明路径引用** 减少重复，首次启动仍走现有 sync。

---

### Task 1: PackManifest schema + 样例 oa_travel/pack.yaml

**Files:**
- Create: `packs/oa_travel/pack.yaml`
- Create: `backend/oa_agent/packs/schema.py`
- Test: `backend/tests/test_packs_m3.py`

**Interfaces:**
- `PackManifest`: `id: str`, `display_name: str`, `version: str`, `connectors: list[str]`, `skills: list[str]`（路径）, `tools_openapi: list[str]`, `write_contracts: list[str]`, `rules: str | None`, `workflows: list[{id, kind: chat|write, module: str}]`, `default_enabled: bool`
- `load_manifest(path: Path) -> PackManifest`；非法 YAML/缺 id 抛清晰错误

**pack.yaml 最小示例字段：**
```yaml
id: oa_travel
display_name: 行程报销
version: "1"
connectors: [office]
default_enabled: true
skills: ["../../skills/travel_expense_query.yaml"]  # 或 packs 内副本
tools_openapi: ["../../openapi/travel_expense.yaml"]
write_contracts: ["../../contracts/travel_expense_write.yaml"]
rules: rules/intent.yaml
workflows:
  - { id: travel_reimburse_submit, kind: write, graph: oa_agent.runtime.graphs.travel_reimburse_submit }
```

- [x] **Step 1: 失败测试 — 合法 manifest 加载；缺 id 失败**
- [x] **Step 2: 实现 schema + 写入 packs/oa_travel/pack.yaml**
- [x] **Step 3:** `uv run pytest tests/test_packs_m3.py -q`

---

### Task 2: PackLoader 扫描 + 依赖校验

**Files:**
- Create: `backend/oa_agent/packs/loader.py`
- Modify: `backend/tests/test_packs_m3.py`

**Interfaces:**
- `discover_packs(root: Path) -> list[PackManifest]`（扫描 `*/pack.yaml`）
- `validate_pack_files(manifest, pack_dir) -> list[str]` 错误（引用文件不存在）
- 默认 root：`REPO_ROOT / "packs"`（`settings.REPO_ROOT`）

- [x] **Step 1–3: TDD；发现 oa_travel；坏路径报错列表非空**

---

### Task 3: PackRegistry 启停状态（setting 持久化）

**Files:**
- Create: `backend/oa_agent/packs/registry.py`
- Create: `backend/oa_agent/packs/state.py`
- Modify: `backend/oa_agent/config/schema.py`（可选 group `packs`：`enabled: list[str]` 或 map）
- Test: `backend/tests/test_packs_m3.py`

**Interfaces:**
- `PackRegistry.reload(settings)`  
- `is_enabled(pack_id) -> bool`（默认取 manifest.default_enabled，再被 setting 覆盖）  
- `set_enabled(db, pack_id, enabled, actor)` + 审计 `pack.enable` / `pack.disable`（在 API Task 做审计也行）  
- `enabled_manifests() -> list[PackManifest]`

权限点：复用 `ops.config.edit` **或** 新增 `ops.pack.manage`（推荐新增并挂超级管理员角色迁移/seed）。若为减少迁移噪音，M3 可用 `ops.tool.manage` 暂代并在交付说明写明。

- [x] **Step 1: 测试默认启用 oa_travel；set_enabled false 后 is_enabled false**
- [x] **Step 2: 实现 setting 读写**
- [x] **Step 3: pytest 绿**

---

### Task 4: 规则外置 — intent.yaml + tool_routing 读 Registry

**Files:**
- Create: `packs/oa_travel/rules/intent.yaml`（LIST/DETAIL → Tool 名、关键词可与现 intent_rules 对齐）
- Modify: `backend/oa_agent/executor/tool_routing.py` — 去掉模块级写死 RULE_TOOLS 常量依赖；改为 `rules_provider()` / 传入 `rule_tool_map`
- Modify: `backend/oa_agent/runtime/intent_rules.py` — 保持日期/意图解析；返回 intent 枚举，不绑死 Tool 名（或 map 由调用方做）
- Test: `backend/tests/test_pack_disable_travel_m3.py` + 调整 `test_tool_routing.py`

**Interfaces:**
- `load_intent_rules(path) -> dict` 含 `rule_tools: {list: name, detail: name}`、可选 topic regex  
- `PackRegistry.aggregated_rule_tools() -> dict[str, str]` 仅 enabled packs  
- deterministic_first / rules 回退使用聚合 map；**无启用 pack 提供该 map 时不选行程 Tool**

- [x] **Step 1: 禁用 oa_travel 后 deterministic/rules 不再返回 travel tool 名**
- [x] **Step 2: 启用后恢复**
- [x] **Step 3: 现有 tool_routing 测适配后全绿**

---

### Task 5: Skill/Tool 可见性与 catalog 挂钩（运行时过滤）

**Files:**
- Modify: `backend/oa_agent/chat/service.py` — `visible_skills` / available tools 排除禁用 pack 声明的 skill/tool 名  
- Modify: `backend/oa_agent/runtime/workflow_catalog.py` — pack 禁用则 write workflow `available=false`  
- 可选：启动时仍 sync 文件进 DB，但 **runtime gate** 看 pack  
- Test: `test_pack_disable_travel_m3.py`

**验收：**
- 禁用后：欢迎页 skills 无行程；understand 规则无行程；`GET /v1/chat/workflows` 中 submit 不可用  
- 启用后恢复  

- [x] **Step 1–3: 集成测（可用 TestClient + 改 setting）**

---

### Task 6: Admin API 领域包列表/启停

**Files:**
- Create: `backend/oa_agent/admin/packs_api.py`
- Modify: `backend/oa_agent/main.py`、`auth/perms.py`（若新权限）
- Test: `backend/tests/test_packs_api_m3.py`
- 可选前端：`PacksView.vue` 最小列表（M3 验收以 API 为准；有页面加分但不阻塞）

**API：**
| 方法 | 路径 | 权限 |
|------|------|------|
| GET | `/v1/admin/packs` | `ops.pack.manage` 或约定权限 |
| POST | `/v1/admin/packs/{id}/enable` | 写链 CSRF+Idempotency+审计 |
| POST | `/v1/admin/packs/{id}/disable` | 同上 |

- [x] **Step 1: 403/启停/列表字段测试**
- [x] **Step 2: 实现**
- [x] **Step 3: pytest 绿**

---

### Task 7: 启动装配 + 全量回归 + 文档

**Files:**
- Modify: `runtime_state` / `engine` boot：discover packs → PackRegistry 挂到 AppRuntime  
- Modify: chat/service 注入 registry  
- Docs: delivery + STATUS + 权威设计短节「Domain Pack」  
- Plan checkboxes

- [x] **Step 1:** `cd backend && uv run pytest -q`
- [x] **Step 2: 交付说明（区分自动化/手工/外部依赖）**
- [x] **Step 3: STATUS：M3 已交付；下一刀 M4**
- [x] **Step 4: 用户要求时再 commit/push**

---

## M3 明确不做

- IdP / OIDC 插件化（M4）  
- 管理端「连接器」重做与去 OA 文案大扫除（M5）  
- Pack zip 上传  
- 把 `oa_agent` 包名重命名  
- 真 OA 手工联调（交付标未执行）

## 验收口令

1. 默认启用：行程相关自动化测与改前同等通过。  
2. API/设置禁用 `oa_travel` 后：规则与 Skill 候选无行程 Tool；写 workflow 不可用。  
3. 再启用后恢复。  
4. 全量 pytest 绿。  
5. 核心路由模块不再出现新建硬编码行程 Tool 字符串（允许从 registry 注入）。  

完成后停下，等用户确认再开 **M4**。
