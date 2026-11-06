# 导出文件管理与 OSS 存储设计

| 项 | 内容 |
|----|------|
| 日期 | 2026-11-05 |
| 状态 | **已确认**（用户审阅通过 2026-11-05） |
| 范围 | 员工导出文件长期登记；后台文件管理；本地 / 阿里云 OSS 二选一存储 |
| 权威设计 | `docs/design/2026-10-09-oa-langgraph-design.md`（冲突时以该文档为准） |
| 相关实现 | `builtin.export` / `sys.export`；`/v1/chat/exports/{ticket}`；对话记录页 |

### 已锁定决断

| ID | 选择 | 含义 |
|----|------|------|
| **D1** | **A** | 员工下载后文件长期保留；后台列表长期可见 |
| **D2** | **B** | 员工原链接长期有效；须本人已登录会话；他人不可用 |
| **D3** | 方案 1 | 数据库登记 + 统一存储接口；OSS 齐则上传 OSS，否则落本地 |
| **D4** | 后台转发下载 | 员工与管理员均经本服务读文件；不把 OSS 直链交给浏览器 |
| **D5** | 一期只增不删 | 后台可查看与下载；不提供删除 / 清理 |

**实施路径：** 新表 `agent_export_file` + 存储适配器；改造 `sys.export` 与员工下载；新权限与「文件管理」页；系统设置新增 OSS 配置组。

---

## 1. 背景与目标

**现状：**

- `sys.export` 把文件写到 `data/exports/{tenant}/`，旁路 `ticket.json` 仅含 `oa` / 文件名 / 过期时间，**无会话编号**。
- 员工 `/v1/chat/exports/{ticket}` 校验本人后下载，**下载即删除**，且有 TTL。
- 后台无导出文件列表，无法从文件追溯对话。

**目标：**

1. 每次导出在库中登记，可按员工 / 会话 / 文件名筛选，并能跳到「对话记录」。
2. 员工原下载链接长期有效，须本人登录；管理员在后台查看与下载。
3. 系统设置配置阿里云 OSS（密钥只写不读）：配齐则新文件上 OSS；未配齐则落服务器本地。

**验收素描：**

1. 未配 OSS 时导出落本地，员工可反复下载；他人票据 404。
2. OSS 配齐后新文件上 OSS，员工与管理员经本服务均可下载；上传失败则本次导出失败且不落库。
3. 后台「文件管理」列出记录，可跳转对话，下载与列表访问均审计。
4. 回复文案不再写「限时 / 只能下载一次」。

---

## 2. 非目标

- 后台删除、批量清理、过期自动删文件。
- 配置变更后搬迁已有文件（本地 ↔ OSS）；旧记录按登记时的 `storage` 读取。
- 员工侧「我的导出」列表页（仍靠对话消息里的下载入口）。
- 把 OSS 预签名 URL 或 Bucket 直链暴露给浏览器。
- 访问 `td_oa`；伪造下载量或健康状态。
- 改 Checkpoint / 图状态。

---

## 3. 数据模型

### 3.1 表 `agent_export_file`

| 列 | 说明 |
|----|------|
| `id` | 自增主键 |
| `file_id` | `exp_` + ULID，对外资源号 |
| `tenant_id` | 一期固定租户 |
| `ticket` | 现有下载票据（`token_urlsafe`），唯一 |
| `oa` | 导出员工；下载鉴权用 |
| `thread_id` | 可空；导出时有则写入，供追溯对话 |
| `run_id` | 可空；导出时有则写入 |
| `filename` | 展示与 Content-Disposition 用 |
| `size_bytes` | 字节数 |
| `content_type` | 如 `text/plain` / xlsx MIME |
| `storage` | `local` \| `oss` |
| `object_key` | 相对对象键；**禁止**完整 URL |
| `created_at` | UTC |

索引：`uk_export_file_id`、`uk_export_ticket`；`(tenant_id, created_at)`；`(tenant_id, oa, created_at)`；`(tenant_id, thread_id)`。

### 3.2 对象键约定

- 本地：相对 `data/exports/` 的路径段，形如 `{tenant}/{ticket}.bin`（与现实现目录一致；元数据改由表承担，不再依赖旁路 json 作为权威）。
- OSS：`{prefix}/{tenant}/{ticket}.bin`，`prefix` 来自配置（可空）；存库的 `object_key` 含 prefix 后的完整相对键，仍非 URL。

### 3.3 历史票据

已存在且未消费的 `ticket.json` + `.bin`：**不自动导入**。一期仅对新导出写表；旧一次性票据可按原逻辑消费或自然失效，不进入文件管理。交付说明中写明。

---

## 4. 存储与配置

### 4.1 OSS 配置组 `oss`（系统设置）

| 字段 | 类型 | 说明 |
|------|------|------|
| `endpoint` | url | 如 `https://oss-cn-hangzhou.aliyuncs.com` |
| `bucket` | str | Bucket 名 |
| `prefix` | str | 对象键前缀，可空 |
| `access_key_id` | str | AccessKey Id（非 secret 掩码字段；仍勿写入日志） |
| `access_key_secret` | secret | 只写不读；Vault 掩码 `已设置 · ****abcd` |

**已配置判定：** `endpoint`、`bucket`、`access_key_id` 非空，且 Vault 中 secret 已设置。缺任一项 → 走本地。

`testable=True`：保存前可测连接（真实 ListBuckets 或对目标 Bucket 的轻量探测）；失败如实返回，不伪造成功。保存走既有 `sys.setting.edit` + CSRF + Idempotency-Key + 审计；密钥变更审计只记「已变更」。

### 4.2 存储接口

统一适配器（示意）：

- `put(object_key, data) -> storage`：按当前配置选择 backend；成功返回 `local` 或 `oss`。
- `get(storage, object_key) -> bytes`：按行上登记的 `storage` 读取，**不**按「当前是否已配 OSS」重判。
- OSS put 失败 → 本次导出失败（`ToolError` / 用户可见「文件保存失败」），**不**回落本地，**不**写 `agent_export_file`。
- 本地写盘失败同理：失败不落库。

顺序：**先 put 成功，再 insert 行**。若 insert 失败：尽力删除刚写入的对象（本地 unlink / OSS delete），避免孤儿文件；仍失败则记运维日志（无密钥明文），不向员工暴露路径。

### 4.3 改造 `sys.export`

- 入参不变：`content`、`filename`；大小上限仍 `EXPORT_MAX_BYTES`。
- 生成 `ticket`、`file_id`；编码 / xlsx 逻辑不变。
- 从 `RunContext` / `Identity` 写入 `oa`、`thread_id`、`run_id`（无则空）。
- 返回给图的结构化结果：`ticket`、`filename`、`size_bytes`、`file_id`；**不再返回** `expires_in` / `expires_at`（或固定省略）。
- 废除下载后 `consume_export`；废除员工下载路径上的 TTL 拒绝。旁路 json 可不再写入（权威在表）；若过渡期仍写 json，不得作为鉴权唯一来源。

### 4.4 员工回复文案

`_file_reply` 改为类似：「已生成文件 **{filename}**，可下载。」去掉「链接限时有效 / 只能下载一次」。`data.kind=file` 仍含 `ticket`、`filename`、`size_bytes`，供对话前端构造 `/v1/chat/exports/{ticket}`。

---

## 5. API 与权限

### 5.1 员工下载（既有路径）

`GET /v1/chat/exports/{ticket}`

- 鉴权：员工会话；`row.oa == session.oa`；租户一致。
- 不校验过期；不删除对象与行。
- 按 `storage` + `object_key` 读字节；`Content-Disposition` 用登记文件名。
- 票据格式非法、不存在、不属于本人、或存储读失败 → 统一 404，文案「文件不存在」（不区分原因，避免探测他人票据）。

### 5.2 管理端

权限点（追加到 `PERMISSIONS`；`super_admin` 自动拥有）：

| 权限点 | 用途 |
|--------|------|
| `ops.file.view` | 导出文件列表与下载；**成功列表 / 成功下载均写审计**，审计写失败则请求失败 |

只读，无单独 manage；一期无写接口故无需 CSRF 删除类接口。OSS 配置仍用 `sys.setting.view` / `sys.setting.edit`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/admin/export-files` | 分页列表；筛选 `oa`、`thread_id`、`filename`（模糊）、时间范围；按 `created_at` 降序 |
| GET | `/v1/admin/export-files/{file_id}/download` | 流式下载；审计 `export_file.download` |

列表项字段：`file_id`、`oa`、`thread_id`、`run_id`、`filename`、`size_bytes`、`storage`、`created_at`。**不**返回 `ticket`、`object_key`（管理员用 `file_id` 下载；避免票据外泄与内部路径暴露）。

列表审计：`export_file.list`（含筛选摘要与条数）。下载审计：`export_file.download`（`file_id`、`oa`、`filename`）。

---

## 6. 后台 UI

- 菜单组：**运行监控**；路径 `/files`；标题「文件管理」；权限 `ops.file.view`。
- 表格：文件名、员工、大小、存储（本地 / OSS）、创建时间；操作：下载、「查看对话」。
- 「查看对话」：`router.push({ path: '/conversations', query: { thread: thread_id } })`，复用对话页已有 `route.query.thread` 打开抽屉。无 `thread_id` 时该按钮不可用并提示「暂无关联会话」。
- 无数据文案：「暂无数据」。不展示伪造统计。
- OSS 配置出现在「连接配置」设置页的新分组（随 `GROUPS` 自动渲染）；密钥框只写不读。

---

## 7. 安全边界

- 员工下载身份只认服务端会话 `oa`；模型 / 客户端自报 oa 一律不参与鉴权。
- 管理员与员工主体分离：管理员下载走 admin 权限与审计，不能冒充员工 ticket 会话。
- AccessKey Secret 仅 Vault；API / 页面 / 日志 / 审计 / 异常不得出现明文。
- `object_key` 禁止 `..`、绝对路径、符号链接逃逸（本地读路径必须落在 `data/exports/{tenant}/` 下）。
- 不向浏览器返回 OSS 签名 URL。

---

## 8. 测试要点

| 场景 | 期望 |
|------|------|
| 未配 OSS 导出 | `storage=local`；表有行；含 `thread_id`（有上下文时） |
| 员工本人重复下载 | 两次均成功；文件与行仍在 |
| 他人员工 ticket | 404 |
| OSS 配齐导出 | put 被调用；`storage=oss`；经本服务可读 |
| OSS put 失败 | 工具失败；无表行 |
| 无 `ops.file.view` | 列表 / 下载 403 |
| 有权限列表与下载 | 200 + 审计记录 |
| 设置页 secret | 只返掩码；留空不覆盖 |

自动化：pytest（SQLite 内存 + 本地存储假适配 / OSS 客户端 mock）；前端 Vitest 覆盖路由权限与对话深链参数。手工：真实 OSS 连接测试标为「外部依赖未验证」直至在测试桶验证。

---

## 9. 交付物清单（实施时）

- 迁移：`agent_export_file`
- 后端：模型、ids `new_export_file_id`、存储适配器、`builtin_runtime._export` / 下载改造、admin API、perms、OSS `GroupDef`、测连接
- 前端：Files 视图、路由菜单、设置组展示（随 schema）、对话跳转
- 文档：本规格；阶段交付说明（功能 / 文件清单 / 迁移 / API / 权限 / 测试结果 / 未完成项）
- **不**提交 `data/` 下导出实体文件

---

## 10. 与权威设计的关系

本能力属于 Tool 导出结果的可运营化与对象存储配置，不提前实现设计 §13 中尚未启动的其它阶段能力。配置版本化（P5）不在本期；OSS 组走现有设置热更新即可。若与 `docs/design/` 冲突，以权威设计为准并回写修订说明。
