# Tool Schema 编辑器 UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「接入业务接口向导」与「编辑 Tool」能编辑任意深度参数/返回 schema，向导试调可按 schema 填 array/object/file（含临时上传），返回支持一层点路径投影。

**Architecture:** 后端将 `model_params` / `result.schema` 规范为受控递归 SchemaNode；`_pick` 支持一层点路径。前端抽出 `schemaTree.ts` + `SchemaTreeEditor`（左树右栏 + JSON）与 `SchemaValueEditor`（试调），向导与编辑页共用树编辑器；新建 `upload-temp` 供 file 试调。

**Tech Stack:** FastAPI / pytest（`oa-langGraph/backend`）；Vue 3 + Element Plus + Vitest（`frontend/src/admin`）。

**Spec:** `docs/superpowers/specs/2026-11-17-tool-schema-editor-ux-design.md`

## Global Constraints

- 只改 `E:\python_project\oa-langGraph`；不改 PHP / oa-agent-chat。
- Schema 受控子集：`string|integer|number|boolean|object|array|file` + `properties`/`items`/`accept`；深度 ≤ 8；无 oneOf/anyOf/tuple items。
- `file.multiple` 落库统一为 `array` + `items.type=file`；UI 可显示「多文件」开关。
- 返回 `fields`/`list_columns` 最多一层点路径；`result.schema` 不参与裁剪。
- 编辑 Tool 不做试调；试调仅向导。
- 旧 Tool 无嵌套时行为不变；禁止再把 `array|object|file` 冲成 `string`。
- 中文回复；标识符英文。Commit **仅在用户明确要求时**执行（步骤里写了 commit 则先 `git add`，未授权则停）。
- 测试不得把未跑过的说成通过。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/oa_agent/executor/catalog.py` | SchemaNode 递归规范化；`FIELD_RE` / `RESULT_FIELD_RE`；`result.schema`；`file.multiple`→array |
| `backend/oa_agent/executor/executor.py` | `_pick` 一层点路径；`validate_args` 对声明的 properties/items 粗检 |
| `backend/oa_agent/admin/catalog_api.py` | `ToolResultIn.schema`；`POST .../export-wizard/upload-temp` |
| `backend/oa_agent/admin/wizard_temp_upload.py` | **新建** 临时文件落盘与 ref |
| `backend/tests/test_schema_node.py` | **新建** 规范化 / multiple / 深度 / 点路径字段 |
| `backend/tests/test_pick_dotted.py` | **新建** `_pick` / compact |
| `backend/tests/test_wizard_upload_temp.py` | **新建** upload-temp API |
| `frontend/src/admin/schemaTree.ts` | **新建** SchemaNode 类型、normalize、tree↔JSON、multiple 互转 |
| `frontend/src/admin/schemaTree.spec.ts` | **新建** 纯函数单测 |
| `frontend/src/admin/schemaValue.ts` | **新建** 按 schema 组试调 args、路径取值保留 |
| `frontend/src/admin/schemaValue.spec.ts` | **新建** |
| `frontend/src/admin/components/SchemaTreeEditor.vue` | **新建** 左树右栏 + JSON |
| `frontend/src/admin/components/SchemaValueEditor.vue` | **新建** 试调表单 + file 上传 |
| `frontend/src/admin/catalogForm.ts` | ToolForm 改为持有完整 `model_params` + `result.schema`；不再冲类型 |
| `frontend/src/admin/catalogForm.spec.ts` | 嵌套往返、不冲类型 |
| `frontend/src/admin/views/ToolsView.vue` | 向导/编辑挂载两组件；删浅层 array KV 逻辑 |

---

### Task 1: 后端 SchemaNode 规范化

**Files:**
- Modify: `backend/oa_agent/executor/catalog.py`
- Create: `backend/tests/test_schema_node.py`

**Interfaces:**
- Produces:
  - `SCHEMA_MAX_DEPTH = 8`
  - `RESULT_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")`
  - `_normalize_param(name, rule, errors, op, depth=0) -> dict`（递归）
  - 规范化后单文件 `file`+`multiple:true` → `{"type":"array","items":{"type":"file",...},"label":...}`
- Consumes: 现有 `PARAM_TYPES`、`normalize_operation`

- [ ] **Step 1: 写失败单测**

```python
# backend/tests/test_schema_node.py
from oa_agent.executor.catalog import normalize_operation

def _op(model_params, result=None):
    return {
        "operationId": "demo_tool",
        "summary": "d",
        "x-agent": {
            "enabled": True,
            "risk_level": "low",
            "timeout_seconds": 10,
            "upstream": "open_oa",
            "model_params": model_params,
            "result": result or {"kind": "object", "fields": ["id"], "labels": {"id": "ID"}, "list_columns": []},
        },
    }

def test_nested_object_and_array_items_preserved():
    spec, errors = normalize_operation("/x", "get", _op({
        "payload": {
            "type": "object",
            "label": "体",
            "properties": {
                "user": {"type": "object", "properties": {"name": {"type": "string", "required": True}}},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        }
    }))
    assert errors == []
    p = spec["model_params"]["payload"]
    assert p["properties"]["user"]["properties"]["name"]["type"] == "string"
    assert p["properties"]["tags"]["items"]["type"] == "string"

def test_file_multiple_normalizes_to_array_of_file():
    spec, errors = normalize_operation("/x", "get", _op({
        "attach": {"type": "file", "multiple": True, "accept": [".pdf"], "label": "附件"},
    }))
    assert errors == []
    a = spec["model_params"]["attach"]
    assert a["type"] == "array"
    assert a["items"]["type"] == "file"
    assert a["items"]["accept"] == [".pdf"]
    assert "multiple" not in a

def test_depth_over_8_errors():
    node = {"type": "object", "properties": {}}
    cur = node
    for i in range(9):
        child = {"type": "object", "properties": {}}
        cur["properties"][f"l{i}"] = child
        cur = child
    spec, errors = normalize_operation("/x", "get", _op({"deep": node}))
    assert any("深度" in e for e in errors)

def test_result_one_level_dotted_field_ok_two_level_rejected():
    spec, errors = normalize_operation("/x", "get", _op(
        {"q": {"type": "string"}},
        {"kind": "object", "fields": ["id", "user.name", "user.dept.title"], "labels": {"user.name": "姓名"},
         "list_columns": [], "schema": {"type": "object", "properties": {"user": {"type": "object"}}}},
    ))
    assert any("user.dept.title" in e for e in errors)
    # 修复后仅合法字段保留的断言在实现里：fields 不含两层路径
```

- [ ] **Step 2: 跑测确认失败**

Run: `cd E:\python_project\oa-langGraph\backend && python -m pytest tests/test_schema_node.py -v`  
Expected: FAIL（深度/`items`/`RESULT_FIELD_RE` 尚未实现）

- [ ] **Step 3: 实现规范化**

在 `catalog.py`：

1. 增加常量：

```python
SCHEMA_MAX_DEPTH = 8
RESULT_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
```

2. 将 `_normalize_param` 改为递归（保留原顶层键，并处理嵌套）：

```python
def _normalize_param(name: str, rule: Any, errors: list[str], op: str, depth: int = 0) -> dict:
    if not isinstance(rule, dict):
        errors.append(f"{op}.model_params.{name} 必须是对象")
        return {}
    if depth > SCHEMA_MAX_DEPTH:
        errors.append(f"{op}.model_params.{name} 嵌套深度超过 {SCHEMA_MAX_DEPTH}")
        return {}
    out = {k: rule[k] for k in (
        "type", "format", "enum", "minimum", "maximum", "default", "required",
        "description", "label", "enum_labels", "accept", "multiple",
    ) if k in rule and rule[k] not in (None, "", [], {})}
    if out.get("type", "string") not in PARAM_TYPES:
        errors.append(
            f"{op}.model_params.{name}.type 只支持 string / integer / number / boolean / object / array / file"
        )
    out.setdefault("type", "string")
    out["required"] = bool(out.get("required", False))
    if "enum" in out and not isinstance(out["enum"], list):
        errors.append(f"{op}.model_params.{name}.enum 必须是数组")
    if "enum_labels" in out:
        if not isinstance(out["enum_labels"], dict):
            errors.append(f"{op}.model_params.{name}.enum_labels 必须是 取值→名称 的对象")
        else:
            out["enum_labels"] = {str(k): str(v) for k, v in out["enum_labels"].items()}
    if "accept" in out:
        if not isinstance(out["accept"], list):
            errors.append(f"{op}.model_params.{name}.accept 必须是数组")
            out.pop("accept", None)
        else:
            out["accept"] = [str(x) for x in out["accept"] if str(x).strip()]
    # file + multiple → array of file
    if out.get("type") == "file" and out.pop("multiple", False):
        items = {"type": "file"}
        if "accept" in out:
            items["accept"] = out.pop("accept")
        out = {k: v for k, v in out.items() if k in ("label", "description", "required")}
        out["type"] = "array"
        out["items"] = items
        out["required"] = bool(rule.get("required", False))
    if out.get("type") == "object":
        props_raw = rule.get("properties") or {}
        if props_raw and not isinstance(props_raw, dict):
            errors.append(f"{op}.model_params.{name}.properties 必须是对象")
        elif isinstance(props_raw, dict) and props_raw:
            out["properties"] = {
                str(k): _normalize_param(f"{name}.{k}", v, errors, op, depth + 1)
                for k, v in props_raw.items()
            }
    if out.get("type") == "array":
        items_raw = rule.get("items")
        if items_raw is None and "items" not in out:
            out["items"] = {"type": "string"}
        elif items_raw is not None:
            out["items"] = _normalize_param(f"{name}[]", items_raw, errors, op, depth + 1)
    out.pop("multiple", None)
    return out
```

3. 在 `normalize_operation` 的 result 段：用 `RESULT_FIELD_RE` 校验 `fields`；非法字段记 error 并丢弃；若有 `result.schema` 则 `_normalize_param("result", schema, errors, name)` 写入 `spec["result"]["schema"]`（注意 path 文案可用 `f"{name}.result.schema"`——若不想污染 model_params 错误前缀，可抽 `_normalize_schema_node(path, rule, errors, depth)` 供 param/result 共用）。

推荐抽出：

```python
def _normalize_schema_node(path: str, rule: Any, errors: list[str], depth: int = 0) -> dict:
    # 与上逻辑相同，错误前缀用 path 而非 op.model_params.name
    ...
```

`_normalize_param` 变为调用 `_normalize_schema_node(f"{op}.model_params.{name}", rule, errors, depth)`。

4. `diff_schemas`：对 `result.schema` 若仅新增/变更嵌套元数据，`add("result.schema", "changed", ..., breaking=False)`（与 labels 类似）。**不要**因仅增加 `properties`/`items` 且顶层 type 不变而把整参标 breaking（现有逻辑在 `before != after` 时已按 type/required/enum 算 is_breaking，嵌套变更且 type 不变 → 非 breaking，无需改）。

- [ ] **Step 4: 跑测通过**

Run: `python -m pytest tests/test_schema_node.py -v`  
Expected: PASS（按实现微调两层路径用例的断言）

- [ ] **Step 5: 暂存（不 commit 除非用户要求）**

```bash
git add backend/oa_agent/executor/catalog.py backend/tests/test_schema_node.py
```

---

### Task 2: `_pick` 一层点路径 + 参数粗检

**Files:**
- Modify: `backend/oa_agent/executor/executor.py`（`_pick`、`validate_args`）
- Create: `backend/tests/test_pick_dotted.py`

**Interfaces:**
- Produces: `_pick(row, fields, remark_limit) -> dict` 支持 `"user.name"`
- Consumes: `ToolSpec.result_fields`

- [ ] **Step 1: 写失败单测**

```python
# backend/tests/test_pick_dotted.py
from oa_agent.executor.executor import _pick, validate_args
from oa_agent.executor.registry import ToolSpec

def test_pick_top_level_and_one_dot():
    row = {"id": 1, "user": {"name": "张三", "dept": {"title": "审计"}}, "items": [{"sku": "A"}]}
    out = _pick(row, ("id", "user.name", "items"))
    assert out == {"id": 1, "user.name": "张三", "items": [{"sku": "A"}]}

def test_pick_missing_dot_skipped():
    assert _pick({"user": "x"}, ("user.name",)) == {}

def test_validate_nested_object_properties():
    spec = ToolSpec(
        name="t", method="GET", path="/", version="1", schema_hash="x",
        risk_level="low", requires_confirmation=False, timeout_seconds=10.0,
        inject_identity_fields=(), top_level_fields=(), query_params_field=None,
        model_params={
            "payload": {
                "type": "object",
                "required": True,
                "properties": {"n": {"type": "integer", "required": True}},
            }
        },
        result_kind="object", result_fields=("id",),
    )
    clean, _ = validate_args(spec, {"payload": {"n": "3", "extra": 1}})
    assert clean["payload"]["n"] == 3
    assert clean["payload"]["extra"] == 1  # 未声明键保留
```

- [ ] **Step 2: 跑测确认失败**

Run: `python -m pytest tests/test_pick_dotted.py -v`  
Expected: FAIL（`user.name` 目前不在 `row` 顶层）

- [ ] **Step 3: 实现**

```python
def _pick(row: dict, fields: tuple[str, ...], remark_limit: int = REMARK_LIMIT) -> dict:
    out: dict = {}
    for f in fields:
        if f in row:
            out[f] = row[f]
        elif "." in f:
            left, right = f.split(".", 1)
            nested = row.get(left)
            if isinstance(nested, dict) and right in nested:
                out[f] = nested[right]
    if isinstance(out.get("remark"), str) and len(out["remark"]) > remark_limit:
        out["remark"] = out["remark"][:remark_limit] + "…"
    return out
```

在 `validate_args` 中，object/array 分支后调用局部函数：

```python
def _check_node(path: str, rule: dict, value: Any) -> Any:
    ptype = rule.get("type") or "string"
    if ptype == "object":
        if not isinstance(value, dict):
            raise ToolError("INVALID_ARGUMENT", f"{path} 必须是对象")
        props = rule.get("properties") or {}
        out = dict(value)
        for pk, pr in props.items():
            if pk not in value:
                if pr.get("required"):
                    raise ToolError("INVALID_ARGUMENT", f"缺少参数 {path}.{pk}")
                continue
            out[pk] = _check_node(f"{path}.{pk}", pr, value[pk])
        return out
    if ptype == "array":
        if not isinstance(value, list):
            raise ToolError("INVALID_ARGUMENT", f"{path} 必须是数组")
        item_rule = rule.get("items") or {"type": "string"}
        return [_check_node(f"{path}[]", item_rule, v) for v in value]
    if ptype == "file":
        s = str(value).strip()
        if not s:
            raise ToolError("INVALID_ARGUMENT", f"缺少参数 {path}")
        return s
    if ptype == "integer":
        return int(value)
    # number/boolean/string：复用原分支逻辑或简写
    ...
    return value
```

顶层循环对 `object`/`array`/`file` 走 `_check_node`；标量保持现有代码以免行为漂移。

- [ ] **Step 4: 跑测通过**

Run: `python -m pytest tests/test_pick_dotted.py tests/test_schema_node.py -v`  
Expected: PASS

- [ ] **Step 5: 暂存**

```bash
git add backend/oa_agent/executor/executor.py backend/tests/test_pick_dotted.py
```

---

### Task 3: `upload-temp` API

**Files:**
- Create: `backend/oa_agent/admin/wizard_temp_upload.py`
- Modify: `backend/oa_agent/admin/catalog_api.py`
- Create: `backend/tests/test_wizard_upload_temp.py`

**Interfaces:**
- Produces:
  - `save_wizard_temp_file(data: bytes, filename: str) -> dict` → `{ref, filename, sha256, size}`
  - `POST /v1/admin/tools/export-wizard/upload-temp` multipart field `file`
- Consumes: 本地目录 `runtime/wizard-temp/`（相对 REPO_ROOT）；`admin_write(TOOL)`

- [ ] **Step 1: 写失败 API 测（用现有 admin fixture 模式）**

先读 `backend/tests/test_catalog_admin.py` 里 client/登录夹具，按同样方式：

```python
def test_upload_temp_returns_ref(admin):
    r = admin.client.post(
        "/v1/admin/tools/export-wizard/upload-temp",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["filename"] == "a.pdf"
    assert body["ref"]
    assert body["sha256"]
```

- [ ] **Step 2: 跑测确认失败**

Run: `python -m pytest tests/test_wizard_upload_temp.py -v`  
Expected: 404 或 FAIL

- [ ] **Step 3: 实现存储与路由**

```python
# wizard_temp_upload.py
from __future__ import annotations
import hashlib
import re
import uuid
from pathlib import Path
from oa_agent.settings import REPO_ROOT

TEMP_DIR = REPO_ROOT / "runtime" / "wizard-temp"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

def save_wizard_temp_file(data: bytes, filename: str) -> dict:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    safe = _SAFE.sub("_", (filename or "file").strip())[:120] or "file"
    name = f"{uuid.uuid4().hex}_{safe}"
    path = TEMP_DIR / name
    path.write_bytes(data)
    ref = str(path.resolve())
    return {"ref": ref, "filename": safe, "sha256": digest, "size": len(data)}
```

在 `catalog_api.py`：

```python
from fastapi import File, UploadFile
from oa_agent.admin.wizard_temp_upload import save_wizard_temp_file

@tools_router.post("/export-wizard/upload-temp")
async def export_wizard_upload_temp(
    file: UploadFile = File(...),
    ctx: AdminCtx = Depends(admin_write(TOOL)),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "空文件")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件过大")
    out = save_wizard_temp_file(data, file.filename or "file")
    # 若项目有 audit 辅助，记一条 ops.tool.manage upload-temp
    return {"data": out}
```

（HTTPException / 统一错误包装按该文件现有风格对齐。）

同时：`ToolResultIn` 增加可选字段：

```python
schema: dict[str, Any] | None = None
```

确保 create/update/save 把 `result.schema` 传入 normalize。

- [ ] **Step 4: 跑测通过**

Run: `python -m pytest tests/test_wizard_upload_temp.py -v`  
Expected: PASS

- [ ] **Step 5: 确认 `runtime/wizard-temp/` 在 `.gitignore`**

若无则追加 `runtime/wizard-temp/`。

- [ ] **Step 6: 暂存**

```bash
git add backend/oa_agent/admin/wizard_temp_upload.py backend/oa_agent/admin/catalog_api.py backend/tests/test_wizard_upload_temp.py .gitignore
```

---

### Task 4: 前端 `schemaTree.ts` 纯函数

**Files:**
- Create: `frontend/src/admin/schemaTree.ts`
- Create: `frontend/src/admin/schemaTree.spec.ts`

**Interfaces:**
- Produces:
  - `export type SchemaType = 'string'|'integer'|'number'|'boolean'|'object'|'array'|'file'`
  - `export interface SchemaNode { type: SchemaType; label?: string; ... properties?; items?; accept?; }`
  - `normalizeNode(n: unknown, depth?: number): SchemaNode`
  - `fileMultipleToArray(node: SchemaNode): SchemaNode`
  - `parseSchemaJson(text: string): { ok: true, value: Record<string, SchemaNode> } | { ok: false, error: string }`
  - `stringifySchema(map: Record<string, SchemaNode>): string`
  - `emptyNode(type?: SchemaType): SchemaNode`

- [ ] **Step 1: 写 vitest**

```ts
import { describe, expect, it } from 'vitest'
import { fileMultipleToArray, normalizeNode, parseSchemaJson } from './schemaTree'

describe('schemaTree', () => {
  it('normalizes nested object', () => {
    const n = normalizeNode({
      type: 'object',
      properties: { a: { type: 'array', items: { type: 'integer' } } },
    })
    expect(n.properties!.a.items!.type).toBe('integer')
  })

  it('file multiple → array of file', () => {
    const n = fileMultipleToArray({ type: 'file', multiple: true, accept: ['.pdf'] } as any)
    expect(n).toEqual({ type: 'array', items: { type: 'file', accept: ['.pdf'] } })
  })

  it('rejects bad json', () => {
    const r = parseSchemaJson('{')
    expect(r.ok).toBe(false)
  })
})
```

- [ ] **Step 2: 跑测失败**

Run: `cd E:\python_project\oa-langGraph\frontend && npm test -- src/admin/schemaTree.spec.ts`  
Expected: FAIL

- [ ] **Step 3: 实现 `schemaTree.ts`**（完整实现，深度默认上限 8，非法 type 降为 string，与后端对齐）

- [ ] **Step 4: 跑测通过**

Run: `npm test -- src/admin/schemaTree.spec.ts`  
Expected: PASS

- [ ] **Step 5: 暂存**

```bash
git add frontend/src/admin/schemaTree.ts frontend/src/admin/schemaTree.spec.ts
```

---

### Task 5: `SchemaTreeEditor.vue`

**Files:**
- Create: `frontend/src/admin/components/SchemaTreeEditor.vue`

**Interfaces:**
- Props: `modelValue: Record<string, SchemaNode>`（参数 map）或对返回根用 `SchemaNode | null`——**统一用**：
  - `mode: 'params' | 'result-root'`
  - params：`modelValue: Record<string, SchemaNode>`
  - result-root：`modelValue: SchemaNode | null`（可选根）
- Emits: `update:modelValue`
- 左树 + 右属性；顶栏树/JSON；JSON 非法禁止切回

- [ ] **Step 1: 搭建组件骨架**

使用 Element Plus：`el-tree`（或自绘缩进列表）+ 右侧 `el-form`。选中节点用 path 字符串（如 `payload/user/name`，array items 用 `tags[]`）。

关键行为：

- 类型变更：若新类型不能保留子树（object→string 等），`ElMessageBox.confirm` 后清空 `properties`/`items`。
- file：`accept` 用逗号文本编辑成 `string[]`；「多文件」开关 → `fileMultipleToArray` / 逆转换仅在 UI 态。
- JSON tab：`stringifySchema` / `parseSchemaJson`；错误时 `el-alert` + 禁用「树编辑」直至修复或「丢弃 JSON」。

- [ ] **Step 2: 手工或 vitest 可先不做挂载测；用临时页面/Story 不必。** 在浏览器打开管理端时再验。本任务以代码审查清单为准：props/emit、不直接改 props。

- [ ] **Step 3: 暂存**

```bash
git add frontend/src/admin/components/SchemaTreeEditor.vue
```

---

### Task 6: `schemaValue.ts` + `SchemaValueEditor.vue`

**Files:**
- Create: `frontend/src/admin/schemaValue.ts`
- Create: `frontend/src/admin/schemaValue.spec.ts`
- Create: `frontend/src/admin/components/SchemaValueEditor.vue`

**Interfaces:**
- `buildArgsFromValues(params: Record<string, SchemaNode>, values: Record<string, unknown>): Record<string, unknown>`
- `mergeValuesOnSchemaChange(oldSchema, newSchema, oldValues): Record<string, unknown>`
- `SchemaValueEditor` props: `schema: Record<string, SchemaNode>`, `modelValue: Record<string, unknown>`；file 上传调 `POST /v1/admin/tools/export-wizard/upload-temp`（用现有 `http` 封装，`FormData`）

- [ ] **Step 1: 纯函数测**

```ts
it('builds array and nested object args', () => {
  const args = buildArgsFromValues(
    { ids: { type: 'array', items: { type: 'integer' } }, payload: { type: 'object', properties: { n: { type: 'string' } } } },
    { ids: ['1', '2'], payload: { n: 'x' } },
  )
  expect(args).toEqual({ ids: [1, 2], payload: { n: 'x' } })
})
```

- [ ] **Step 2: 实现 `schemaValue.ts` 与组件**

`SchemaValueEditor`：递归渲染；array 加删；file：`el-upload` `:http-request` 自定义 → 成功把 `ref` 写入值，展示 `filename`；旁路 `el-input` 手填。

- [ ] **Step 3: 跑测**

Run: `npm test -- src/admin/schemaValue.spec.ts`  
Expected: PASS

- [ ] **Step 4: 暂存**

```bash
git add frontend/src/admin/schemaValue.ts frontend/src/admin/schemaValue.spec.ts frontend/src/admin/components/SchemaValueEditor.vue
```

---

### Task 7: 改造 `catalogForm.ts` + 编辑 Tool 接线

**Files:**
- Modify: `frontend/src/admin/catalogForm.ts`
- Modify: `frontend/src/admin/catalogForm.spec.ts`
- Modify: `frontend/src/admin/views/ToolsView.vue`（编辑对话框部分）

**Interfaces:**
- `ToolForm.modelParams: Record<string, SchemaNode>` 替代 `params: ParamRow[]`（或并存迁移：保留 `fields: FieldRow[]`，新增 `resultSchema: SchemaNode | null`）
- `toolPayload` / `toolFormFromSchema` 完整往返嵌套；**禁止** `type: rule.type === 'integer' ? 'integer' : 'string'`

推荐最小破坏：

```ts
export interface ToolForm {
  // ...现有标量字段
  modelParams: Record<string, SchemaNode>
  resultSchema: SchemaNode | null
  result_kind: 'list' | 'object'
  fields: FieldRow[]  // key 允许一层点路径
}
```

- [ ] **Step 1: 扩展 `catalogForm.spec.ts`**

```ts
it('preserves array/object/file on round-trip', () => {
  const schema = {
    name: 't', summary: '', path: '/', upstream: 'open_oa',
    model_params: {
      ids: { type: 'array', items: { type: 'integer' } },
      f: { type: 'file', accept: ['.pdf'] },
    },
    result: { kind: 'object', fields: ['id', 'user.name'], labels: { 'user.name': '名' }, list_columns: [],
      schema: { type: 'object', properties: { user: { type: 'object' } } } },
  }
  const form = toolFormFromSchema(schema)
  const payload = toolPayload(form) as any
  expect(payload.model_params.ids.items.type).toBe('integer')
  expect(payload.model_params.f.type).toBe('file')
  expect(payload.result.fields).toContain('user.name')
  expect(payload.result.schema.properties.user.type).toBe('object')
})
```

- [ ] **Step 2: 跑测失败 → 改 `catalogForm.ts` → 通过**

Run: `npm test -- src/admin/catalogForm.spec.ts`

- [ ] **Step 3: 编辑对话框**

替换参数表格为：

```vue
<SchemaTreeEditor mode="params" v-model="form.modelParams" />
```

返回区：

```vue
<SchemaTreeEditor mode="result-root" v-model="form.resultSchema" />
<!-- 保留 fields 表；placeholder 提示支持 user.name -->
```

删除仅「文本/整数」的 `el-select`。同步 `openEdit` / `save` 使用新 `toolPayload`。

- [ ] **Step 4: 暂存**

```bash
git add frontend/src/admin/catalogForm.ts frontend/src/admin/catalogForm.spec.ts frontend/src/admin/views/ToolsView.vue
```

---

### Task 8: 向导接线（schema + 试调 + 落库）

**Files:**
- Modify: `frontend/src/admin/views/ToolsView.vue`（向导脚本与模板）

**Interfaces:**
- 删除 `WizardObjectEntry` 浅层 KV 试调 UI
- `wizardParams: Record<string, SchemaNode>` 由 describe 预填后进 `SchemaTreeEditor`
- `wizardValues` + `SchemaValueEditor`
- `wizardBuildModelParams()` → 直接返回 `wizardParams`（已是 SchemaNode map）
- `wizardBuildArgs()` → `buildArgsFromValues(wizardParams, wizardValues)`
- `wizardSave` 的 `result` 带 `schema: wizardResultSchema`；`fields` 来自结果表（可一层点路径）

- [ ] **Step 1: describe 回调里把后端 params 转 `Record<string, SchemaNode>`**（用 `normalizeNode`）

- [ ] **Step 2: 模板替换参数配置区与测试值区**

- [ ] **Step 3: 手工验收清单（实现者勾选）**

1. 向导：array&lt;integer&gt; 可加多项试调并 probe  
2. object 嵌套可填  
3. file 上传后 args 含 ref 字符串  
4. 入库后再打开编辑：类型与嵌套仍在  
5. 返回字段填 `user.name` 可保存；`user.dept.title` 前端/后端均拒绝  

- [ ] **Step 4: 跑前后端相关测**

```bash
cd E:\python_project\oa-langGraph\backend && python -m pytest tests/test_schema_node.py tests/test_pick_dotted.py tests/test_wizard_upload_temp.py -v
cd E:\python_project\oa-langGraph\frontend && npm test -- src/admin/schemaTree.spec.ts src/admin/schemaValue.spec.ts src/admin/catalogForm.spec.ts
```

Expected: 全 PASS

- [ ] **Step 5: 暂存；用户要求时再 commit**

```bash
git add frontend/src/admin/views/ToolsView.vue
# 用户授权后：
# git commit -m "feat: Tool schema 树编辑与向导嵌套试调"
```

---

## Spec coverage（self-review）

| Spec 项 | Task |
|---------|------|
| SchemaNode / 深度 8 / multiple→array | T1, T4 |
| result.schema + 一层点路径 fields | T1, T7, T8 |
| `_pick` 一层路径、深层透传 | T2 |
| validate 嵌套粗检、额外键保留 | T2 |
| upload-temp + 手填 | T3, T6 |
| SchemaTreeEditor 左树右栏 + JSON | T5 |
| SchemaValueEditor 仅向导 | T6, T8 |
| 编辑页不冲类型 | T7 |
| 向导落库完整 model_params | T8 |
| 不做编辑页试调 / 深路径裁剪 / oneOf | 非目标，无任务 |

**Placeholder scan:** 无 TBD；T5 挂载测以手工清单代替（已写明）。  
**类型名:** 统一 `SchemaNode` / `SchemaType`；上传响应字段统一 `ref`。

---

## Execution

Plan 路径：`docs/superpowers/plans/2026-11-17-tool-schema-editor-ux.md`
