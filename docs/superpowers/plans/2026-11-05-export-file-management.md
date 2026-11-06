# 导出文件管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 员工导出文件长期登记并可追溯对话；未配 OSS 落本地、配齐则上传阿里云；员工原链接长期有效（本人登录）；后台「文件管理」可列表与下载。

**Architecture:** 新表 `agent_export_file` 为权威索引；`ExportStore` 统一 `put`/`get`（local | oss）；改造 `sys.export` 先写对象再落库；员工与管理员下载均经本服务按行上 `storage` 读字节；系统设置新增 `oss` 组。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、`oss2`、Vue 3 + Element Plus、pytest / vitest。

**Spec:** `docs/superpowers/specs/2026-11-05-export-file-management-design.md`

## Global Constraints

- 与 OA 只走 HTTP；不访问 `td_oa`。
- 密钥只写不读；日志 / 审计 / 异常无 AccessKey Secret 明文；`object_key` 非完整 URL。
- 管理读列表与下载 = `ops.file.view` + 访问即审计；审计失败则请求失败。
- OSS 上传失败不回落本地、不写表行。
- 不返回 OSS 预签名 URL / ticket 给管理端列表。
- 一期无删除；旧 `ticket.json` 不自动导入。
- 回复与文档中文；代码标识符英文。
- 测试不得把未执行说成通过；真实 OSS 标「外部依赖未验证」直至测通。
- Commit 仅在用户明确要求时执行；无 git 时跳过 Commit 步骤。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/migrations/versions/0012_export_file.py` | 建表 + 种子 `ops.file.view` 给 super_admin |
| `backend/oa_agent/db/models.py` | `ExportFile` 模型 |
| `backend/oa_agent/ids.py` | `new_export_file_id()` → `exp_` + ULID |
| `backend/oa_agent/auth/perms.py` | `ops.file.view` |
| `backend/oa_agent/executor/export_store.py` | 本地 / OSS 适配与配置判定（新建） |
| `backend/oa_agent/config/schema.py` | `oss` GroupDef |
| `backend/oa_agent/admin/settings_api.py` | OSS 测试连接 |
| `backend/oa_agent/executor/executor.py` | `Identity` 增加可选 `thread_id` / `run_id` |
| `backend/oa_agent/chat/service.py` | 构造 Identity 时写入 thread/run |
| `backend/oa_agent/executor/builtin_runtime.py` | `_export` / `take_export` 改走表 + store |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | `_file_reply` 文案 |
| `backend/oa_agent/chat/router.py` | 下载 404 文案 |
| `backend/oa_agent/admin/export_files_api.py` | 管理列表 / 下载（新建） |
| `backend/oa_agent/main.py` | include router |
| `backend/pyproject.toml` | 依赖 `oss2` |
| `backend/tests/test_export_store.py` | 存储与导出登记（新建） |
| `backend/tests/test_export_routing.py` | 改一次性断言为可重复下载 |
| `backend/tests/test_admin_export_files.py` | 管理 API（新建） |
| `frontend/src/admin/router.ts` | 菜单「文件管理」 |
| `frontend/src/admin/views/FilesView.vue` | 列表页（新建） |
| `frontend/src/admin/files.ts` + `files.spec.ts` | 类型与跳转辅助 |
| `docs/design/2026-10-09-oa-langgraph-design.md` §9 | 补权限点 |
| `docs/delivery/2026-11-05-export-file-management-delivery.md` | 阶段交付 |

---

### Task 1: 迁移、模型、ID、权限点

**Files:**
- Create: `backend/migrations/versions/0012_export_file.py`
- Modify: `backend/oa_agent/db/models.py`（文末追加 `ExportFile`）
- Modify: `backend/oa_agent/ids.py`
- Modify: `backend/oa_agent/auth/perms.py`
- Test: `backend/tests/test_export_store.py`（本 Task 先测模型可插入 + PERMISSIONS 含新键）

**Interfaces:**
- Produces: `new_export_file_id() -> str`（`exp_` 前缀）
- Produces model `ExportFile` 字段与规格 §3.1 一致：`file_id`, `ticket`, `oa`, `thread_id`, `run_id`, `filename`, `size_bytes`, `content_type`, `storage`, `object_key`, `created_at`, `tenant_id`
- Produces perm: `ops.file.view` = `"导出文件：列表与下载（访问即审计）"`
- Migration `revision = "0012_export_file"`, `down_revision = "0011_tool_kind_mcp_server"`；唯一约束 `uk_export_file_id`、`uk_export_ticket`；索引 `ix_export_created`、`ix_export_oa_created`、`ix_export_thread`；幂等给 super_admin 插 `ops.file.view`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_export_store.py
from oa_agent.auth.perms import PERMISSIONS
from oa_agent.ids import new_export_file_id

def test_export_file_id_prefix():
    assert new_export_file_id().startswith("exp_")

def test_ops_file_view_permission_registered():
    assert "ops.file.view" in PERMISSIONS
```

Run: `cd backend && uv run pytest tests/test_export_store.py::test_export_file_id_prefix tests/test_export_store.py::test_ops_file_view_permission_registered -v`  
Expected: FAIL（函数 / 键不存在）

- [ ] **Step 2: 实现迁移、模型、`new_export_file_id`、perms；再加插入冒烟**

迁移建表列类型参照 `0011`（`BIGINT` / `DT` / `MYSQL_OPTS`）。模型：

```python
class ExportFile(Base):
    __tablename__ = "agent_export_file"
    __table_args__ = (
        sa.UniqueConstraint("file_id", name="uk_export_file_id"),
        sa.UniqueConstraint("ticket", name="uk_export_ticket"),
        sa.Index("ix_export_created", "tenant_id", "created_at"),
        sa.Index("ix_export_oa_created", "tenant_id", "oa", "created_at"),
        sa.Index("ix_export_thread", "tenant_id", "thread_id"),
    )
    # 列同规格 §3.1；thread_id/run_id nullable String(40)
```

冒烟测试用项目既有 DB fixture（与 `test_admin_employees` 相同方式）插入一行并查出。

- [ ] **Step 3: 跑测试 PASS**

Run: `cd backend && uv run pytest tests/test_export_store.py -v`  
Expected: PASS

- [ ] **Step 4: Commit（仅用户要求时）**

```bash
git add backend/migrations/versions/0012_export_file.py backend/oa_agent/db/models.py backend/oa_agent/ids.py backend/oa_agent/auth/perms.py backend/tests/test_export_store.py
git commit -m "$(cat <<'EOF'
feat: add export file table and ops.file.view permission

EOF
)"
```

---

### Task 2: ExportStore（本地 + OSS）与依赖

**Files:**
- Create: `backend/oa_agent/executor/export_store.py`
- Modify: `backend/pyproject.toml`（加 `oss2>=2.18`）
- Modify: `backend/tests/test_export_store.py`
- Run: `cd backend && uv sync`

**Interfaces:**
- Consumes: 无（纯存储）
- Produces:

```python
@dataclass(frozen=True)
class OssConfig:
    endpoint: str
    bucket: str
    prefix: str
    access_key_id: str
    access_key_secret: str

def oss_configured(cfg: OssConfig | None) -> bool: ...

class ExportStore:
    def __init__(self, *, data_dir: Path, tenant_id: str, oss: OssConfig | None = None): ...
    def object_key_for(self, ticket: str) -> str:
        """local: {tenant}/{ticket}.bin；oss: {prefix}/{tenant}/{ticket}.bin（prefix 可空）"""
    def put(self, ticket: str, data: bytes) -> tuple[str, str]:
        """返回 (storage, object_key)；oss 配齐走 OSS，否则 local。OSS put 失败抛 ToolError/AppError 语义错误，不写 local。"""
    def get(self, storage: str, object_key: str) -> bytes:
        """按行上 storage 读取；路径必须落在租户导出根下（local）。"""
    def delete(self, storage: str, object_key: str) -> None:
        """尽力删除（insert 失败回滚用）；忽略不存在。"""
```

- OSS 客户端仅在 `put`/`get`/`delete` 且 `storage==oss` 时懒创建；单测用假客户端注入（`ExportStore(..., oss_client=FakeBucket())`）避免真网。
- `get` local：resolve 后 `Path.resolve()` 必须以 `data_dir/exports/{tenant}` 为前缀，否则拒绝。

- [ ] **Step 1: 失败测试（未配 OSS → local put/get；配齐假客户端 → storage=oss；假客户端 raise → put 失败且本地无文件）**

```python
def test_put_local_when_oss_missing(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=None)
    storage, key = store.put("abcdefghijklmnopqrst", b"hello")
    assert storage == "local"
    assert store.get(storage, key) == b"hello"

def test_put_oss_when_configured(tmp_path):
    calls = []
    class Fake:
        def put_object(self, key, data): calls.append((key, data))
        def get_object(self, key):
            class R: def read(self_inner): return b"from-oss"
            return R()
    cfg = OssConfig("https://oss.example.com", "b", "p", "id", "secret")
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa", oss=cfg, oss_client=Fake())
    storage, key = store.put("abcdefghijklmnopqrst", b"x")
    assert storage == "oss" and key.startswith("p/")
    assert store.get(storage, key) == b"from-oss"
```

Run 期望 FAIL → 实现 → PASS。`uv sync` 装上 `oss2`。

- [ ] **Step 2: Commit（仅用户要求时）**

---

### Task 3: 系统设置 `oss` 组 + 测试连接

**Files:**
- Modify: `backend/oa_agent/config/schema.py`（追加 `GroupDef("oss", ...)`）
- Modify: `backend/oa_agent/admin/settings_api.py`（`_run_test` 支持 `oss`）
- Test: `backend/tests/test_export_store.py` 或新建 `test_oss_settings.py`

**Interfaces:**
- Fields: `endpoint`(url), `bucket`(str), `prefix`(str, default `""`), `access_key_id`(str), `access_key_secret`(secret)
- `testable=True`；`apply_mode` = `"热生效"`
- `_run_test("oss", cfg)`：缺字段 → 422；否则用 `oss2` 对 bucket 做 `get_bucket_info`（或 list 限 1）；成功 `{"ok": True}`；失败 `{"ok": False, "error": redact(msg)}`，**禁止**把 secret 拼进 error
- 帮助文案写明：四项齐（含 secret 已设置）后新导出上传 OSS，否则本地

- [ ] **Step 1: 测试** `GROUPS["oss"]` 字段齐全；`_run_test` 缺 bucket 抛错；mock 成功返回 ok

- [ ] **Step 2: 实现 schema + settings_api 分支**

- [ ] **Step 3: PASS 后 Commit（仅用户要求时）**

---

### Task 4: Identity 带 thread/run + sys.export 登记

**Files:**
- Modify: `backend/oa_agent/executor/executor.py`（`Identity` 加 `thread_id: str | None = None`, `run_id: str | None = None`）
- Modify: `backend/oa_agent/chat/service.py`（`_identity_from_session` 无法知 run；在真正 `execute` 前把当前 run 的 thread/run 写入 Identity —— 见下）
- Modify: `backend/oa_agent/executor/builtin_runtime.py`
- Modify: `backend/oa_agent/executor/builtin_runtime.py` `build_builtin_runtime`：注入 `export_store` 工厂或 settings 回调
- Modify: `backend/tests/test_export_routing.py`（一次性 → 可重复）
- Modify: `backend/tests/test_export_store.py`（导出写表）

**Identity 注入约定（选一，推荐 A）：**

**A（推荐）：** 在 `ToolExecutor.execute` / `_execute_builtin` 调用前，由引擎在构造 Identity 时带上；`chat/service.py` 里创建 run 后：

```python
identity = _identity_from_session(session)
identity = replace(identity, thread_id=session.thread_id, run_id=rec.run_id)
```

（`dataclasses.replace`；凡构造 Identity 跑图处都补 thread/run，缺则保持 None。）

**BuiltinRuntime._export 新流程：**

1. 校验 content / filename / 大小（不变）。
2. `ticket = secrets.token_urlsafe(18)`；`file_id = new_export_file_id()`。
3. `store = self._export_store()`（无 store / 无 session_factory → `_not_available()`）。
4. `storage, object_key = store.put(ticket, data)`。
5. `session_factory` 开事务 insert `ExportFile`（`oa=identity.oa`, `thread_id=identity.thread_id`, `run_id=identity.run_id`, …）。
6. insert 失败 → `store.delete(storage, object_key)` 后重新抛错。
7. 返回 `{"ticket", "filename", "size_bytes", "file_id"}`（无 expires_*）。
8. **删除** 写 `ticket.json`、TTL、`consume_export` 在成功下载路径的调用。

**take_export(ticket, oa):**

1. 查表：`ticket` + `tenant_id`；无行或 `oa` 不匹配 → None。
2. `store.get(row.storage, row.object_key)`；失败 → None。
3. **不**删行、不删对象。
4. 返回 `(bytes, filename)`。

`build_builtin_runtime(rt)`：用 `rt.setting` / `rt.settings_svc.effective` 读 oss 组 + vault secret 拼 `OssConfig`；`data_dir=rt.settings.data_dir`。

- [ ] **Step 1: 改写测试**

```python
def test_take_export_is_owner_only_and_repeatable(tmp_path, db_session_factory):
    # BuiltinRuntime(..., session_factory=..., export 用 ExportStore(tmp_path))
    # alice 导出 → bob None → alice 成功 → alice 再成功；表行仍在
```

原 `test_take_export_is_owner_only_and_one_time` 改名并改断言。

- [ ] **Step 2: 实现 → PASS**

Run: `cd backend && uv run pytest tests/test_export_routing.py tests/test_export_store.py tests/test_builtin_tools.py -v`

- [ ] **Step 3: Commit（仅用户要求时）**

---

### Task 5: 员工下载文案与 404 文案

**Files:**
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py` `_file_reply`
- Modify: `backend/oa_agent/chat/router.py` `download_export`
- Modify: `backend/tests/test_export_routing.py`（`test_export_reply_exposes_download_ticket_not_fence`）

**Interfaces:**
- 文案：`已生成文件 **{filename}**，可下载。`（无「限时」「一次」）
- `data` 仍含 `ticket` / `filename` / `size_bytes`；可含 `file_id`；去掉对 `expires_in` 的展示依赖
- 404 message：`文件不存在`

- [ ] **Step 1: 测试断言 content 不含「一次」「秒内」→ 改实现 → PASS**

- [ ] **Step 2: Commit（仅用户要求时）**

---

### Task 6: 管理端 export-files API

**Files:**
- Create: `backend/oa_agent/admin/export_files_api.py`
- Modify: `backend/oa_agent/main.py`（import + include）
- Create: `backend/tests/test_admin_export_files.py`

**Interfaces:**
- `GET /v1/admin/export-files`：`admin_read("ops.file.view")`；Query：`page`, `page_size`, `oa`, `thread_id`, `filename`（contains）, `start`, `end`；按 `created_at` desc
- 响应 item：**不含** `ticket`、`object_key`；含 `file_id`, `oa`, `thread_id`, `run_id`, `filename`, `size_bytes`, `storage`, `created_at`
- 审计：`export_file.list` 后 `ctx.db.commit()`（同 conversations_api）
- `GET /v1/admin/export-files/{file_id}/download`：流式 `Response`；审计 `export_file.download`；无权限 403；无文件 404「文件不存在」
- 下载用与 BuiltinRuntime 相同的 `ExportStore` 构造方式（可抽 `build_export_store(rt, db)`）

- [ ] **Step 1: 失败测试**

```python
def test_list_requires_perm(client_no_perm): ...
def test_list_and_download_with_audit(admin_client, seeded_export_file):
    r = admin_client.get("/v1/admin/export-files")
    assert r.status_code == 200
    assert "ticket" not in r.json()["items"][0]
    d = admin_client.get(f"/v1/admin/export-files/{file_id}/download")
    assert d.status_code == 200
    # 断言 audit 表有 export_file.list / export_file.download
```

参照 `test_admin_employees.py` 的 client fixture。

- [ ] **Step 2: 实现 API + main include → PASS**

- [ ] **Step 3: Commit（仅用户要求时）**

---

### Task 7: 后台「文件管理」前端

**Files:**
- Create: `frontend/src/admin/views/FilesView.vue`
- Create: `frontend/src/admin/files.ts`
- Create: `frontend/src/admin/files.spec.ts`
- Modify: `frontend/src/admin/router.ts`（monitor 组增加一项）
- Modify: `frontend/src/admin/console/menuGroups.spec.ts`（若写死叶子则补路径）

**Interfaces:**
- 菜单：`path: '/files'`, `title: '文件管理'`, `code: 'FILES'`, `perm: 'ops.file.view'`, `group: 'monitor'`, icon 用 `Folder` 或 `Document`（与现有 `@element-plus/icons-vue` 一致）
- 列表调 `GET /v1/admin/export-files`；筛选 oa / thread_id / filename；空态 `NO_DATA`
- 下载：`window.open` 或 `fetch`+blob（credentials same-origin）`/v1/admin/export-files/{file_id}/download`
- 「查看对话」：`router.push({ path: '/conversations', query: { thread: row.thread_id } })`；无 thread_id 禁用

`files.spec.ts`：

```typescript
import { conversationLink } from './files'
expect(conversationLink('thr_1')).toEqual({ path: '/conversations', query: { thread: 'thr_1' } })
expect(conversationLink(null)).toBeNull()
```

- [ ] **Step 1: Vitest 失败 → 实现 helper + 视图 + 路由 → `npm run test` 相关 PASS**

- [ ] **Step 2: Commit（仅用户要求时）**

---

### Task 8: 权威设计 §9 与交付说明

**Files:**
- Modify: `docs/design/2026-10-09-oa-langgraph-design.md` §9 表追加 `ops.file.view`；配置中心段落可一句提 `oss` 组（勿扩写 P5）
- Create: `docs/delivery/2026-11-05-export-file-management-delivery.md`

交付须含：功能、文件清单、迁移说明、API、权限与安全、测试结果（区分自动化 / 手工 / 未执行 / 外部依赖未验证）、未完成项（旧票据不迁移、无删除）、下一阶段（可选清理策略）。

- [ ] **Step 1: 写交付文档并更新 §9**

- [ ] **Step 2: 全量相关测试**

```bash
cd backend && uv run pytest tests/test_export_store.py tests/test_export_routing.py tests/test_admin_export_files.py tests/test_builtin_tools.py -q
cd ../frontend && npm run test -- --run src/admin/files.spec.ts src/admin/console/menuGroups.spec.ts
```

- [ ] **Step 3: Commit（仅用户要求时）**

---

## Spec coverage checklist

| 规格项 | Task |
|--------|------|
| D1 长期保留 | 4 |
| D2 员工链接长期 + 本人 | 4、5 |
| 方案 1 表 + 存储接口 | 1、2、4 |
| OSS 配齐上传 / 未配本地 | 2、3、4 |
| 上传失败不回落 | 2、4 |
| 后台列表追溯对话 | 6、7 |
| 后台下载转发 | 6 |
| `ops.file.view` + 审计 | 1、6 |
| 密钥只写不读 | 3 |
| 旧票据不导入 | 8 交付说明 |
| 文案去掉限时/一次 | 5 |
| 不暴露 ticket/object_key 给管理列表 | 6 |

## Self-review notes

- 无 TBD；Identity 注入约定写死为 dataclasses.replace。
- `take_export` 与 admin download 都经 `ExportStore.get`，按行上 `storage`。
- `oss2` 入主依赖；单测不打真网。
