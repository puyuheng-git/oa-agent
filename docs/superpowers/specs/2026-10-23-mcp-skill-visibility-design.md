# MCP / Skill / Tool 职责与可见权限设计

| 项 | 内容 |
|----|------|
| 日期 | 2026-10-23 |
| 状态 | **已确认**（用户审阅通过 2026-10-23） |
| 子系统 | 平台路线图 **C**（总序 E → **C** → A → D → B） |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md`（冲突时以该文档为准） |
| 路线图 | `docs/superpowers/plans/2026-10-23-platform-next-roadmap.md` |
| 前序交付 | E：`docs/delivery/2026-10-23-chat-threads-delivery.md` |

### 已锁定决断

| ID | 选择 | 含义 |
|----|------|------|
| **D5** | **B** | 「MCP」= 内部执行平面 + 规划出站标准 MCP Client |
| **D6** | **C** | 可见权限 = 后台默认规则 + OA 标签覆盖（混合） |
| **D7** | **B** | 模型选不可见 Tool → 明确告知「该功能未对你开放」 |
| **D14** | **通用** | Domain 仅「通用助理」骨架；不做多 Domain 路由 |
| **D16** | **B** | 本期无 OA 标签接口：后台规则 + OA 覆盖**预留**；联调后置 |
| **D17** | **A** | 可见性只挂 **Skill**；Tool 随 Skill 间接可见 |
| **D18** | **A** | 出站 MCP：职责 + 适配层接口/安全边界；不连真实 Server |
| **D19** | **C** | 无可见性规则 = 不启裁剪（同现网）；有规则才裁剪 |

**实施路径：** 方案 1 — 运行时 `VisibilityService` + 配置表；规则即时生效，不打进 Release 快照。

---

## 1. 背景与目标

**现状：**

- 真实路径：员工自然语言 →（Skill 约束下）模型选 Tool → Executor 调 office-api。
- 代码包名 `mcp` 实为 Registry/Executor，**不是**标准 MCP 协议服务端。
- Tool / Skill 后台 CRUD、启停、校验已有；运行时「启用且校验通过的 Skill → 过滤 Tool」。
- **无**按员工裁剪 Skill 目录的能力：启用即对全员可见（欢迎页、帮助、模型候选、执行）。

**目标：**

1. 定稿 Tool / Skill / MCP（执行平面）/ Domain 职责用语，避免「MCP」对外混淆。
2. 以 Skill 为唯一挂载点实现**目录可见性**裁剪；数据权限仍在 office-api。
3. 所有员工可见路径与执行前校验统一经 `VisibilityService`，防漏网。
4. 预留 OA 标签覆盖与出站 MCP Client 适配接口，本期不对接真实 OA 标签服务、不连真实 MCP Server。

**验收素描：**

1. 文档与代码边界清晰：员工只见 Skill；管理员见 Tool + Skill +（预留）出站连接器。
2. 为 Skill 配置 `oa` allow 后，未命中员工：欢迎 `skills` 不含该 Skill；模型候选无其 Tool；若仍选中则明确「未开放」且不执行上游。
3. `PUT` 规则为空数组后，该 Skill 恢复现网「启用即全员」行为（D19=C）。
4. 出站 MCP 仅有接口 + Noop；无真实出站流量。
5. 管理写操作失败时审计失败则整单失败；日志不含密钥明文。

---

## 2. 非目标（本规格不做）

- 子系统 A（Profile / 长期记忆）、D（新固定 Workflow）、B（多 Domain 路由 / L2+）。
- Tool 级独立可见规则；发现权与调用权拆分；场景定时开关；负向权限运营大盘。
- 入站 MCP Server；对接真实内部 MCP Server；OA「可办事宜/标签」HTTP 联调（仅预留）。
- 管理端可见性编辑 UI（本期 **仅 API**；UI 另开任务）。
- 改业务放行逻辑或放宽 office-api 校验。
- 管理员直改 Checkpoint / 图状态。

---

## 3. 职责分层（定稿用语）

| 概念 | 职责 | 员工是否可见 | 本期动作 |
|------|------|--------------|----------|
| **Tool** | 一个可调用的 office-api（或将来 MCP 映射）能力：路径、schema、白名单、超时、上游 | 否（经 Skill 间接） | 沿用现网；不挂可见规则 |
| **Skill** | 能力包：说明、示例、允许 Tool 集、填参指引 | **是** | **可见性唯一挂载点** |
| **MCP（执行平面）** | Registry / Executor：校验、注入身份、事件、限流；出站 Client 适配层 | 否 | 包名可保留；对外称「执行器 / 连接器」；出站仅接口+边界 |
| **Domain** | 岗位角色（提示词 + Skill 子集） | 不直接选 | 仅预留「通用」骨架配置字段，不做路由 |

硬约束：

1. 与 OA 只走 HTTP；对 `td_oa` 零访问。
2. 业务授权、校验、幂等在 office-api / Service；**模型输出不参与权限判定**。
3. Agent 只做目录可见性裁剪，**绝不**因 Skill 可见而放宽上游校验。

---

## 4. 可见性模型

### 4.1 原则

- **目录可见性（Agent）：** 提示词 / 欢迎页 / 帮助 / 模型候选 / 执行前门禁。
- **数据权限（office-api）：** 即使 Skill 可见，接口仍只返回该员工 token 有权数据。

### 4.2 生效条件（D19=C）

| 该 Skill 的规则行数 | 行为 |
|---------------------|------|
| **0** | **不启裁剪**；仅现网条件：`enabled` + 校验通过 +（执行侧）已注册 Tool 等 |
| **≥1** | 进入裁剪：须命中至少一条 **allow**，且不被 **deny** 命中 |

### 4.3 规则主体（一期）

| `principal_type` | 含义 | 本期 |
|------------------|------|------|
| `all` | 全员 | ✅ 可配 |
| `oa` | 显式员工账号 | ✅ 可配 |
| `tag` | OA 标签 / 可办事宜码 | ⚠️ 可入库；**无 OA 拉取时 `tags=[]`，tag 规则不命中（不误放行）** |

- `effect`：`allow` \| `deny`；**deny 优先于 allow**。
- 有规则但无 allow 命中 → 不可见。

### 4.4 PrincipalContext

```
PrincipalContext:
  oa: str          # 仅来自服务端 session，禁止客户端自报
  tags: list[str]  # 本期恒空或由可注入 stub；将来由 OA 覆盖填充
```

解析顺序：

1. 载入该 Skill 规则；空 → 可见（在现网启用/校验之上）。
2. 构建 `PrincipalContext`。
3. 任一 deny 命中 → 不可见。
4. 任一 allow 命中 → 可见。
5. 否则不可见。

### 4.5 对员工表现（D7=B）

- 不可见 Skill：不出现在欢迎 `skills`、自动帮助文案、模型候选 Tool 集。
- 模型仍选出不可见 Tool / 所属 Skill 不可见：执行前失败，员工可见明确文案「该功能未对你开放」；错误码见 §7。不静默当不存在。

---

## 5. 数据模型

### 5.1 新表 `agent_skill_visibility_rule`

| 列 | 类型（示意） | 说明 |
|----|--------------|------|
| `id` | PK | |
| `tenant_id` | String(32) | 一期 `dscpa` |
| `skill_id` | FK → `agent_skill` | 挂载点 |
| `effect` | String(8) | `allow` \| `deny` |
| `principal_type` | String(16) | `all` \| `oa` \| `tag` |
| `principal_value` | String(128) | `all` 时可空或 `*`；`oa`/`tag` 为具体值 |
| `created_at` / `updated_at` | UtcDateTime | |
| `created_by` | String(64) nullable | 管理员标识（审计冗余，非授权源） |

索引建议：

- `(tenant_id, skill_id)`
- 可选 UK：`(tenant_id, skill_id, effect, principal_type, principal_value)` 防重复

### 5.2 与发布 / 配置

- 可见规则属**配置中心即时生效**，**不**写入 Release `content_json` 快照。
- 进行中的 run 以「调用当下」规则为准（与现网 Tool 启停一致）。
- Domain「通用」仅预留配置键/表字段（若已有 agent 配置则只文档化）；本期无多 Domain 表也可只在设计中声明扩展点。

---

## 6. 运行时与 API

### 6.1 VisibilityService

单一入口（名称可微调，职责不可散）：

- `is_skill_visible(skill, principal) -> bool`
- `filter_skills(skills, principal) -> list`
- `assert_tool_allowed(tool_name, principal, skill_index) -> None`（失败抛业务错误）

**必过调用点：**

| 路径 | 行为 |
|------|------|
| session 欢迎 `skills` | 只返回可见 Skill |
| 帮助 / `help_text` 自动生成 | 只用可见 Skill |
| `understand` 候选 Tool | 仅可见 Skill 声明且已注册的 Tool |
| Executor 真实调用前 | 再校验；失败明确文案 + 事件（非思维链） |
| 企微 / 网页 | 同一 `session.oa`，不按渠道分权 |

### 6.2 管理端 API

鉴权：权限点（建议挂现有 Skill 管理权限或新增 `sys.skill.visibility`）+ CSRF + `Idempotency-Key` + 审计；审计写失败则操作失败。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/admin/skills/{skill_id}/visibility` | 列出规则 |
| PUT | `/v1/admin/skills/{skill_id}/visibility` | **全量替换**；body `{"rules":[...]}`；**空数组 = 关闭裁剪（D19=C）** |
| GET | `/v1/admin/visibility/preview?oa=` | 可选；预览该 oa 可见 Skill（`tags` 本期空） |

员工侧不新增独立「我的权限」API；仍嵌在现有 `session.skills` 等字段。

### 6.3 OA 覆盖预留（D16=B）

- 定义 `TagProvider`（或等价 Protocol）：`load_tags(oa, office_token) -> list[str]`。
- 默认实现：返回 `[]`。
- 将来接 office-api 时只换实现；**禁止**用模型或客户端自报 tags。

---

## 7. 错误码与文案

| code | HTTP（示意） | 何时 | 员工文案方向 |
|------|--------------|------|--------------|
| `TOOL_NOT_AVAILABLE` | 与现网对话错误封装一致（复用已有码；事件可带 `reason=not_visible`） | 执行前 / 选中不可见能力 | 「该功能未对你开放」 |
| 现有 `SKILL_DISABLED` 等 | 保持 | 全局无可用 Skill 等 | 保持现网 |

- 文案与错误码**不**泄露「该 Skill 是否存在于他人」或具体规则内容。
- 可记可观测事件（skill/tool 名、oa、reason=`not_visible`）；**不**记思维链、**不**记 token/密钥。

---

## 8. 出站 MCP Client（接口与安全边界）

本期 **D18=A**：只钉契约，不连真实 Server。

| 边界 | 要求 |
|------|------|
| 地址 | 仅配置白名单；禁止任意 URL / SSRF |
| 身份 | 不得泄露 `master.key`、管理会话、保险箱明文；员工身份仅按约定注入且可关闭 |
| 映射 | 内部 `ToolSpec` ↔ 外部 tool name 的 Protocol/ABC |
| 默认实现 | `NoopOutboundMcpClient`：调用即「未配置 / 未启用」 |
| 结果 | 进模型前须白名单/截断（与现 Executor 纪律一致） |
| 员工面 | 不出现「MCP」字样 |

完整对接真实 MCP Server 与 OA 标签联调可并行后置，不在本规格验收内。

---

## 9. 权限与安全

- 身份仅 `session.oa`（及将来服务端 `tags`）；丢弃客户端自报 `oa` / `tags`。
- 管理写 = 权限点 + CSRF + Idempotency-Key + 审计；审计失败则失败。
- 密钥只写不读；日志/审计/异常无明文密钥。
- 可见性裁剪失败（不可见）≠ 业务越权成功；上游仍按员工 token 校验。

---

## 10. 测试计划（诚实分类）

| 项 | 标注 |
|----|------|
| 无规则 = 不裁剪（D19=C） | 自动化 |
| allow `oa` 命中 / 未命中 | 自动化 |
| deny 优先于 allow | 自动化 |
| `tag` 规则在 `tags=[]` 时不放行 | 自动化 |
| 欢迎页 / 候选集 / 执行前三处过滤 | 自动化 |
| 不可见时明确文案（D7=B） | 自动化 |
| PUT `rules=[]` 恢复全员（在启用前提下） | 自动化 |
| 管理写审计失败则失败 | 自动化或既有审计框架复用 |
| 前端管理可见性 UI（若本期做） | 自动化 + 手工 |
| OA 标签真实联调 | **未执行 / 外部依赖**（本期不做） |
| 真实 MCP Server | **未执行**（本期不做） |

禁止将未执行项标为通过。

---

## 11. 迁移与兼容

1. Alembic 增加 `agent_skill_visibility_rule`；空表时全员行为与发版前一致。
2. 现有 Skill **无需**立刻补规则。
3. 无 Redis 强制变更；管理端若加页需前端 build。
4. 权威设计 §12 / §8 在实施交付时短更新 API 与用语（实施计划 Task 内完成）。

---

## 12. 实施分期建议（供 writing-plans）

| Task 方向 | 内容 |
|-----------|------|
| 1 | 表 + migration + ORM |
| 2 | `VisibilityService` + 单测（含 D19/deny/tag 空） |
| 3 | 接入欢迎 / 帮助 / understand 候选 |
| 4 | Executor 执行前断言 + D7 文案 |
| 5 | 管理 API + 审计 + preview |
| 6 | `TagProvider` 空实现 + 出站 MCP Protocol + Noop |
| 7 | 职责用语文档（权威设计短更新）+ 交付说明 + 全量测试 |

---

## 13. 规格自检结论

- 无 TBD；错误码定为复用 `TOOL_NOT_AVAILABLE`；管理 UI 明确本期不做。
- D6 混合与 D16 预留不矛盾：规则可含 `tag`，解析靠 `TagProvider` 空实现。
- 范围可单份 implementation plan 覆盖（约 7 Task）。
