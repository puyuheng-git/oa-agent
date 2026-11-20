# Agent 运行时契约纠偏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把对话选路收成「确定性窄门 → Skill 两级 → 低置信澄清」，并交付配置真相、目录闸门、MCP Server Skill、可解释轨迹与回归集（规格 A 期；不做录入智能化 B）。

**Architecture:** 不重写编排图。改 `ROUTING_DEFAULTS` / 配置 schema / `DEFAULT_CONFIG`；在 `RunContext.tools()` 与 `tool_routing.route()` 边界强制候选契约；Catalog/MCP 同步补绑定与启用闸门；管理端在 `RoutingView` 增加配置真相与人工迁移；轨迹补 `config_resolved` 等阶段事件。

**Tech Stack:** FastAPI / SQLAlchemy / Alembic / Vue3 + Element Plus / pytest（`oa-langGraph`）。

**Spec:** `docs/superpowers/specs/2026-11-20-agent-runtime-contract-design.md`

## Global Constraints

- 配置优先级不变：工作流发布快照 > 全局 `runtime` 默认。
- 不自动批量改已发布快照；不废除快照优先；不改进行中 Run/Checkpoint。
- 写操作仍走固定写 Workflow 白名单；写路径不猜 Tool。
- 员工面不出现「MCP」字样；MCP 仅为 Tool `kind=mcp`。
- Skill Pack A 期不参与业务 Tool 选路（平台 builtin 如 `skill_load` 等除外，见 Task 2）。
- 管理写 = 权限点 + CSRF + `Idempotency-Key` + 审计。
- 回复与文档中文；代码标识符英文。
- **Commit 仅在用户明确要求时执行**；计划中的 commit 步骤默认跳过，改为本地验证通过即可。
- 测试命令在 `backend` 目录：`uv run pytest … -v`（若环境无 `uv`，用项目惯用的 `pytest`）。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/oa_agent/executor/tool_routing.py` | 默认 mode；`resolve_routing_config` 无效回退；轨迹阶段事件 |
| `backend/oa_agent/config/schema.py` | runtime 字段默认与文案（海选标兼容） |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | `DEFAULT_CONFIG` 默认 mode；`RunContext.tools()` builtin 孤儿例外 |
| `backend/oa_agent/runtime/releases.py` | 枚举标签；迁移辅助（若放服务层） |
| `backend/oa_agent/executor/catalog.py` | Skill `category`；绑定 kind 校验；启用/解绑闸门辅助 |
| `backend/oa_agent/executor/mcp_sync.py` | 确保 Server Skill、同步自动绑 Tool |
| `backend/oa_agent/admin/mcp_servers_api.py` | 「确认对员工开放」API |
| `backend/oa_agent/admin/catalog_api.py` | 启用须绑 Skill；解绑拒绝孤儿；孤儿清单；种类校验 |
| `backend/oa_agent/admin/routing_api.py` | 配置真相 + 待迁移清单 + 单项迁移 |
| `backend/oa_agent/db/models.py` + `migrations/versions/0018_*.py` | `McpServer.employee_open`（或等价） |
| `frontend/src/admin/views/RoutingView.vue` (+ `routing.ts`) | 真相面板、迁移确认、孤儿入口 |
| `backend/tests/test_tool_routing.py` | 默认与轨迹 |
| `backend/tests/test_runtime_contract.py` | **新建**：孤儿/builtin/MCP/Pack/种类/真相 API 回归 |

---

### Task 1: 全局默认改为 `deterministic_first`

**Files:**
- Modify: `backend/oa_agent/executor/tool_routing.py`（`ROUTING_DEFAULTS`、`resolve_routing_config`）
- Modify: `backend/oa_agent/config/schema.py`（`tool_routing_mode` FieldDef 默认与 help）
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py`（`DEFAULT_CONFIG["tool_routing_mode"]`）
- Modify: `backend/oa_agent/runtime/releases.py`（枚举 label：海选标「兼容/待迁移」）
- Test: `backend/tests/test_tool_routing.py`

**Interfaces:**
- Produces: `ROUTING_DEFAULTS["tool_routing_mode"] == "deterministic_first"`；无效 mode 回退到 `deterministic_first`（不再回退 `legacy_prompt`）
- Consumes: 现有 `MODES` / `ROUTING_KEYS`

- [ ] **Step 1: 写失败测试（默认解析）**

在 `test_tool_routing.py` 追加：

```python
def test_routing_defaults_are_deterministic_first():
    assert tr.ROUTING_DEFAULTS["tool_routing_mode"] == "deterministic_first"
    assert tr.ROUTING_DEFAULTS["deterministic_fallback_mode"] == "skill_then_tool"
    cfg = tr.resolve_routing_config({}, None)
    assert cfg["tool_routing_mode"] == "deterministic_first"
    bad = tr.resolve_routing_config({"tool_routing_mode": "not_a_mode"}, None)
    assert bad["tool_routing_mode"] == "deterministic_first"


def test_workflow_snapshot_still_wins_over_default():
    cfg = tr.resolve_routing_config(
        {"tool_routing_mode": "legacy_prompt"},
        {"tool_routing_mode": "deterministic_first"},
    )
    assert cfg["tool_routing_mode"] == "legacy_prompt"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_tool_routing.py::test_routing_defaults_are_deterministic_first tests/test_tool_routing.py::test_workflow_snapshot_still_wins_over_default -v`  
Expected: FAIL（仍为 `legacy_prompt` 默认）

- [ ] **Step 3: 改默认与回退**

`tool_routing.py`：

```python
ROUTING_DEFAULTS: dict[str, Any] = {
    "tool_routing_mode": "deterministic_first",
    # ... 其余键保持不变 ...
    "deterministic_fallback_mode": "skill_then_tool",
    "routing_clarify_on_low_confidence": True,
    "routing_trace_enabled": True,
}
```

在 `resolve_routing_config` 内：

```python
mode = out.get("tool_routing_mode") or "deterministic_first"
if mode not in MODES:
    mode = "deterministic_first"
out["tool_routing_mode"] = mode
```

同步改 `schema.py` 中 `FieldDef("tool_routing_mode", ..., "deterministic_first", ...)`：help 写明海选为兼容/待迁移；`options` 里 `legacy_prompt` 标签改为「提示词海选（兼容/待迁移）」。

`oa_assistant.DEFAULT_CONFIG["tool_routing_mode"] = "deterministic_first"`。

`releases.py` 中对应 enum 选项 label 与 schema 一致。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_tool_routing.py::test_routing_defaults_are_deterministic_first tests/test_tool_routing.py::test_workflow_snapshot_still_wins_over_default -v`  
Expected: PASS

- [ ] **Step 5: 全量路由单测不回归**

Run: `uv run pytest tests/test_tool_routing.py -v`  
Expected: PASS（若有断言写死旧默认，一并改为新默认）

---

### Task 2: 候选契约 — 孤儿剔除 + builtin 例外 + Pack 不扩业务 Tool

**Files:**
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py`（`RunContext.tools`）
- Modify: `backend/oa_agent/executor/executor.py`（执行前二次断言，若尚未覆盖孤儿）
- Test: `backend/tests/test_runtime_contract.py`（新建）

**Interfaces:**
- Produces:
  - `RunContext.tools()`：当 `skills is not None` 时，候选 = 可见 Skill 绑定 ∪ **registry 中 `kind=="builtin"`（含导出/技能元工具）**；非 builtin 孤儿不出现
  - Pack 仍可注入 `SKILL_*` builtin，但**不得**因 Pack 把任意业务 Tool 名塞进候选
- Consumes: `registry.get` / `ToolSpec.kind` / 现有 `_export_skill` 等

**背景：** 今日 `tools()` 已按 Skill 绑定收窄；缺口是（1）`skills is None` 时全注册表；（2）未显式保证未绑 Skill 的 builtin 仍可用；（3）需文档化 Pack 只带 builtin 元工具。

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/test_runtime_contract.py`：

```python
from oa_agent.runtime.graphs.oa_assistant import RunContext, EXPORT_TOOL

class FakeReg:
    def __init__(self, specs: dict):
        self._specs = specs
    def names(self):
        return list(self._specs)
    def get(self, name):
        return self._specs.get(name)

def test_tools_excludes_orphan_non_builtin():
    orphan = FakeSpec("orphan_office", kind="office")  # 在测试文件内定义带 kind 的 FakeSpec
    bound = FakeSpec("bound_office", kind="office")
    builtin = FakeSpec("sys_calc", kind="builtin")
    skill = FakeSkill("travel", "行程", tools=["bound_office"])
    ex = SimpleNamespace(registry=FakeReg({
        "orphan_office": orphan, "bound_office": bound, "sys_calc": builtin, EXPORT_TOOL: FakeSpec(EXPORT_TOOL, kind="builtin"),
    }))
    ctx = RunContext(executor=ex, skills=[skill], skill_packs=[])
    names = set(ctx.tools())
    assert "bound_office" in names
    assert "orphan_office" not in names
    assert "sys_calc" in names or EXPORT_TOOL in names  # builtin 例外


def test_skills_none_still_not_required_for_unit_tests_but_chat_always_sets_skills():
    """文档化：生产 chat 路径必须传 skills；本测仅锁定 tools() 在 skills=None 时的行为选择。
    契约：skills=None 时仍暴露全注册表（兼容旧单测），但 chat.service 必须传 visible skills。
    """
    pass  # 在 Step 3 用 chat 侧断言或注释 + 单独测试 visible 路径
```

实现时把 `FakeSpec` 做成带 `kind` 属性；若 `ToolSpec` 从 registry 来，用真实 `ToolSpec` 或 SimpleNamespace。

更稳妥的生产断言：在 `chat/service.py` 组装 `RunContext` 处加测试/不变量——`skills` 永不为 `None`（可空列表）。

- [ ] **Step 2: 跑测确认失败**

Run: `uv run pytest tests/test_runtime_contract.py::test_tools_excludes_orphan_non_builtin -v`  
Expected: FAIL 或按当前行为调整断言后先红

- [ ] **Step 3: 实现 `tools()` 契约**

在 `RunContext.tools()` 中，`skills is not None` 分支末尾：

```python
# 全局 builtin 例外：未出现在任何 Skill 绑定中的 builtin 仍可进候选
for name in registry.names():
    if name in out:
        continue
    spec = registry.get(name)
    if spec is not None and getattr(spec, "kind", None) == "builtin":
        out[name] = (spec, None)
```

保持现有 EXPORT / SKILL_* 注入逻辑；确认它们 `kind=builtin`，避免重复逻辑冲突。

在 `chat/service.py` 构建 `RunContext` 处断言/保证：`skills` 使用 `visible_skills_for(...)` 的列表（可为 `[]`），**不要传 `None`**。

Executor：若 `execute(name)` 时 name 不在「当前 RunContext 允许集」——生产路径已有 `name not in ctx.tools()` 检查（见 `oa_assistant`）；补测覆盖孤儿执行失败。

- [ ] **Step 4: 跑测通过**

Run: `uv run pytest tests/test_runtime_contract.py -v`  
Expected: PASS

---

### Task 3: 轨迹阶段事件（配置来源可解释）

**Files:**
- Modify: `backend/oa_agent/executor/tool_routing.py`（`route` / `_emit`）
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py`（把 config 来源传入 route，若需）
- Test: `backend/tests/test_tool_routing.py` 或 `test_runtime_contract.py`

**Interfaces:**
- Produces: 在 `routing_start` 前后增加 `config_resolved` 事件 metadata：`mode`, `source`（`"global"` | `"release"`）, `fallback_mode`；确定性阶段已有事件则补 `source=deterministic`；`tool_candidates` 阶段带 `filtered_orphan_count`（可选）
- Consumes: `recorder.event`；`resolve_routing_config`

- [ ] **Step 1: 写失败测试**

```python
def test_route_emits_config_resolved():
    rec = FakeRecorder()
    tr.route(
        "查报销",
        tools=_two_tools(),
        today=date(2026, 10, 28),
        config={},
        runtime_defaults=None,
        recorder=rec,
    )
    types = [e["event_type"] for e in rec.events]
    assert "config_resolved" in types
    ev = next(e for e in rec.events if e["event_type"] == "config_resolved")
    assert ev["metadata"]["mode"] == "deterministic_first"
```

- [ ] **Step 2: 跑测确认失败** → Expected: FAIL missing event

- [ ] **Step 3: 在 `route()` 开头 `_emit`**

```python
_emit(recorder, trace, "config_resolved", metadata={
    "mode": mode,
    "source": "release" if (config or {}).get("tool_routing_mode") is not None else "global",
    "fallback_mode": cfg.get("deterministic_fallback_mode"),
})
```

说明：若工作流快照显式写了 key 则 `source=release`；仅靠 runtime/代码默认则为 `global`。更精确做法：`resolve_routing_config` 同时返回 `source` 字段（推荐，避免误判「快照里写了别的键」）。

推荐实现：

```python
def resolve_routing_config(...) -> dict:
    ...
    out["_config_source"] = "release" if "tool_routing_mode" in (workflow_config or {}) else (
        "global" if "tool_routing_mode" in (runtime_defaults or {}) else "code_default"
    )
    return out
```

对外 API 可去掉 `_` 前缀键。

- [ ] **Step 4: 跑测通过**

---

### Task 4: 入库闸门 — 启用须绑 Skill；解绑拒绝孤儿；孤儿清单

**Files:**
- Modify: `backend/oa_agent/executor/catalog.py`（辅助函数）
- Modify: `backend/oa_agent/admin/catalog_api.py`（enable / save_skill / list orphans）
- Test: `backend/tests/test_runtime_contract.py`（API 级，复用现有 admin fixture）

**Interfaces:**
- Produces:
  - `tool_skill_refs(db, tenant_id) -> dict[str, set[str]]`  # tool_name -> skill names
  - `assert_tool_bound_for_enable(db, tenant_id, tool_name, kind) -> None`  # builtin 跳过
  - `GET /v1/admin/tools/orphans` → `{ items: [{ name, kind, enabled }] }`
  - enable 非 builtin 未绑定 → 400；Skill 保存若移除某 tool 且无其他 Skill 引用 → 400「请先改绑或先禁用 Tool」
- Consumes: `Skill` / `SkillVersion.content_json.tools` / `Tool.kind`

- [ ] **Step 1: 写失败 API 测试**（参照 `test_catalog.py` / `test_skill_visibility.py` 的 admin client fixture）

```python
def test_enable_orphan_office_tool_rejected(admin):
    # 创建 enabled=False、未出现在任何 Skill.tools 的 office tool
    r = admin.post(f"/v1/admin/tools/{name}/enable", ...)
    assert r.status_code == 400
    assert "Skill" in (r.json().get("detail") or r.json().get("message") or "")


def test_list_orphans_includes_unbound(admin):
    r = admin.get("/v1/admin/tools/orphans")
    assert r.status_code == 200
    names = [i["name"] for i in r.json()["items"]]
    assert "orphan_x" in names
```

- [ ] **Step 2: 跑测红**

- [ ] **Step 3: 实现辅助 + API**

在 `catalog.py`：

```python
def iter_skill_tool_bindings(db, tenant_id: str) -> dict[str, set[str]]:
    """tool_name -> set(skill_name)."""
    ...

def is_orphan_tool(db, tenant_id: str, tool_name: str, kind: str) -> bool:
    if kind == "builtin":
        return False
    return tool_name not in iter_skill_tool_bindings(db, tenant_id)
```

`catalog_api`：enable 前调用；`save_skill` / PUT 时若新 tools 集合导致某 tool 变为孤儿且该 tool `enabled=True` → 拒绝。  
`GET /tools/orphans`：`kind != builtin` 且无绑定。

- [ ] **Step 4: 跑测绿**

---

### Task 5: Skill `category` + 可绑 Tool kind 校验

**Files:**
- Modify: `backend/oa_agent/executor/catalog.py`（`normalize_skill`）
- Modify: `backend/oa_agent/admin/catalog_api.py`（保存时查 Tool.kind）
- Modify: `frontend/src/admin/views/SkillsView.vue`（种类下拉，最小）
- Test: `backend/tests/test_runtime_contract.py`

**Interfaces:**
- Produces: `content_json.category` ∈ `oa_query` | `oa_invoke` | `external_mcp` | `platform` | `""`（空=不约束，兼容旧数据）
- 约束表（写死常量）：

```python
SKILL_CATEGORY_KINDS = {
    "oa_query": frozenset({"office", "open_oa_invoke"}),
    "oa_invoke": frozenset({"office", "open_oa_invoke"}),
    "external_mcp": frozenset({"mcp"}),
    "platform": frozenset({"builtin"}),
}
```

空 category：不校验 kind（仅后台分组用）。

- [ ] **Step 1: 测试** — `category=external_mcp` 绑 `office` Tool → normalize/save 失败  
- [ ] **Step 2: 实现** — `normalize_skill` 保留 `category`；save 时加载 Tool.kind 比对  
- [ ] **Step 3: SkillsView** — 表单增加种类 select（可空）  
- [ ] **Step 4: 测通**

**说明：** 种类**不**参与 `route()` 粗路由（规格已锁）。

---

### Task 6: MCP — Server Skill + 同步自动绑定 + 确认开放

**Files:**
- Create migration: `backend/migrations/versions/0018_mcp_employee_open.py`
- Modify: `backend/oa_agent/db/models.py`（`McpServer.employee_open: bool` 默认 `False`）
- Modify: `backend/oa_agent/executor/mcp_sync.py`
- Modify: `backend/oa_agent/admin/mcp_servers_api.py`
- Test: `backend/tests/test_mcp_servers_api.py` / `test_runtime_contract.py`

**Interfaces:**
- Produces:
  - `ensure_mcp_server_skill(db, tenant_id, server, operator) -> Skill`  
    name 稳定：`mcp_<server.name>`（需符合 `NAME_RE`；非法字符替换为 `_`）  
    `category=external_mcp`；`source_file=mcp:server:<id>`
  - `sync_server_tools`：创建/更新后把 tool name 并入该 Skill 的 `tools` 列表；**保持 `enabled=False`**
  - `POST /v1/admin/mcp-servers/{name}/open-to-employees`：`employee_open=True`，批量 `enabled=True` 该 server 下 mcp tools（仍受可见性规则约束）；审计 `mcp_server.open_employees`
  - `POST .../close-to-employees`：反向（可选但推荐对称）
- Consumes: 现有 sync 事务；Visibility 仍按 Skill 规则

- [ ] **Step 1: 迁移 + ORM**

```python
# 0018_mcp_employee_open.py
revision = "0018_mcp_employee_open"
down_revision = "0017_llm_model_routing"
# add agent_mcp_server.employee_open Boolean default false
```

- [ ] **Step 2: 测试** — sync 后 Tool 出现在 Server Skill.tools；`employee_open` 前不在员工可见候选（enabled false 即不可注册进 runtime——与现网一致）；open 后 enabled true  
- [ ] **Step 3: 实现 ensure + sync 绑定 + open API**  
- [ ] **Step 4: 测通**；`uv run pytest tests/test_mcp_servers_api.py tests/test_runtime_contract.py -v`

**注意：** 现注释已要求「新增默认停用」；本任务补齐**自动绑 Skill**，避免启用后仍孤儿。

---

### Task 7: 配置真相 API + 人工迁移单项

**Files:**
- Modify: `backend/oa_agent/admin/routing_api.py`
- Modify: `backend/oa_agent/runtime/releases.py`（可选 helper）
- Test: `backend/tests/test_runtime_contract.py`

**Interfaces:**
- Produces:
  - `GET /v1/admin/routing/config-truth`（权限 `ops.run.view` 或 `sys.setting.view`——与配置中心读权限对齐；若无现成 perm，用 `ops.run.view`）  
    ```json
    {
      "global_mode": "deterministic_first",
      "global_fallback": "skill_then_tool",
      "active_workflows": [
        {"workflow_id": "...", "release_id": "...", "tool_routing_mode": "legacy_prompt", "matches_global": false}
      ],
      "legacy_prompt_releases": [ ... ],
      "note": "单次对话以会话绑定 release 快照为准"
    }
    ```
  - `POST /v1/admin/routing/releases/{release_id}/migrate-contract`  
    body: `{ "confirm": true, "reason": "..." }`  
    将**下一草稿或允许改的草稿**写入契约默认；若业务上只能改 draft：则「基于该 release 创建/更新 draft 并写入路由键」，**不直接改已冻结 published content**（与现有 ReleaseService 一致）。  
    若项目允许对 published 打补丁——以 `ReleaseService` 现有能力为准；**禁止**静默改历史 version 行。  
    审计：`routing.snapshot.migrate`  
  - `POST /v1/admin/routing/releases/{release_id}/ack-keep-legacy`（可选）body 标记保留海选，清单可过滤

实现迁移时优先路径：**更新 workflow draft 的 content_json 路由键 → 管理员自行发布**；API 返回 `{ draft_version, next_step: "publish" }`，避免违背「发布即冻结」。

- [ ] **Step 1: 测试真相接口含 legacy 项；迁移写 draft**  
- [ ] **Step 2: 实现**  
- [ ] **Step 3: 测通**

---

### Task 8: 管理端 RoutingView — 真相面板 + 迁移确认

**Files:**
- Modify: `frontend/src/admin/views/RoutingView.vue`
- Modify: `frontend/src/admin/routing.ts`（类型与 fetch helper）
- Test: `frontend/src/admin/routing.spec.ts`（纯函数/展示；可选）

**Interfaces:**
- Consumes: Task 7 API
- Produces: 页面顶部 Card「配置真相」；表格列出 `legacy_prompt_releases`；按钮「迁移到契约默认」→ 二次确认 Dialog 展示 diff → POST；链到孤儿清单（`/tools` 或内嵌请求 orphans）

- [ ] **Step 1: `routing.ts` 增加类型与 `fetchConfigTruth`**  
- [ ] **Step 2: `RoutingView` 增加面板与迁移 Dialog**（中文文案；无数据用现有 `NO_DATA`）  
- [ ] **Step 3:** `npm test -- routing.spec.ts`（若有新纯函数）+ 手测说明写在 PR/交付备注

---

### Task 9: 规格 §9 回归集收口

**Files:**
- Modify: `backend/tests/test_runtime_contract.py`（把下列用例全部落到可自动跑）
- Modify: 必要时补 `test_tool_routing.py`

**Interfaces:** 无新生产 API；Produces: 一键回归

用例清单（每条独立 `test_*`）：

1. 默认 `deterministic_first` + fallback `skill_then_tool`（Task 1）  
2. 确定性命中不进 Skill 海选（已有路由测可复用/断言 `fallback_from` 空且 mode deterministic）  
3. 绑在可见 Skill 下的 Tool 可选中  
4. 孤儿非 builtin 不在 `ctx.tools()`；执行路径拒绝  
5. builtin 未绑可进候选  
6. 低置信 clarify（`routing_clarify_on_low_confidence=True`，构造低置信场景）  
7. MCP sync 默认不可对话；open 后可启用  
8. Skill Pack 启用不把业务 Tool 塞进候选（仅 builtin 元工具）  
9. 种类不允许的绑定保存失败  
10. 快照 `legacy_prompt` 时 effective 为海选且出现在 config-truth 清单  

- [ ] **Step 1: 补齐缺失用例**  
- [ ] **Step 2: Run** `uv run pytest tests/test_runtime_contract.py tests/test_tool_routing.py tests/test_mcp_servers_api.py -v`  
Expected: PASS  
- [ ] **Step 3: Run** `cd frontend && npm test`（至少 admin 相关）Expected: PASS  

---

### Task 10: 交付备注（短）

**Files:**
- Create: `docs/delivery/2026-11-20-agent-runtime-contract-delivery.md`

- [ ] **Step 1: 写交付摘要** — 范围、迁移步骤（改全局默认 → 看真相页 → 人工迁 draft → 发布）、已知风险（主工作流仍钉海选则体感不变）、A/B 边界  
- [ ] **Step 2: 把 spec 状态行改为「实现中/已交付」**（实现完成时再改）

---

## Self-review（对照规格）

| 规格章节 | 任务 |
|----------|------|
| §4 选路契约 / 默认 | Task 1–2 |
| §5 配置真相与迁移 | Task 7–8 |
| §6 孤儿/绑定/MCP/种类 | Task 4–6 |
| §7 轨迹 | Task 3 |
| §8 错误与安全 | Task 4/6/7 审计与 400 |
| §9 回归 | Task 9 |
| §10 A/B 边界 | Task 10；未包含向导智能化 |
| Pack 排除选路 | Task 2 / 9.8 |
| 不自动批量迁快照 | Task 7（draft + 人工发布） |

**占位符扫描：** 无 TBD。  
**注意：** Task 7 迁移落 **draft 再发布**，与「不直接改冻结 published」一致；若实现时发现 ReleaseService 另有官方 migrate API，优先复用，勿发明第二套发布通道。
