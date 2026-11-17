# LLM 模型默认、分类与同池顺延 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后台模型支持能力分类与大小档、全局默认、按「能力×规模」独立路由池，以及配置跳过 + 运行失败有限顺延。

**Architecture:** 扩展 `LlmModel`（`capabilities` / `model_tier`）；新建 `LlmRoute`（有序 `model_ids`）与 `LlmDefaults`（全局默认 + `max_failover`）。`resolve_model` / `resolve_candidates` 按规格 §4 选模；`invoke_*` 仅对传输/提供方错误顺延。管理端 API + `LlmView` 提供设默认与路由池编辑；路由阶段默认走 `(text, small)`。

**Tech Stack:** FastAPI / SQLAlchemy / Alembic / Vue3 + Element Plus / pytest（oa-langGraph）。

**Spec:** `docs/superpowers/specs/2026-11-17-llm-model-routing-design.md`

## Global Constraints

- 能力枚举固定：`text` / `vision` / `multimodal` / `embedding`（模型多选）。
- 规模单选：`large` / `small`；缺省 `capabilities=["text"]`、`model_tier="large"`。
- 全局默认每租户最多 1 个；route 唯一键 `(tenant_id, capability, model_tier)`。
- 运行顺延仅传输/提供方错误；非法 JSON **不**换模型；`max_failover` 默认 3（含首次）。
- 未配 route / 未设默认时兼容旧 `purpose_tags` → 首个启用模型。
- 回复与文档中文；代码标识符英文。
- **Commit 仅在用户明确要求时执行**；计划中的 commit 步骤默认跳过，改为本地验证通过即可。
- 测试命令在 `backend` 目录：`uv run pytest … -v`。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/oa_agent/db/models.py` | `LlmModel` 加字段；新建 `LlmRoute`、`LlmDefaults` |
| `backend/migrations/versions/0017_llm_model_routing.py` | 列 + 两表 + 种子全局默认 |
| `backend/oa_agent/runtime/llm.py` | `ModelConfig.model_id`；`resolve_model` / `resolve_candidates`；failover 封装 |
| `backend/oa_agent/admin/llm_api.py` | models 字段扩展；defaults / routes / set-default |
| `backend/oa_agent/chat/service.py` | `_model` / `_router_model` 走新解析（router → text+small） |
| `frontend/src/admin/views/LlmView.vue` | 能力/规模/默认按钮/路由池 UI |
| `backend/tests/test_llm_routing.py` | 解析链 + 顺延 + API |
| `backend/tests/test_llm.py` | 创建模型时带新字段的冒烟（可选小改） |

---

### Task 1: ORM + Alembic 0017

**Files:**
- Modify: `backend/oa_agent/db/models.py`（`LlmModel` 与新表，紧接现有 `LlmModel`）
- Create: `backend/migrations/versions/0017_llm_model_routing.py`
- Test: `backend/tests/test_migrations.py`（已有 head 对比；迁移后应无 diff）

**Interfaces:**
- Produces:
  - `LlmModel.capabilities: list`（JSON，默认 `["text"]`）
  - `LlmModel.model_tier: str`（默认 `"large"`）
  - `LlmRoute(tenant_id, capability, model_tier, model_ids, enabled, …)`
  - `LlmDefaults(tenant_id, global_default_model_id, max_failover, …)`
- Consumes: 现有 `BigIntPK` / `UtcDateTime` / `DEFAULT_TENANT`

- [ ] **Step 1: 扩展 `LlmModel` 并新增两表**

在 `class LlmModel` 的 `purpose_tags` 后插入：

```python
capabilities: Mapped[list] = mapped_column(sa.JSON, default=lambda: ["text"])
model_tier: Mapped[str] = mapped_column(sa.String(16), default="large")
```

在 `LlmModel` 类后新增：

```python
class LlmRoute(Base):
    __tablename__ = "agent_llm_route"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "capability", "model_tier", name="uk_llm_route_cap_tier"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    capability: Mapped[str] = mapped_column(sa.String(32))
    model_tier: Mapped[str] = mapped_column(sa.String(16))
    model_ids: Mapped[list] = mapped_column(sa.JSON, default=list)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class LlmDefaults(Base):
    __tablename__ = "agent_llm_defaults"
    __table_args__ = (sa.UniqueConstraint("tenant_id", name="uk_llm_defaults_tenant"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(32), default=DEFAULT_TENANT)
    global_default_model_id: Mapped[int | None] = mapped_column(BigIntPK, nullable=True)
    max_failover: Mapped[int] = mapped_column(sa.Integer, default=3)
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)
```

- [ ] **Step 2: 写迁移 `0017_llm_model_routing.py`**

```python
"""LLM 能力/规模、路由池与全局默认。

Revision ID: 0017_llm_model_routing
Revises: 0016_skill_market_review
Create Date: 2026-11-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0017_llm_model_routing"
down_revision = "0016_skill_market_review"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
DT = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_OPTS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci", "mysql_engine": "InnoDB"}


def upgrade() -> None:
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("agent_llm_model")}
    if "capabilities" not in cols:
        op.add_column(
            "agent_llm_model",
            sa.Column("capabilities", sa.JSON(), nullable=True),
        )
    if "model_tier" not in cols:
        op.add_column(
            "agent_llm_model",
            sa.Column("model_tier", sa.String(16), nullable=False, server_default="large"),
        )
    # 回填 capabilities 空值
    conn.execute(sa.text(
        "UPDATE agent_llm_model SET capabilities = :cap WHERE capabilities IS NULL"
    ), {"cap": '["text"]'})

    if "agent_llm_route" not in sa.inspect(conn).get_table_names():
        op.create_table(
            "agent_llm_route",
            sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
            sa.Column("capability", sa.String(32), nullable=False),
            sa.Column("model_tier", sa.String(16), nullable=False),
            sa.Column("model_ids", sa.JSON, nullable=True),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("created_at", DT, nullable=False),
            sa.Column("updated_at", DT, nullable=False),
            sa.UniqueConstraint("tenant_id", "capability", "model_tier", name="uk_llm_route_cap_tier"),
            **MYSQL_OPTS,
        )

    if "agent_llm_defaults" not in sa.inspect(conn).get_table_names():
        op.create_table(
            "agent_llm_defaults",
            sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(32), nullable=False, server_default="dscpa"),
            sa.Column("global_default_model_id", BIGINT, nullable=True),
            sa.Column("max_failover", sa.Integer, nullable=False, server_default="3"),
            sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
            sa.Column("updated_at", DT, nullable=False),
            sa.UniqueConstraint("tenant_id", name="uk_llm_defaults_tenant"),
            **MYSQL_OPTS,
        )

    # 每租户：无 defaults 行则插入；global 为空则种子第一个启用模型
    tenants = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT tenant_id FROM agent_llm_model"
    )).fetchall()]
    if not tenants:
        tenants = ["dscpa"]
    for tid in tenants:
        row = conn.execute(sa.text(
            "SELECT id, global_default_model_id FROM agent_llm_defaults WHERE tenant_id = :t"
        ), {"t": tid}).first()
        mid = conn.execute(sa.text(
            "SELECT id FROM agent_llm_model WHERE tenant_id = :t AND enabled = 1 "
            "ORDER BY id LIMIT 1"
        ), {"t": tid}).scalar()
        if row is None:
            conn.execute(sa.text(
                "INSERT INTO agent_llm_defaults "
                "(tenant_id, global_default_model_id, max_failover, updated_by, updated_at) "
                "VALUES (:t, :m, 3, 'migration', CURRENT_TIMESTAMP)"
            ), {"t": tid, "m": mid})
        elif row[1] is None and mid is not None:
            conn.execute(sa.text(
                "UPDATE agent_llm_defaults SET global_default_model_id = :m "
                "WHERE tenant_id = :t AND global_default_model_id IS NULL"
            ), {"t": tid, "m": mid})


def downgrade() -> None:
    op.drop_table("agent_llm_defaults")
    op.drop_table("agent_llm_route")
    conn = op.get_bind()
    cols = {c["name"] for c in sa.inspect(conn).get_columns("agent_llm_model")}
    if "model_tier" in cols:
        op.drop_column("agent_llm_model", "model_tier")
    if "capabilities" in cols:
        op.drop_column("agent_llm_model", "capabilities")
```

（SQLite 下 `enabled = 1` / `CURRENT_TIMESTAMP` 与项目既有迁移风格对齐；若测试失败按 `0012`/`0016` 惯用写法微调。）

- [ ] **Step 3: 跑迁移相关测试**

Run: `cd backend && uv run pytest tests/test_migrations.py -v`  
Expected: PASS（metadata 与 DB 无多余 diff）

- [ ] **Step 4: Commit（仅用户要求时）** — 跳过除非用户明确要求。

---

### Task 2: `resolve_model` / `resolve_candidates`

**Files:**
- Modify: `backend/oa_agent/runtime/llm.py`
- Create: `backend/tests/test_llm_routing.py`

**Interfaces:**
- Produces:
  - `CAPABILITIES = ("text", "vision", "multimodal", "embedding")`
  - `ModelConfig` 增加 `model_id: int`
  - `resolve_model(db, vault, tenant_id, model_id=None, *, purpose="intent", capability=None, model_tier=None) -> ModelConfig | None`
  - `resolve_candidates(db, vault, tenant_id, model_id=None, *, capability=None, model_tier=None, purpose="intent") -> list[ModelConfig]`（长度 ≤ `max_failover`，已过滤配置可用）
- Consumes: `LlmModel` / `LlmProvider` / `LlmRoute` / `LlmDefaults`

- [ ] **Step 1: 写失败测试（解析优先级）**

`backend/tests/test_llm_routing.py`：

```python
from oa_agent.db.models import LlmDefaults, LlmModel, LlmProvider, LlmRoute
from oa_agent.runtime.llm import resolve_candidates, resolve_model


def _seed_two_models(admin):
    p = admin.post("/v1/admin/llm/providers", json={
        "name": "p1", "base_url": "https://llm.example.com/v1", "api_key": "sk-test-KEY9",
    }).json()
    m1 = admin.post("/v1/admin/llm/models", json={
        "provider_id": p["id"], "model_name": "big", "capabilities": ["text"],
        "model_tier": "large", "purpose_tags": ["intent"],
    }).json()
    m2 = admin.post("/v1/admin/llm/models", json={
        "provider_id": p["id"], "model_name": "small", "capabilities": ["text"],
        "model_tier": "small",
    }).json()
    return p, m1, m2


def test_global_default_when_unspecified(admin, installed):
    _, m1, m2 = _seed_two_models(admin)
    admin.post(f"/v1/admin/llm/models/{m2['id']}/set-default")
    rt = installed.app.state.runtime  # 若属性路径不同，用项目 conftest/runtime 惯用取法
    with rt.session() as db:
        cfg = resolve_model(db, rt.vault, rt.tenant_id, None)
    assert cfg is not None and cfg.model_id == m2["id"]


def test_route_pool_text_small(admin, installed):
    _, m1, m2 = _seed_two_models(admin)
    admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "small", "model_ids": [m2["id"]], "enabled": True,
    })
    rt = installed.app.state.runtime
    with rt.session() as db:
        cfg = resolve_model(db, rt.vault, rt.tenant_id, None, capability="text", model_tier="small")
    assert cfg.model_id == m2["id"]
```

> 若 `installed.app.state.runtime` 不存在：在测试里 `from oa_agent.runtime_state import get_runtime` 或项目现有 helper；实现前先 `rg "app.state" backend/tests` 对齐取 runtime 方式。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_llm_routing.py::test_global_default_when_unspecified -v`  
Expected: FAIL（无 set-default 或 resolve 未读 defaults）

- [ ] **Step 3: 实现解析（`llm.py`）**

核心逻辑（完整写入文件，替换旧 `resolve_model`）：

```python
CAPABILITIES = ("text", "vision", "multimodal", "embedding")
TIERS = ("large", "small")


@dataclass(frozen=True)
class ModelConfig:
    model_id: int
    provider_name: str
    base_url: str
    api_key: str | None
    timeout: int
    model_name: str
    params: dict
    capabilities: tuple[str, ...] = ()
    model_tier: str = "large"


def _has_key(vault, db, provider: LlmProvider) -> bool:
    return bool(vault.reveal(db, provider.secret_ref))


def _to_cfg(m: LlmModel, p: LlmProvider, vault, db) -> ModelConfig:
    caps = tuple(m.capabilities or ["text"])
    return ModelConfig(
        m.id, p.name, p.base_url, vault.reveal(db, p.secret_ref),
        p.timeout_seconds, m.model_name, dict(m.params_json or {}),
        caps, m.model_tier or "large",
    )


def _load_defaults(db, tenant_id: str) -> LlmDefaults | None:
    return db.scalar(sa.select(LlmDefaults).where(LlmDefaults.tenant_id == tenant_id))


def _config_ok(m: LlmModel, p: LlmProvider, vault, db) -> bool:
    return bool(m.enabled and p.enabled and _has_key(vault, db, p))


def resolve_candidates(
    db: Session, vault: SecretVault, tenant_id: str, model_id: int | None = None, *,
    purpose: str = INTENT_PURPOSE, capability: str | None = None, model_tier: str | None = None,
) -> list[ModelConfig]:
    defaults = _load_defaults(db, tenant_id)
    limit = (defaults.max_failover if defaults else 3) or 3
    rows = db.execute(
        sa.select(LlmModel, LlmProvider)
        .join(LlmProvider, LlmProvider.id == LlmModel.provider_id)
        .where(LlmModel.tenant_id == tenant_id)
        .order_by(LlmModel.id)
    ).all()
    by_id = {m.id: (m, p) for m, p in rows}

    def ok_pair(pair):
        m, p = pair
        return _config_ok(m, p, vault, db)

    ordered_ids: list[int] = []

    # 1) 显式 ID
    if model_id is not None and model_id in by_id:
        m, p = by_id[model_id]
        if ok_pair((m, p)):
            ordered_ids.append(model_id)
        # 同池后续见 _append_route_after
        _append_route_after(ordered_ids, db, tenant_id, m, capability, by_id, ok_pair)
    elif capability and model_tier:
        _append_route(ordered_ids, db, tenant_id, capability, model_tier, by_id, ok_pair)
    else:
        # 全局默认
        gid = defaults.global_default_model_id if defaults else None
        if gid and gid in by_id and ok_pair(by_id[gid]):
            ordered_ids.append(gid)
        if not ordered_ids:
            # purpose_tags
            for m, p in rows:
                if purpose in (m.purpose_tags or []) and ok_pair((m, p)):
                    ordered_ids.append(m.id)
                    break
        if not ordered_ids:
            for m, p in rows:
                if ok_pair((m, p)):
                    ordered_ids.append(m.id)
                    break

    out: list[ModelConfig] = []
    seen = set()
    for mid in ordered_ids:
        if mid in seen or mid not in by_id:
            continue
        seen.add(mid)
        if not ok_pair(by_id[mid]):
            continue
        out.append(_to_cfg(*by_id[mid], vault, db))
        if len(out) >= limit:
            break
    return out


def resolve_model(db, vault, tenant_id, model_id=None, purpose=INTENT_PURPOSE,
                  capability=None, model_tier=None) -> ModelConfig | None:
    cands = resolve_candidates(
        db, vault, tenant_id, model_id, purpose=purpose,
        capability=capability, model_tier=model_tier,
    )
    return cands[0] if cands else None
```

实现 `_append_route` / `_append_route_after` 时严格按 spec §4.4（capability 固定顺序 `text → vision → multimodal → embedding`）。

**兼容：** 所有现有 `resolve_model(...)` 调用保持位置参数兼容；新增关键字参数。

- [ ] **Step 4: 跑解析测试**

Run: `cd backend && uv run pytest tests/test_llm_routing.py -v -k "default or route_pool"`  
Expected: PASS（Task 3 的 API 若尚未实现，本任务测试可先直接写 DB 种子，待 Task 3 再改用 HTTP）

> 若 set-default API 尚未存在：本任务测试用 `db.add(LlmDefaults(...))` 种子，Task 3 再加 HTTP 用例。

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 3: Admin API — defaults / routes / set-default / 模型字段

**Files:**
- Modify: `backend/oa_agent/admin/llm_api.py`
- Modify: `backend/tests/test_llm_routing.py`（补 API 用例）
- Modify: `backend/tests/test_llm.py`（创建模型断言 `capabilities` / `model_tier` 默认值）

**Interfaces:**
- Produces HTTP:
  - `POST /v1/admin/llm/models/{id}/set-default` → `{...defaults}`
  - `GET/PUT /v1/admin/llm/defaults`
  - `GET /v1/admin/llm/routes` → `{items: [...]}`
  - `PUT /v1/admin/llm/routes` body `{capability, model_tier, model_ids, enabled}` → route + `warnings: []`
  - `DELETE /v1/admin/llm/routes/{capability}/{model_tier}`
  - `ModelIn` 增加 `capabilities: list[str]`、`model_tier: Literal["large","small"]`
- Consumes: Task 1 表；审计 `ctx.audit`

- [ ] **Step 1: 写 API 失败测试**

```python
def test_set_default_and_list_defaults(admin):
    p = admin.post("/v1/admin/llm/providers", json={
        "name": "p1", "base_url": "https://llm.example.com/v1", "api_key": "sk-x",
    }).json()
    m = admin.post("/v1/admin/llm/models", json={
        "provider_id": p["id"], "model_name": "a",
    }).json()
    assert m["capabilities"] == ["text"] and m["model_tier"] == "large"
    r = admin.post(f"/v1/admin/llm/models/{m['id']}/set-default")
    assert r.status_code == 200
    d = admin.get("/v1/admin/llm/defaults").json()
    assert d["global_default_model_id"] == m["id"]
    assert d["max_failover"] == 3


def test_put_route_warns_mismatch(admin):
    p = admin.post("/v1/admin/llm/providers", json={
        "name": "p1", "base_url": "https://llm.example.com/v1", "api_key": "sk-x",
    }).json()
    m = admin.post("/v1/admin/llm/models", json={
        "provider_id": p["id"], "model_name": "v", "capabilities": ["vision"], "model_tier": "large",
    }).json()
    r = admin.put("/v1/admin/llm/routes", json={
        "capability": "text", "model_tier": "large", "model_ids": [m["id"]], "enabled": True,
    })
    assert r.status_code == 200
    assert r.json()["warnings"]  # 能力不符警告
```

- [ ] **Step 2: 跑测确认失败** → Expected: 404/422

- [ ] **Step 3: 实现 API**

`ModelIn`：

```python
class ModelIn(BaseModel):
    provider_id: int
    model_name: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    purpose_tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=lambda: ["text"])
    model_tier: Literal["large", "small"] = "large"
    enabled: bool = True
```

`_apply_model` 校验 capabilities ⊆ 允许集合，去重保序；写入 `m.capabilities` / `m.model_tier`。  
`_model_view` 增加字段，并用 defaults 行标注 `is_default: bool`。

新增 endpoints（权限同现有 models 写/读）。`set-default`：upsert `LlmDefaults`，审计 `llm.model.set_default`。  
`PUT /routes`：校验 `model_ids` 均属本租户；不符能力/规模写入 `warnings` 仍 200。

- [ ] **Step 4: 跑测**

Run: `cd backend && uv run pytest tests/test_llm_routing.py tests/test_llm.py -v`  
Expected: PASS

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 4: 运行失败顺延

**Files:**
- Modify: `backend/oa_agent/runtime/llm.py`（`invoke_json` / 新 helper）
- Modify: `backend/tests/test_llm_routing.py`

**Interfaces:**
- Produces:
  - `is_provider_error(exc: BaseException) -> bool` — True 仅当传输/提供方错误（`ModelCallError` 且非「模型输出不是合法 JSON」）
  - `invoke_json_failover(candidates: list[tuple[chat_model, ModelConfig]], messages, rec, node_name, **kwargs) -> dict`  
    对每个候选调用现有 `invoke_json`；provider error 则试下一个；非法 JSON 立即抛出
- Consumes: `resolve_candidates`、现有 `invoke_json`

- [ ] **Step 1: 写顺延测试（mock chat model）**

```python
from oa_agent.runtime.llm import ModelCallError, ModelConfig, invoke_json_failover


class Boom:
    def invoke(self, messages):
        raise ConnectionError("down")


class Ok:
    def invoke(self, messages):
        class R:
            content = '{"reply":"hi"}'
            response_metadata = {}
            usage_metadata = None
        return R()


def test_failover_skips_provider_error(monkeypatch):
    # 用最小 RunRecorder stub；或 monkeypatch _LoggedCall
    c1 = ModelConfig(1, "p", "http://x", "k", 30, "a", {})
    c2 = ModelConfig(2, "p", "http://x", "k", 30, "b", {})
    # 构造 recorder stub 后：
    # out = invoke_json_failover([(Boom(), c1), (Ok(), c2)], [("user", "hi")], rec, "understand")
    # assert out["reply"] == "hi"
    ...
```

补全 stub 时对齐 `RunRecorder` 最小接口（`model_call_count` / `model_logs` / `usages` / `event`）。

另测：`OkJsonInvalid` 抛 `ModelCallError("模型输出不是合法 JSON")` → **不**试第二个。

- [ ] **Step 2: 实现 `invoke_json_failover`**

```python
def is_provider_error(exc: BaseException) -> bool:
    if not isinstance(exc, ModelCallError):
        return True  # 原始连接错误在 raise ModelCallError 之前也可能出现；统一在 invoke 内转换
    msg = str(exc)
    return "模型输出不是合法 JSON" not in msg and "模型没有输出内容" not in msg


def invoke_json_failover(pairs, messages, rec, node_name, **kwargs):
    last: Exception | None = None
    for i, (chat_model, cfg) in enumerate(pairs):
        try:
            parsed = invoke_json(chat_model, cfg, messages, rec, node_name, **kwargs)
            if i > 0 and rec.model_logs:
                rec.model_logs[-1].setdefault("failover_from", pairs[0][1].model_id)
                rec.model_logs[-1]["attempt"] = i + 1
            return parsed
        except ModelCallError as exc:
            last = exc
            if not is_provider_error(exc) or i == len(pairs) - 1:
                raise
            continue
    assert last is not None
    raise last
```

- [ ] **Step 3: 在 `chat/service.py` 组装候选并交给 graph**

`_model` 改为返回 `(chat, cfg)` 仍兼容；另增 `_model_pairs(rt, config, *, capability=None, model_tier=None, model_id=None)` → `list[tuple]`。  
`_router_model`：若无 `router_model_id`，则 `resolve_candidates(..., capability="text", model_tier="small")`；空则 `None`（回退主模型，与今天一致）。

Graph 内调用点：优先在 `oa_assistant` 组装 model 处改为 failover（若改动面过大，可先只在 `invoke_json` 调用包装一层，把 `ctx.model` 扩成 `ctx.model_pairs`）。**最小可交付：** `chat/service.py` 注入 `model_pairs`；`oa_assistant` understand/chat 使用 `invoke_json_failover`。

- [ ] **Step 4: 跑测**

Run: `cd backend && uv run pytest tests/test_llm_routing.py -v`  
Expected: PASS

- [ ] **Step 5: Commit（仅用户要求时）**

---

### Task 5: 前端 `LlmView.vue`

**Files:**
- Modify: `frontend/src/admin/views/LlmView.vue`

**Interfaces:**
- Consumes: Task 3 API
- Produces: UI — 能力多选、规模单选、设为默认、路由池编辑、`max_failover`

- [ ] **Step 1: 模型表单与列**

- `mForm` 增加 `capabilities: string[]`（默认 `['text']`）、`model_tier: 'large'|'small'`。  
- 表格列：能力、规模、默认（星标/`is_default`）。  
- 操作列增加「设为默认」→ `POST .../set-default` + confirm。  
- 用途标签输入可保留，标签改为次要（placeholder 提示兼容）。

能力选项常量：

```ts
const CAP_OPTIONS = [
  { value: 'text', label: '文本' },
  { value: 'vision', label: '视觉' },
  { value: 'multimodal', label: '多模态' },
  { value: 'embedding', label: 'Embedding' },
]
```

- [ ] **Step 2: 路由与 defaults 卡片**

同页新增 `el-card`「模型路由」：

- 加载 `GET /defaults`、`GET /routes`。  
- 顶栏：`max_failover` 数字框 + 保存 → `PUT /defaults`。  
- 列表：capability × tier；编辑对话框：多选本能力+规模的模型，上下移动排序，保存 `PUT /routes`。  
- 展示 `warnings`（若有）。

- [ ] **Step 3: 手动点检清单（无 E2E 则文档勾选）**

1. 新增模型默认 text/large。  
2. 设为默认后列表有标记；另一模型再设则覆盖。  
3. 建 `(text, small)` 池并排序。  
4. 把 vision 模型拖进 text 池 → 保存有警告但仍成功。

- [ ] **Step 4: Commit（仅用户要求时）**

---

### Task 6: 收尾验证与交付回写

**Files:**
- Create（可选）: `docs/delivery/2026-11-17-llm-model-routing-delivery.md`
- Modify: spec 状态行改为「已交付」当且仅当测试通过

- [ ] **Step 1: 全量相关测试**

Run:

```bash
cd backend
uv run pytest tests/test_llm.py tests/test_llm_routing.py tests/test_migrations.py -v
```

Expected: 全部 PASS

- [ ] **Step 2: 冒烟旧聊天路径**（有 fixture 的）

Run: `uv run pytest tests/test_agent_chat.py -v -k "llm or model" --maxfail=3`  
（若无匹配用例则跑 `tests/test_agent_chat.py` 中与 resolve_model monkeypatch 相关的子集，确认签名兼容。）

- [ ] **Step 3: 写 delivery 短文**（目标 / 文件 / 测试命令 / 已知限制）

- [ ] **Step 4: 请用户验收后台页与路由阶段小模型行为**

---

## Spec coverage checklist

| Spec 项 | Task |
|---------|------|
| `capabilities` / `model_tier` | 1, 3, 5 |
| `agent_llm_route` / `agent_llm_defaults` | 1, 3 |
| 全局默认按钮 | 3, 5 |
| 解析顺序 §4.1 | 2 |
| 配置可用 §4.2 | 2 |
| 运行顺延 §4.3–4.4 | 4 |
| router → `(text, small)` §4.5 | 4 |
| API §5 | 3 |
| UI §6 | 5 |
| 迁移种子 §7 | 1 |
| 测试 §8 | 2–4, 6 |
| 范围外 §9 | 不做 |

## Self-review notes

- 无 TBD；`installed.app.state.runtime` 取法需实现时与 conftest 对齐（已标注）。  
- `ModelConfig` 增加 `model_id` 后，所有构造处（含测试 monkeypatch `CFG`）需补字段，Task 4/6 回归 `test_agent_chat`。  
- Commit 步骤默认跳过，服从用户规则。
