# LLM 模型默认、分类与同池顺延

**日期：** 2026-11-17  
**状态：** 已交付（见 [`docs/delivery/2026-11-17-llm-model-routing-delivery.md`](../../delivery/2026-11-17-llm-model-routing-delivery.md)）  
**权威设计：** [`docs/design/2026-10-09-oa-langgraph-design.md`](../../design/2026-10-09-oa-langgraph-design.md)  
**相关：** [`2026-10-28-llm-remote-models-design.md`](./2026-10-28-llm-remote-models-design.md)

---

## 1. 目标

后台模型管理支持：

1. **全局默认模型**：系统未指定模型时使用。  
2. **能力分类**（固定枚举，模型可多选）：`text` / `vision` / `multimodal` / `embedding`。  
3. **规模档**（单选）：`large` / `small`，便于系统按场景调用（如路由用小模型）。  
4. **独立路由策略表**：按「能力 × 规模」维护有序候选列表；配置不可用跳过，调用失败时同池顺延。

---

## 2. 硬约束

1. 提供方协议仍仅为 `openai_compatible`；不改密钥只写不读。  
2. 租户内全局默认模型最多 **1** 个（覆盖式设置）。  
3. 每个 `(tenant_id, capability, model_tier)` 至多一条 route。  
4. 运行时顺延仅针对**传输/提供方错误**（超时、HTTP 4xx/5xx、鉴权、连接失败等 → `ModelCallError` 一类）；**不因**「输出不是合法 JSON」换模型。  
5. 同池最多尝试 `max_failover` 次（含第一次），默认 **3**。  
6. 未配置 route / 未设全局默认时，行为与现状兼容（不强制管理员立刻配齐）。

---

## 3. 数据模型

### 3.1 扩展 `agent_llm_model`

| 字段 | 类型 | 说明 |
|------|------|------|
| `capabilities` | JSON list | 固定枚举多选；缺省 `["text"]` |
| `model_tier` | string | `large` \| `small`；缺省 `large` |

保留现有字段（含 `purpose_tags`）。全局默认**不**存在模型行上。

### 3.2 新建 `agent_llm_route`

| 字段 | 说明 |
|------|------|
| `tenant_id` | 租户 |
| `capability` | 单值枚举：`text` / `vision` / `multimodal` / `embedding` |
| `model_tier` | `large` / `small` |
| `model_ids` | 有序 JSON 数组：候选模型主键 ID |
| `enabled` | 是否启用该池 |
| `updated_by` / 时间戳 | 与现有表一致 |

唯一约束：`(tenant_id, capability, model_tier)`。

### 3.3 新建 `agent_llm_defaults`

| 字段 | 说明 |
|------|------|
| `tenant_id` | 租户（唯一） |
| `global_default_model_id` | 可空；全局默认模型 ID |
| `max_failover` | 同池运行时尝试上限，默认 3 |

「设为默认」按钮写入 `global_default_model_id`（覆盖）。

---

## 4. 解析与顺延

### 4.1 解析顺序

1. 调用方显式 `model_id`（如工作流 `llm_model_id`）：  
   - 配置可用 → 使用之；  
   - 配置不可用 → 不报错中断解析，进入 §4.4 的「同池后续」候选（从该 ID 在池中的下一位起）；若无匹配池则继续步骤 2。  
2. 调用方指定 `(capability, model_tier)` → 查启用中的 route，按 `model_ids` 取第一个**配置可用**模型。若该池不存在、为空或无可用模型 → 返回 `None`（**不**落到全局默认，由调用方决定回退；如路由阶段回退主模型）。  
3. 否则（调用方未指定 `(capability, model_tier)`）→ `global_default_model_id`（若配置可用）。  
4. 否则 → 兼容旧逻辑：`purpose_tags` 匹配 → 任一启用模型。  
5. 都没有 → `None`（上层走规则/降级，与今天一致）。

### 4.2 配置可用

模型 `enabled`、提供方 `enabled`、已配置 API Key；且（在 route 池过滤时）模型 `capabilities` 含该池 `capability`、`model_tier` 等于该池。`model_ids` 中无效或不符条目静默跳过（可打日志）。

### 4.3 运行失败顺延

- 触发：传输/提供方错误导致的 `ModelCallError`（或等价）。  
- 不触发：模型输出非法 JSON / 业务解析失败。  
- 同池按 `model_ids` 顺序继续，总尝试次数 ≤ `max_failover`。  
- 事件：每次失败记 `model_call`；成功时可带 `failover_from` / `attempt` 元数据。  
- 池耗尽或达上限 → 向上抛错/走现有降级，不静默编造。

### 4.4 显式 `model_id` 失败后（配置不可用或运行失败）

1. 确定 failover 池：  
   - 若调用方传了 `capability` → 使用 `(capability, 该模型 model_tier)` 的 route（须启用且 `model_ids` 含该 ID，或至少 capability/tier 匹配；含该 ID 时从其后继续，不含则从池头继续且总次数仍受 `max_failover` 约束）。  
   - 若未传 `capability` → 在本租户启用 route 中查找 `model_ids` 含该 ID 且 `model_tier` 等于该模型的池；若多条，按 capability 固定顺序 `text → vision → multimodal → embedding` 取第一条。  
2. 从该 ID 在 `model_ids` 中的**下一位**起尝试配置可用模型（运行失败时同样）。  
3. 找不到任何匹配池 → **不再顺延**（显式 ID 运行失败则向上抛错；配置不可用则回到 §4.1 步骤 2）。

### 4.5 系统调用约定

| 场景 | 选模 |
|------|------|
| 对话主模型（未指定 ID） | 全局默认 |
| 路由小模型（`stage=router`） | `(text, small)` 池（不继承发布配置的 `llm_model_id`）；池空/不可用则无候选，路由阶段回退主模型（即全局默认） |
| 视觉 / 多模态 | 调用方传 `(vision\|multimodal, large\|small)` |
| embedding | `(embedding, tier)` 按调用方 |

---

## 5. API（增量）

权限与现有 LLM 管理一致：`sys.setting.view` / `sys.setting.edit`。写操作记审计。

| 方法 | 路径 | 说明 |
|------|------|------|
| 扩展 | `POST/PUT /v1/admin/llm/models` | body 增加 `capabilities`、`model_tier` |
| POST | `/v1/admin/llm/models/{id}/set-default` | 设全局默认 |
| GET | `/v1/admin/llm/defaults` | 读全局默认与 `max_failover` |
| PUT | `/v1/admin/llm/defaults` | 更新 `global_default_model_id` / `max_failover` |
| GET | `/v1/admin/llm/routes` | 列出本租户全部 route |
| PUT | `/v1/admin/llm/routes` | 创建或覆盖单条 `(capability, model_tier)` 的 `model_ids` / `enabled` |
| DELETE | `/v1/admin/llm/routes/{capability}/{model_tier}` | 删除该池 |

校验：`model_ids` 必须属于本租户；能力/规模不符的 ID **仍允许保存**（解析时跳过）。`PUT /routes` 成功体可含 `warnings: string[]`（如「模型 3 的 capabilities 不含 text」），无则 `[]`。

---

## 6. 后台 UI（`LlmView.vue`）

**模型表**

- 列：能力标签、规模、是否全局默认。  
- 编辑：能力多选、规模单选。  
- 行操作：**设为默认**（二次确认，覆盖）。

**模型路由**（同页卡片或子 Tab）

- 按「能力 × 规模」管理池；从符合条件的启用模型中排序（拖拽或上下箭头）。  
- 顶栏或 defaults 区展示/编辑 `max_failover`。  
- 空池提示：该组合无候选，调用方自行回退（路由阶段回退主模型）。

---

## 7. 迁移

1. `agent_llm_model` 增加 `capabilities`（默认 `["text"]`）、`model_tier`（默认 `large`）。  
2. 创建 `agent_llm_route`、`agent_llm_defaults`。  
3. **不**自动生成 route 行。  
4. 迁移时：若该租户尚无 `agent_llm_defaults` 行或 `global_default_model_id` 为空，将「带 `intent` 用途标签的第一个启用模型，否则按 id 排序的第一个启用模型」写入一次；已有值不覆盖。

---

## 8. 测试

- 设默认 / 覆盖默认；停用默认后解析落到 route 或兼容链。  
- 配置态跳过停用/无 Key；运行失败顺延（mock 第一次失败、第二次成功）。  
- JSON 非法不顺延。  
- 显式 ID 失败后从池内后续继续；不在池内不顺延。  
- 指定 `(capability, tier)` 且池空/不可用 → 返回 `None`（不落全局默认）；路由阶段由调用方回退主模型。  
- 发布配置固定 `llm_model_id` 时，路由候选仍以 `(text, small)` 池为首。  
- 正文已流式输出后发生提供方错误 → 不顺延，直接抛错。  
- `set-default`、改 route 写审计；无权限 403。

---

## 9. 范围外

- 按工作流/渠道多套 route。  
- 定时健康检查写探活状态。  
- 非 OpenAI 兼容协议。  
- 根据远端模型名自动推断能力/规模。  
- 移除 `purpose_tags`（仅 UI 降权，保留兼容）。

---

## 10. 文件清单（预期）

- `backend/oa_agent/db/models.py` — `LlmModel` 扩展；`LlmRoute`、`LlmDefaults`  
- DB 迁移 / 建表路径（与仓库现有 schema 同步方式一致）  
- `backend/oa_agent/runtime/llm.py` — `resolve_model` / 顺延调用封装  
- `backend/oa_agent/admin/llm_api.py` — defaults / routes / set-default  
- `frontend/src/admin/views/LlmView.vue` — 默认按钮、分类、路由池 UI  
- `backend/tests/test_llm.py`（及必要时新增 routing 测试）  
- 运行时调用点：`chat/service.py`、`oa_assistant` router 阶段等按 §4.5 传 `(capability, tier)`

---

## 11. 决策记录

| 项 | 选择 |
|----|------|
| 同类型分组 | 能力 × 规模 二维 |
| 默认 | 全局默认 + 各池有序列表 |
| 不可用 | 配置跳过 + 运行失败有限顺延 |
| 能力取值 | 固定枚举，模型多选；规模单选 |
| 架构 | 独立 route / defaults 表（方案 2） |
| 顺延上限 | 默认 3，可配 |
