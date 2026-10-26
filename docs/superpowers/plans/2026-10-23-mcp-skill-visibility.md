# MCP / Skill 可见权限 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按员工裁剪 Skill 目录可见性（欢迎页 / 帮助 / 模型候选 / 执行前）；定稿 Tool·Skill·执行器职责；预留 OA 标签与出站 MCP 接口（不连真系统）。

**Architecture:** 新表 `agent_skill_visibility_rule` + `VisibilityService` 统一裁剪。无规则 = 不启裁剪（D19=C）。规则即时生效、不进 Release。`TagProvider` 默认返回 `[]`；`NoopOutboundMcpClient` 占位。管理端仅 API（`ops.skill.manage`），无前端 UI。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、既有 chat/admin 鉴权、pytest。

**Spec:** `docs/superpowers/specs/2026-10-23-mcp-skill-visibility-design.md`

## Global Constraints

- 与 OA 只走 HTTP；不访问 `td_oa`。
- 身份只来自服务端 `session.oa`；丢弃客户端自报 `oa` / `tags`。
- Agent 只做目录可见性；业务放行在 office-api；模型输出不参与权限判定。
- 管理写 = 权限点 + CSRF + `Idempotency-Key` + 审计；审计失败则失败。
- 密钥只写不读；日志/审计无明文密钥。
- 不可见时错误码复用 `TOOL_NOT_AVAILABLE`，文案「该功能未对你开放」（D7=B）。
- 回复与文档中文；代码标识符英文。
- 测试不得把未执行说成通过；OA 标签联调 / 真实 MCP = 本期不做。
- `data/` 不入库。无 git 时跳过所有 Commit 步骤。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/migrations/versions/0009_skill_visibility.py` | 建表 |
| `backend/oa_agent/db/models.py` | `SkillVisibilityRule` ORM |
| `backend/oa_agent/mcp/visibility.py` | `PrincipalContext`、`VisibilityService`、规则 CRUD 辅助 |
| `backend/oa_agent/mcp/tags.py` | `TagProvider` Protocol + `EmptyTagProvider` |
| `backend/oa_agent/mcp/outbound.py` | 出站 MCP Protocol + `NoopOutboundMcpClient` |
| `backend/oa_agent/chat/service.py` | `skill_menu` 按 oa 过滤 |
| `backend/oa_agent/runtime/graphs/travel_query.py` | RunContext 候选 Skill 过滤；帮助文案 |
| `backend/oa_agent/runtime/engine.py` 或构图处 | 向 RunContext 注入已过滤 skills |
| `backend/oa_agent/mcp/executor.py` | 执行前可见性断言（若上下文可取） |
| `backend/oa_agent/admin/catalog_api.py` | GET/PUT `.../visibility`、preview |
| `backend/oa_agent/config/schema.py` | 默认 `tool_not_available` 文案 |
| `backend/tests/test_skill_visibility.py` | 领域 + HTTP + 运行时过滤 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §8 用语 + §12 API 短更新 |
| `docs/delivery/2026-10-23-mcp-skill-visibility-delivery.md` | 交付说明 |

---

### Task 1: 模型与迁移

**Files:**
- Create: `backend/migrations/versions/0009_skill_visibility.py`
- Modify: `backend/oa_agent/db/models.py`
- Test: `backend/tests/test_skill_visibility.py`（先冒烟：表可写一行）

**Interfaces:**
- Produces: ORM `SkillVisibilityRule`；表 `agent_skill_visibility_rule`
- Constants: `effect` ∈ `{allow,deny}`；`principal_type` ∈ `{all,oa,tag}`

- [ ] **Step 1: 写失败测试（模型可插入）**

```python
# backend/tests/test_skill_visibility.py
def test_visibility_rule_row_persists(rt):
    from oa_agent.db.models import Skill, SkillVisibilityRule
    with rt.session() as db, db.begin():
        skill = db.scalar(sa.select(Skill).limit(1))
        if skill is None:
            pytest.skip("no skill fixture")
        db.add(SkillVisibilityRule(
            tenant_id=rt.tenant_id, skill_id=skill.id,
            effect="allow", principal_type="oa", principal_value="alice",
            created_by="test",
        ))
    with rt.session() as db:
        n = db.scalar(sa.select(sa.func.count()).select_from(SkillVisibilityRule))
        assert n >= 1
```

- [ ] **Step 2: 跑测确认失败（无表/无模型）**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_skill_visibility.py::test_visibility_rule_row_persists -q`  
Expected: FAIL（ImportError 或表不存在）

- [ ] **Step 3: 在 `models.py`（`SkillVersion` 后）增加**

```python
class SkillVisibilityRule(Base):
    __tablename__ = "agent_skill_visibility_rule"
    __table_args__ = (
        sa.Index("ix_skill_vis_tenant_skill", "tenant_id", "skill_id"),
        sa.UniqueConstraint(
            "tenant_id", "skill_id", "effect", "principal_type", "principal_value",
            name="uk_skill_vis_rule",
        ),
    )
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    skill_id: Mapped[int] = mapped_column(sa.BigInteger)
    effect: Mapped[str] = mapped_column(sa.String(8))  # allow|deny
    principal_type: Mapped[str] = mapped_column(sa.String(16))  # all|oa|tag
    principal_value: Mapped[str] = mapped_column(sa.String(128), default="")
    created_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)
```

`principal_value`：`all` 时存 `""` 或 `"*"`（实现取一种并在 PUT 规范化为 `""`）。

- [ ] **Step 4: 迁移 `0009_skill_visibility.py`**

`down_revision = "0008_chat_thread"`。建表 + 索引 + UK。`downgrade` drop 表。无数据回填。

- [ ] **Step 5: 跑测通过**

Run: `cd backend && .venv\Scripts\python -m pytest tests/test_skill_visibility.py::test_visibility_rule_row_persists -q`  
Expected: PASS（若无 Skill 种子则测试改为自建最小 Skill 行，或用 catalog 夹具）

- [ ] **Step 6: Commit（无 git 则跳过）**

```bash
git add backend/oa_agent/db/models.py backend/migrations/versions/0009_skill_visibility.py backend/tests/test_skill_visibility.py
git commit -m "feat(visibility): add skill visibility rule table"
```

---

### Task 2: VisibilityService + TagProvider

**Files:**
- Create: `backend/oa_agent/mcp/visibility.py`
- Create: `backend/oa_agent/mcp/tags.py`
- Modify: `backend/tests/test_skill_visibility.py`

**Interfaces:**
- Produces:
  - `PrincipalContext(oa: str, tags: list[str])`
  - `TagProvider.load_tags(oa: str, office_token: str) -> list[str]`
  - `EmptyTagProvider`
  - `VisibilityService.is_skill_visible(db, *, tenant_id, skill_id, principal) -> bool`
  - `VisibilityService.filter_skill_ids(db, *, tenant_id, skill_ids, principal) -> set[int]`
  - `VisibilityService.replace_rules(db, *, tenant_id, skill_id, rules, created_by) -> None`
  - `VisibilityService.list_rules(db, *, tenant_id, skill_id) -> list[SkillVisibilityRule]`
- Consumes: `SkillVisibilityRule`；规则行按 `skill_id` 加载

**规则语义（必须测）：**

1. 该 skill **0 行** → `True`（D19=C）
2. deny 命中 → `False`（优先）
3. allow `all` / allow `oa==principal.oa` → `True`
4. allow `tag` 且 tag ∈ principal.tags → `True`
5. 有规则但无 allow 命中（含仅 tag 且 tags=[]）→ `False`

- [ ] **Step 1: 写失败测试**

```python
def test_no_rules_means_visible(rt):
    from oa_agent.mcp.visibility import PrincipalContext, VisibilityService
    with rt.session() as db:
        assert VisibilityService.is_skill_visible(
            db, tenant_id=rt.tenant_id, skill_id=999001,
            principal=PrincipalContext(oa="alice", tags=[]),
        ) is True

def test_allow_oa_and_deny_priority(rt):
    # 建 skill + allow oa=alice + deny oa=alice → False
    # 仅 allow oa=alice，principal bob → False
    ...

def test_tag_rule_no_hit_when_tags_empty(rt):
    # 仅 allow tag=finance，tags=[] → False
    ...
```

- [ ] **Step 2: 跑测确认失败**

Run: `pytest tests/test_skill_visibility.py::test_no_rules_means_visible tests/test_skill_visibility.py::test_allow_oa_and_deny_priority tests/test_skill_visibility.py::test_tag_rule_no_hit_when_tags_empty -q`  
Expected: FAIL

- [ ] **Step 3: 实现 `tags.py` 与 `visibility.py`**

```python
# tags.py 要点
class TagProvider(Protocol):
    def load_tags(self, oa: str, office_token: str) -> list[str]: ...

class EmptyTagProvider:
    def load_tags(self, oa: str, office_token: str) -> list[str]:
        return []
```

```python
# visibility.py 命中逻辑要点
def _principal_matches(rule, principal) -> bool:
    if rule.principal_type == "all":
        return True
    if rule.principal_type == "oa":
        return principal.oa == rule.principal_value
    if rule.principal_type == "tag":
        return rule.principal_value in (principal.tags or [])
    return False
# 先扫 deny，再扫 allow；无规则短路径 True
```

`replace_rules`：删该 skill 全部规则再插入；校验 effect/type；`all` 的 value 规范为 `""`。

- [ ] **Step 4: 跑测通过**

Run: 同上三条 + 既有 `test_visibility_rule_row_persists`  
Expected: PASS

- [ ] **Step 5: Commit（无 git 则跳过）**

```bash
git add backend/oa_agent/mcp/visibility.py backend/oa_agent/mcp/tags.py backend/tests/test_skill_visibility.py
git commit -m "feat(visibility): VisibilityService and empty TagProvider"
```

---

### Task 3: 欢迎页 / 帮助 / understand 候选接入

**Files:**
- Modify: `backend/oa_agent/chat/service.py`（`skill_menu`）
- Modify: `backend/oa_agent/runtime/engine.py` 与/或构图注入 `RunContext.skills` 处（`chat/service.py` `_build_context` / `start_run`）
- Modify: `backend/oa_agent/runtime/graphs/travel_query.py`（若帮助路径需显式；通常过滤 skills 即可）
- Modify: `backend/tests/test_skill_visibility.py`

**Interfaces:**
- Consumes: `VisibilityService`、`EmptyTagProvider`、`PrincipalContext(oa=session.oa, tags=provider.load_tags(...))`
- Produces: `skill_menu(rt, oa=...)` 或内部用 session；`available_skills_for(oa)` 过滤后列表

**接入要点：**

1. `skill_menu`：在现有 `available_skills()` 之上按 `skill` 的 DB `id`（`SkillState` 若无 id 则用 `name` 反查）过滤不可见。
2. 构建 `RunContext` 时传入的 `skills=` 必须已是可见子集（与欢迎页一致）。
3. `help_text` 使用同一可见 skills 列表。
4. **库宕机：** 与 chat 降级一致——可见性查询失败时记录日志并**不挡**对话（可回退为不过滤）；有规则且库可用时必须过滤。测试用正常库路径覆盖过滤。

- [ ] **Step 1: 写失败集成测试**

```python
def test_skill_menu_hides_for_other_oa(chat, office, rt):
    # open_chat → 记下某 skill 名
    # 为该 skill PUT/直接写 allow oa=其他账号
    # 再 GET session / skill_menu 路径：items 不含该 skill
    ...

def test_understand_candidate_excludes_hidden_skill_tools(chat, office, rt, model):
    # 配置 allow 仅 alice；用 bob session 发消息选 tool → 不应出现该 tool 调用
    # 或断言 RunContext.tools 不含
    ...
```

（可复用 `tests/test_chat.py` / `test_catalog.py` 夹具：`open_chat`、`make_assertion`、office mock。）

- [ ] **Step 2: 跑测确认失败 → 实现 → 通过**

Run: `pytest tests/test_skill_visibility.py -k "skill_menu or understand or candidate" -q`  
Expected: 实现后 PASS

- [ ] **Step 3: Commit（无 git 则跳过）**

```bash
git add backend/oa_agent/chat/service.py backend/oa_agent/runtime/engine.py backend/oa_agent/runtime/graphs/travel_query.py backend/tests/test_skill_visibility.py
git commit -m "feat(visibility): filter skills in menu and run context"
```

---

### Task 4: Executor 执行前断言 + D7 文案

**Files:**
- Modify: `backend/oa_agent/mcp/executor.py` 与/或 `travel_query.call_tool` 节点
- Modify: `backend/oa_agent/config/schema.py`（默认 `tool_not_available` 文案 →「该功能未对你开放。」）
- Modify: `backend/tests/test_skill_visibility.py`

**Interfaces:**
- 在真正 HTTP 上游调用前：若 tool 所属 Skill 对当前 principal 不可见 → `ToolError("TOOL_NOT_AVAILABLE", ..., user_message=...)` 或图节点返回与现网一致的 `error_code=TOOL_NOT_AVAILABLE`
- 事件可带 `reason=not_visible`；**不**写 token

**注意：** 现网 `executor` 在 Tool 未注册时已抛 `TOOL_NOT_AVAILABLE`。可见性失败须在**有注册**仍拦截，且 `office` mock 的 `call_count == 0`（参考 `tests/test_catalog.py`）。

若 Executor 无 DB/oa 上下文：在 `call_tool` 图节点内、调用 `executor` 前用 `ctx` 的 oa + skills 映射断言（推荐，上下文完整）。

- [ ] **Step 1: 写失败测试**

```python
def test_execute_hidden_tool_returns_not_available_no_upstream(chat, office, rt):
    # skill 对员工不可见，但 registry 仍有 tool（模拟模型硬选）
    # 发消息或直接调 call_tool 路径
    # assert error_code == TOOL_NOT_AVAILABLE
    # assert 「未对你开放」in content 或配置文案
    # assert office route.call_count == 0
```

- [ ] **Step 2: 实现断言 + 更新默认文案**

`schema.py` 中 `_text("tool_not_available", ...)` 的默认员工文案改为「该功能未对你开放。」（已安装库的覆盖配置不强制迁移；交付说明注明）。

- [ ] **Step 3: 跑测通过**

Run: `pytest tests/test_skill_visibility.py::test_execute_hidden_tool_returns_not_available_no_upstream tests/test_catalog.py -q --tb=line`  
Expected: PASS（catalog 回归不破）

- [ ] **Step 4: Commit（无 git 则跳过）**

```bash
git add backend/oa_agent/runtime/graphs/travel_query.py backend/oa_agent/mcp/executor.py backend/oa_agent/config/schema.py backend/tests/test_skill_visibility.py
git commit -m "feat(visibility): block hidden tools before upstream"
```

---

### Task 5: 管理 API + 审计 + preview

**Files:**
- Modify: `backend/oa_agent/admin/catalog_api.py`
- Modify: `backend/tests/test_skill_visibility.py`（或 `test_catalog.py` 扩展）

**Interfaces:**
- `GET /v1/admin/skills/{name}/visibility` — `ops.skill.manage` 读
- `PUT /v1/admin/skills/{name}/visibility` — 写；body：

```json
{
  "reason": "限制仅财务试用",
  "rules": [
    {"effect": "allow", "principal_type": "oa", "principal_value": "alice"},
    {"effect": "deny", "principal_type": "oa", "principal_value": "bob"}
  ]
}
```

- 空 `rules: []` = 删除全部规则（D19=C 恢复不裁剪）
- `GET /v1/admin/visibility/preview?oa=alice` — 返回该 oa 当前可见 skill `name` 列表（tags 空）
- 权限：`Depends(admin_write(SKILL))` / `admin_read(SKILL)`；审计 action 如 `skill.visibility.update`；与变更同事务

- [ ] **Step 1: 写失败 API 测试**

```python
def test_admin_put_visibility_and_preview(admin_client, rt):
    # PUT rules allow oa=alice
    # GET visibility 返回 1 条
    # preview?oa=alice 含 skill；preview?oa=bob 不含
    # PUT rules=[] 后 preview 双方都含（若 skill 本身 available）
```

- [ ] **Step 2: 实现路由（挂在 `skills_router`）**

按 `name` 查 `Skill`；404 用现网 skill 不存在错误。校验每条 rule 字段。`principal_type=all` 时忽略/清空 value。

- [ ] **Step 3: 跑测通过**

Run: `pytest tests/test_skill_visibility.py -k admin -q`  
Expected: PASS

- [ ] **Step 4: Commit（无 git 则跳过）**

```bash
git add backend/oa_agent/admin/catalog_api.py backend/tests/test_skill_visibility.py
git commit -m "feat(visibility): admin GET/PUT visibility and preview"
```

---

### Task 6: 出站 MCP Protocol + Noop

**Files:**
- Create: `backend/oa_agent/mcp/outbound.py`
- Modify: `backend/tests/test_skill_visibility.py`（或 `test_outbound_mcp.py`）

**Interfaces:**

```python
class OutboundMcpClient(Protocol):
    def call_tool(self, name: str, arguments: dict, *, identity: Identity) -> dict: ...

class NoopOutboundMcpClient:
    def call_tool(self, name: str, arguments: dict, *, identity: Identity) -> dict:
        raise ToolError("TOOL_NOT_AVAILABLE", "出站连接器未配置", user_message="该功能未对你开放。")
```

文档字符串写明：地址白名单、禁止泄露 master key/管理会话、结果须白名单后再给模型。本期**无任何**生产路径实例化非 Noop；可不挂路由。

- [ ] **Step 1: 单测 Noop 抛错且不发网络**

```python
def test_noop_outbound_raises():
    from oa_agent.mcp.outbound import NoopOutboundMcpClient
    with pytest.raises(ToolError) as e:
        NoopOutboundMcpClient().call_tool("x", {}, identity=Identity(oa="a", authorization=""))
    assert e.value.code == "TOOL_NOT_AVAILABLE"
```

- [ ] **Step 2: 实现 → PASS → Commit（无 git 则跳过）**

```bash
git add backend/oa_agent/mcp/outbound.py backend/tests/test_skill_visibility.py
git commit -m "feat(mcp): NoopOutboundMcpClient boundary stub"
```

---

### Task 7: 权威设计短更新 + 交付 + 全量测试

**Files:**
- Modify: `docs/design/2026-10-09-oa-langgraph-design.md`（§8.1 用语：执行器/连接器；§12 增加 visibility API 行）
- Create: `docs/delivery/2026-10-23-mcp-skill-visibility-delivery.md`
- Report: `.superpowers/sdd/task-*-report.md`（若走 SDD）

**交付文档必须含：** 功能、文件清单、迁移 `0009`、API、权限与安全、测试结果（自动化通过 / 手工 / 未执行 / 外部依赖）、未完成项（OA 标签、真实 MCP、管理 UI）、下一阶段 **A**。

- [ ] **Step 1: 写交付文档与设计短更新**

- [ ] **Step 2: 全量测试**

```bash
cd backend && .venv\Scripts\python -m pytest -q
cd frontend && npm test && npx vue-tsc --noEmit
```

Expected: backend 全绿；frontend 与 C 无关应仍绿。诚实记录。

- [ ] **Step 3: Commit（无 git 则跳过）**

```bash
git add docs/design/2026-10-09-oa-langgraph-design.md docs/delivery/2026-10-23-mcp-skill-visibility-delivery.md
git commit -m "docs: skill visibility delivery and design API note"
```

---

## Spec coverage checklist

| Spec 项 | Task |
|---------|------|
| 表 + ORM | 1 |
| VisibilityService + D19/deny/tag 空 | 2 |
| TagProvider 空 | 2 |
| 欢迎 / 帮助 / 候选 | 3 |
| 执行前 + D7 文案 | 4 |
| 管理 GET/PUT/preview + 审计 | 5 |
| 出站 MCP Noop | 6 |
| 文档 + 全量测试 + 交付 | 7 |
| 管理 UI | 非目标（不做） |
| OA/真实 MCP 联调 | 非目标（交付标未执行） |

## Self-review notes

- 无 TBD；错误码统一 `TOOL_NOT_AVAILABLE`。
- `SkillState` 若无 `id`：Task 3 用 `name` → DB `Skill.id` 映射，计划已注明。
- 库宕机降级与 E 的 guard 哲学一致，避免再破 `test_monitoring_db_down_*`。
