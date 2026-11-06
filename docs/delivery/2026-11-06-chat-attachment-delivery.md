# 交付说明：员工上传文件

**日期：** 2026-11-06  
**规格：** `docs/superpowers/specs/2026-11-06-chat-attachment-design.md`  
**计划：** `docs/superpowers/plans/2026-11-06-chat-attachment.md`  
**权威设计：** `docs/design/2026-10-09-oa-langgraph-design.md`（已索引本规格）

未提交 git。

## 1. 功能

1. 员工在对话里一次上传最多 5 个文件，单文件最大 20MB。类型为 xlsx、xls、docx、pdf、md、csv，以及 png、jpeg、webp、gif。扩展名和文件头都要符合，一批里有一个不合法则整批不落盘。
2. 未发送的文件只留在浏览器。发送时先上传，成功后再把正文和 `attachment_ids` 交给流式接口。只有附件、没有正文也可以发送。上传失败或中途停止时，输入区里的字和文件留下。
3. 输入区可粘贴允许的文件类型（含截图与从资源管理器复制的 Excel、Word、PDF 等）；纯文字仍贴进输入框。拖拽覆盖整块对话面板（消息列表 + 输入区）。
4. 已发送的上传写入 `agent_export_file`，`origin=upload`。与导出共用存储：OSS 配齐走 OSS，否则落本地。同一租户内相同字节只存一份。
5. 员工只能下载自己的、已写入消息的上传。导出票据不能下载上传文件。
6. 管理端文件管理增加来源列和筛选。列表与下载仍走 `ops.file.view`，访问即审计。未发送的上传不出现在列表里。
7. 模型先看目录。内容放得进 3 万字和 8 张图时整份送入，否则按范围读，一轮最多 20 次。同一会话里改问业务时仍走原来的办公工具链。

## 2. 文件清单

| 路径 | 说明 |
|------|------|
| `backend/migrations/versions/0013_upload_file.py` | `origin`、`sha256`、`media_kind`、`in_message` |
| `backend/oa_agent/db/models.py` | `ExportFile` 新列，旧导出行默认为已发送的导出 |
| `backend/oa_agent/ids.py` | `new_upload_file_id()`，前缀 `upl_` |
| `backend/oa_agent/chat/attachment_admit.py` | 整批准入 |
| `backend/oa_agent/chat/attachment_store.py` | 内容哈希对象键 |
| `backend/oa_agent/chat/attachment_files.py` | 登记、绑定、本人下载 |
| `backend/oa_agent/chat/attachment_extract.py` | 抽文本、图片归一化 |
| `backend/oa_agent/chat/attachment_loop.py` | 目录、分片读取、阅读循环 |
| `backend/oa_agent/chat/router.py` | 上传、下载、发送体 |
| `backend/oa_agent/chat/service.py` | 空正文可带附件发送 |
| `backend/oa_agent/runtime/engine.py` | 图输入带 `attachment_ids` |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | 有已发送上传时先读文件 |
| `backend/oa_agent/executor/builtin_runtime.py` | 导出下载拒绝上传票据 |
| `backend/oa_agent/admin/export_files_api.py` | 来源筛选 |
| `backend/pyproject.toml` | pillow、openpyxl、xlrd、python-docx、pypdf |
| `frontend/src/admin/files.ts`、`views/FilesView.vue` | 来源列和筛选 |
| `oa-agent-chat` 的 `api.ts`、`App.vue`、`Composer.vue`、`ChatPanel.vue`、`files-from-clipboard.ts` | 选择、整板拖拽、文件粘贴、上传后发送 |

## 3. 迁移

新迁移 `0013_upload_file`，上一版本 `0012_export_file`。已有导出行补 `origin=export`、`in_message=true`。不改已发布的 `0012`。

部署前在 `backend/` 执行迁移到该版本。新依赖随 `uv sync` 安装。

## 4. API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/chat/attachments` | multipart 字段 `files`。返回 `file_id`、文件名、大小、`media_kind`。此时尚未进入文件管理 |
| POST | `/v1/chat/messages`、`/v1/chat/messages/stream` | 增加 `attachment_ids`。`message` 可为空，但不能和附件同时空 |
| GET | `/v1/chat/files/{file_id}` | 本人下载已发送的上传 |
| GET | `/v1/admin/export-files?origin=upload\|export` | 缺省含导出和已发送上传。非法 `origin` 为 422 |

响应不含 `object_key`、`sha256`、`ticket`。

## 5. 权限与安全

- 员工接口用会话凭证。管理端列表和下载仍是 `ops.file.view`，访问即审计。
- 下载要求登记行的 `oa` 等于当前员工，且 `in_message` 为真，否则「文件不存在」。
- 对象键是相对路径，带租户段。不把路径、对象键或 OSS 直链交给模型或浏览器。
- 抽出的文本按不可信数据送入模型。不执行宏，不算公式，不做 OCR。
- 本期不删除对象，也不提供撤回。

## 6. 测试结果

| 项 | 结果 |
|----|------|
| `uv run pytest` 计划中的 8 个后端测试文件（`backend/`，2026-11-06） | **自动化通过**（退出码 0） |
| `frontend`：`npm run test -- src/admin/files.spec.ts` | **自动化通过**（6） |
| `oa-agent-chat`：`npm run test -- src/chat/components/composer-files.spec.ts` | **自动化通过**（17） |
| 浏览器里选择文件、拖拽、粘贴截图、看文件管理来源列 | **未执行** |
| 配齐 OSS 后实际上传 | **外部依赖未验证** |
| 真实模型阅读大文件、拒绝图片 | **未执行** |

后端命令：

```text
uv run pytest tests/test_upload_file_model.py tests/test_attachment_admit.py tests/test_attachment_store.py tests/test_chat_attachments.py tests/test_admin_export_files.py tests/test_attachment_extract.py tests/test_attachment_loop.py tests/test_attachment_graph.py -q --tb=line
```

## 7. 未完成项

- 模型拒绝图片时，员工看到「当前模型无法查看图片」，这一轮以聊天回复结束，运行状态不是失败。
- 阅读循环会从模型可见文本里去掉 `http` 这四个字母，文件正文里的网址可能被改掉。
- 非流式 `sendMessage` 仍不带 `attachment_ids`。对话页走流式接口。
- 企微通道不能上传。没有删除和 OCR。
- 浏览器里真实粘贴文件、拖到消息列表，仍未手工验证。

## 8. 下一步

在浏览器里用员工会话走一遍：粘贴截图或 PDF、拖一个 xlsx 到消息列表和输入区、看文件管理里的「用户上传」，并确认导出文件仍能下载。OSS 配齐后再传一次，确认对象在桶里、下载仍经本服务。
