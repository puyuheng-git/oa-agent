# 交付说明：导出文件管理与 OSS 存储

**日期：** 2026-11-05  
**规格：** `docs/superpowers/specs/2026-11-05-export-file-management-design.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md` §5.2 / §9 / §12  

---

## 1. 功能

1. 新表 `agent_export_file` 登记每次 `sys.export`：员工、会话/运行、文件名、大小、存储方式（local / oss）、对象键。  
2. `ExportStore` 统一读写：OSS 配置齐则上传，否则落本地；按行上 `storage` 读取，不因当前配置切换而误读。  
3. 员工 `GET /v1/chat/exports/{ticket}`：须本人登录；可重复下载；不删对象、不校验 TTL。  
4. 管理端「文件管理」：分页列表、筛选、下载、「查看对话」深链；`ops.file.view`；列表与成功下载均审计，审计失败则请求失败。  
5. 系统设置新增 `oss` 组（AccessKey Secret 只写不读；可测连接）。  
6. 助手回复去掉「限时 / 只能下载一次」表述。

---

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/migrations/versions/0012_export_file.py` | 建表 + `ops.file.view` 种子 |
| `backend/oa_agent/db/models.py` | `ExportFile` |
| `backend/oa_agent/ids.py` | `new_export_file_id()` |
| `backend/oa_agent/auth/perms.py` | `ops.file.view` |
| `backend/oa_agent/executor/export_store.py` | 本地 / OSS 适配 |
| `backend/oa_agent/config/schema.py` | `oss` 配置组 |
| `backend/oa_agent/admin/settings_api.py` | OSS 测试连接 |
| `backend/oa_agent/executor/executor.py` | `Identity` 可选 thread/run |
| `backend/oa_agent/chat/service.py` | Identity 注入 thread/run |
| `backend/oa_agent/executor/builtin_runtime.py` | 导出登记与下载 |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | `_file_reply` 文案 |
| `backend/oa_agent/chat/router.py` | 员工下载 |
| `backend/oa_agent/admin/export_files_api.py` | 管理列表 / 下载 |
| `backend/oa_agent/main.py` | 路由注册 |
| `backend/oa_agent/executor/builtin_catalog.py` | 内置说明文案 |
| `backend/pyproject.toml` | `oss2` 依赖 |
| `backend/tests/test_export_store.py` | 存储与登记 |
| `backend/tests/test_export_routing.py` | 导出路由 |
| `backend/tests/test_admin_export_files.py` | 管理 API |
| `backend/tests/test_builtin_tools.py` | 内置 export 等 |
| `frontend/src/admin/router.ts` | 菜单「文件管理」 |
| `frontend/src/admin/views/FilesView.vue` | 列表页 |
| `frontend/src/admin/files.ts` | API 与类型 |
| `frontend/src/admin/files.spec.ts` | 深链辅助 |
| `frontend/src/admin/console/menuGroups.spec.ts` | 菜单权限 |
| `frontend/src/admin/toolGuides.ts` | 内置 Tool 说明 |
| `docs/design/2026-10-09-oa-langgraph-design.md` | §5.2 `oss`、§9、§12 |
| `docs/delivery/2026-11-05-export-file-management-delivery.md` | 本文 |

---

## 3. 迁移说明

1. 执行 Alembic 至 `0012_export_file`（`agent_export_file` 表；`agent_admin_role_perm` 为 super_admin 幂等插入 `ops.file.view`）。  
2. 已有 `data/exports/` 旁路 `ticket.json` + `.bin`：**不自动导入**；升级后旧票据无法通过下载接口消费（统一 404「文件不存在」），也不会出现在「文件管理」。  
3. 配置 OSS 后仅**新导出**走 OSS；历史行按登记时的 `storage` 读取，不做搬迁。

---

## 4. API 说明

| 方法 | 路径 | 权限 / 鉴权 | 说明 |
|------|------|-------------|------|
| GET | `/v1/chat/exports/{ticket}` | 员工会话；`row.oa == session.oa` | 流式下载；404 统一「文件不存在」 |
| GET | `/v1/admin/export-files` | `ops.file.view` | Query：`page`, `page_size`, `oa`, `thread_id`, `filename`, `start`, `end`；审计 `export_file.list` |
| GET | `/v1/admin/export-files/{file_id}/download` | `ops.file.view` | 流式下载；审计 `export_file.download` |
| （设置） | `/v1/admin/settings/*` | `sys.setting.view` / `sys.setting.edit` | 含 `oss` 组与测试连接 |

列表不返回 `ticket`、`object_key`；管理员用 `file_id` 下载。

---

## 5. 权限与安全

- `ops.file.view`：只读列表与下载；成功访问写审计，审计写失败则 HTTP 失败。  
- AccessKey Secret 仅 Vault；页面 / API / 日志 / 审计 / 异常无明文。  
- 不向浏览器返回 OSS 预签名 URL；`object_key` 非完整 URL；本地路径防 `..` 逃逸。  
- 员工下载只认服务端会话 `oa`；管理员与员工主体分离。

---

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `pytest tests/test_export_store.py tests/test_export_routing.py tests/test_admin_export_files.py tests/test_builtin_tools.py -q`（2026-11-05 重跑） | **自动化通过**（1 skipped） |
| `npm run test -- --run src/admin/files.spec.ts src/admin/console/menuGroups.spec.ts` | **自动化通过**（10 tests） |
| 真实阿里云 OSS 桶上传 / 下载 | **外部依赖未验证** |
| 浏览器冒烟（设置 OSS、导出、文件管理页） | **未执行** |

---

## 7. 未完成项

- 后台删除、批量清理、过期自动删对象。  
- 旧 `ticket.json` 不迁移至 `agent_export_file`。  
- 员工侧「我的导出」独立列表页（仍靠对话内下载入口）。

---

## 8. 下一阶段建议

- 可选：导出文件保留策略（按大小 / 天数清理、运维脚本），需单独规格与权限设计。  
- 在测试桶完成 OSS 端到端验证后，将「外部依赖未验证」改为手工通过并记录环境。
