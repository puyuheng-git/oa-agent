# Tool 参数/返回 Schema 编辑器 UX（向导 + 编辑 Tool）

| 项 | 内容 |
|---|---|
| 日期 | 2026-11-17 |
| 状态 | 已评审待实现 |
| 范围 | 管理端「接入业务接口向导」与「编辑 Tool」：任意深度参数/返回 schema 可视化编辑；向导试调按 schema 填值；file 试调可上传 |
| 仓库 | `oa-langGraph`（`frontend/src/admin` + `backend/oa_agent`） |
| 前置 | [2026-11-16 Agent Export 向导](./2026-11-16-agent-export-wizard-design.md) 已落地；本设计修补参数/返回编辑能力缺口 |
| 方案 | 共享 Schema 树编辑器 + 受控 JSON Schema 子集（方案 1） |

## 1. 背景与问题

现状（`ToolsView.vue` + `catalogForm.ts` + `catalog._normalize_param`）：

- **编辑 Tool**：参数类型仅「文本 / 整数」；打开并保存会把 `array` / `object` / `file` 等冲成 `string`。
- **接入向导**：类型可选，但试调数组仅一层字符串、object 仅一层 KV、file 仅路径文本框；落库的 `model_params` 不带嵌套元数据。
- **返回值**：两边都是扁平 `fields` / `labels` / `list_columns`；多维/嵌套结构无法描述；`_pick` 只取顶层键。

目标：定义 schema 与向导试调都可用；支持任意深度；file 试调可上传；返回可描述嵌套并支持一层点路径列表列。

## 2. 决策摘要

| 编号 | 决策 |
|---|---|
| D1 | 范围 = schema 定义 + 向导试调填值（编辑 Tool 不做试调） |
| D2 | 嵌套任意深度；受控子集，不做 oneOf/anyOf/tuple items |
| D3 | 向导与编辑 Tool **共用** `SchemaTreeEditor`：左树 + 右属性；可切 JSON 高级编辑 |
| D4 | file：试调上传得 path/id；schema 可配 `accept` / `multiple`；仍可手填路径/ID |
| D5 | 返回：`result.schema` 描述形状；`fields`/`list_columns` 允许顶层或**一层**点路径；更深整段透传、不按深路径裁剪 |
| D6 | 存储扩展现有 `model_params` / `result`，不换成另一套文档模型 |
| D7 | 仅增加可选嵌套元数据视为 **compatible**；删顶层字段/改标量类型等仍走现有 breaking 规则 |

## 3. 数据模型

### 3.1 Schema 节点（递归）

```ts
type SchemaNode = {
  type: 'string' | 'integer' | 'number' | 'boolean' | 'object' | 'array' | 'file'
  label?: string
  description?: string
  required?: boolean
  format?: 'date' | ''
  enum?: (string | number)[]
  enum_labels?: Record<string, string>
  minimum?: number
  maximum?: number
  default?: unknown
  properties?: Record<string, SchemaNode>  // object
  items?: SchemaNode                       // array：单一 items
  accept?: string[]                        // file 扩展名，空=不限
  multiple?: boolean                       // file 多文件；落库可规范为 array+items.file
}
```

顶层：`model_params: { [paramName]: SchemaNode }`（与现网一致，节点可变深）。

**规范约束**

- 递归深度上限：**8**（规范化时截断或报错，实现时选报错更安全）。
- `multiple: true` 的 `file`：**落库统一**为 `type: array` + `items: { type: 'file', accept? }`；UI 可用「多文件」开关，读写时与该形状互转。单文件保持 `type: file`。
- 不做：`oneOf` / `anyOf` / 元组 `items: SchemaNode[]`。

### 3.2 返回值

```ts
result: {
  kind: 'list' | 'object'
  fields: string[]                 // 顶层键或一层点路径，如 "user.name"
  labels: Record<string, string>
  list_columns: string[]           // ⊆ fields
  schema?: SchemaNode              // 可选；描述整段返回形状（给人/Agent）
}
```

**字段名校验**：`^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$`（最多一个点）。两层及以上点路径拒绝进入 `fields`。

### 3.3 兼容

- 旧 Tool 无 `properties` / `items` / `result.schema`：行为与现网一致。
- 编辑打开已有 `array`/`object`/`file`：**禁止**再冲成 `string`。
- `catalogForm.toolFormFromSchema` / `toolPayload` 改为读写完整 SchemaNode（或编辑页直接以 schema JSON 树为源，弱化仅两类型的 `ParamRow`）。

## 4. UI：`SchemaTreeEditor`

### 4.1 布局（已定 B）

- **左**：结构树。顶层参数名；`object` → `properties` 子节点；`array` → 固定子节点 `items`。
- **右**：选中节点属性（名称、类型、label、description、required；标量扩展；file 的 accept/multiple；array 的 items 类型入口）。
- **顶栏**：树编辑 | JSON 高级；校验状态。

### 4.2 交互

- + 参数 / + 子字段、删除、同级拖拽排序。
- 切换类型：与旧子结构不兼容时确认后清空子树。
- JSON 高级：与树双向同步；非法 JSON 或超出受控子集 → 报错，禁止带着坏数据切回树；提供「丢弃 JSON 改动」。

### 4.3 返回值区

- 同一组件编辑可选 `result.schema`。
- 另表维护 `fields` / `labels` / `list_columns`（键允许一层点路径）。

### 4.4 挂载点

| 页面 | 用法 |
|---|---|
| 接入业务接口向导 | 配置 `model_params` 与 `result`（替代当前浅表） |
| 编辑 Tool | 同上，替换仅文本/整数的参数表与扁平字段表的「结构不足」部分 |

组件建议路径：`frontend/src/admin/components/SchemaTreeEditor.vue`（及纯函数 `schemaTree.ts`）。

## 5. 向导试调：`SchemaValueEditor` + 上传

### 5.1 范围

- **仅向导**测试步；编辑 Tool 本期不做试调。

### 5.2 SchemaValueEditor

- 按当前 `model_params` 递归渲染：标量控件、array 加删项、object 缩进子表单。
- 任意节点可「粘贴 JSON」覆盖该节点。
- 必填空值时拦截「测试接口」并标红。
- schema 变更后：尽量保留同路径旧值；对不上的丢弃并提示。

### 5.3 file 上传

- 主路径：选择文件 → `POST /v1/admin/tools/export-wizard/upload-temp` → 响应含 `ref`（写入参数的字符串，path 或附件 id，与现网 file 语义一致）及 `filename`；控件展示文件名，值为 `ref`。
- 校验 `accept`；多文件（array of file）→ `ref[]`。
- 辅路径：手填路径/附件 ID（直接写入参数字符串）。
- 临时对象：短 TTL（建议 ≤24h）、管理端权限、**不**写入员工会话附件。

### 5.4 落库

- `wizardBuildModelParams` 必须持久化完整 SchemaNode（含 `properties` / `items` / `accept` 等），不得再只写 `type/label/required/description`。
- 试调成功后的 `result` 写入含可选 `schema` 与一层路径 `fields`。

## 6. 运行时与后端

### 6.1 规范化（`catalog.py`）

- `_normalize_param` 递归处理 `properties` / `items`，放行 `accept` / `multiple`；深度 > 8 报错。
- `result`：可选 `schema` 经同一套节点规范化；`fields`/`list_columns` 使用一层点路径正则；`list_columns ⊆ fields`。

### 6.2 参数校验（`executor.py`）

- `object` / `array`：容器类型检查 + 对声明了的 `properties`/`items` 做递归粗检（未声明的键：object 可保留透传或剥掉——**实现时与现网「只校验声明参数」一致：顶层仍只认 model_params 键；嵌套 object 未声明的额外键默认保留**）。
- `file`：值仍为非空字符串（path/id）；多文件则为 string 数组。

### 6.3 返回投影 `_pick`

- 顶层键：`row[f]`。
- 一层路径 `a.b`：若 `row[a]` 为 `dict`，取 `b`，输出扁平键 `"a.b"`。
- `fields` 中的 array/object：整段放入结果。
- `result.schema` **不参与**裁剪。

### 6.4 新 API

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/v1/admin/tools/export-wizard/upload-temp` | 管理端临时上传；返回 `{ id, path 或等价引用, filename }` |

权限：与现有 export-wizard 同级管理权限；审计记录上传。

### 6.5 版本兼容

- 仅增加 `properties`/`items`/`accept`/`result.schema` 等可选元数据 → **compatible**。
- 删除顶层参数、更改标量 `type`、收紧 required 等 → 沿用现有 breaking 判定（可按需把「嵌套形状 breaking」后续再加，本期不扩大 breaking 面）。

## 7. 非目标（本期不做）

- 编辑 Tool 内嵌试调 / probe。
- 返回值按任意深路径裁剪。
- 完整 JSON Schema（oneOf/anyOf/$ref）。
- 员工对话侧 file 参数填写 UX（仍走现有附件体系）。
- 第三方 schema-form 生成器替换自研树。

## 8. 测试要点

- `catalogForm` / 规范化：嵌套 param 往返不丢；旧扁平 schema 仍可读。
- 编辑保存：不再把 `array`/`file` 冲成 `string`。
- `_pick`：顶层、`user.name`、整段 `items` 数组；拒绝两层点路径入库。
- SchemaTreeEditor：树↔JSON 同步与非法 JSON 拦截。
- SchemaValueEditor：array/object/file 试调组装；upload-temp 回填后 probe 请求体正确。
- 深度上限与 accept 校验。

## 9. 实现顺序（供 writing-plans 展开）

1. 后端 SchemaNode 规范化 + `_pick` 一层路径 + 单测  
2. `upload-temp` API  
3. 前端 `schemaTree.ts` + `SchemaTreeEditor`  
4. `SchemaValueEditor` + 向导接线（含 file 上传）  
5. 编辑 Tool 换成同一编辑器；修复 `catalogForm` 冲类型问题  
6. 联调向导：嵌套参数试调 → 入库 → 再打开编辑不丢结构  

## 10. 线框参考

头脑风暴线框（本地，已 gitignore）：`.superpowers/brainstorm/*/content/schema-tree-*.html`、`test-value-file-upload.html`、`return-projection.html`。
