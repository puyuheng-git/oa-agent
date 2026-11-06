# 员工上传文件 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 员工在对话里上传 Excel、Word、PDF、Markdown、CSV 和图片（含粘贴截图），模型按文件内容回答；已发送的上传出现在文件管理，并与导出文件区分。

**Architecture:** 浏览器在发送时整批上传。服务端校验后按内容哈希写入现有 `ExportStore`（OSS 配齐走 OSS，否则本地），在 `agent_export_file` 登记，消息成功后 `in_message=true`。Checkpoint 不存字节。有已发送上传时，模型先看目录；放得进余量就带全文和图片，否则用运行时注入的 `sys.attachment_read` 按范围读，读完再写回答。办公查询仍走原来的 understand → call_tool。

**Tech Stack:** FastAPI、SQLAlchemy 2、Alembic、Pillow、openpyxl、xlrd、python-docx、pypdf、Vue 3、pytest、vitest。

**Spec:** `docs/superpowers/specs/2026-11-06-chat-attachment-design.md`

## Global Constraints

- 正文仍受 `message_max_chars` 限制（默认 500，最大 2000）。附件不占这 2000 字。单次最多 5 个，单文件最大 20MB。
- 图片只收 png、jpeg、webp、gif。文档只收 xlsx、xls、docx、pdf、md、csv。扩展名和文件头都要符合。
- 对话记录和接口响应不含字节、不含 `object_key`、不含服务器路径。模型句柄只有文件名和 sha256 前 8 位。
- 员工下载须本人会话且 `in_message` 为真，否则 404「文件不存在」。上传票据不能走 `/v1/chat/exports/{ticket}`。
- 管理端列表与下载仍是 `ops.file.view`，访问即审计；审计失败则请求失败。
- 对象缺失或哈希不符：整次请求失败，提示「附件已损坏或无法读取，请重新上传」，不空内容重试。模型拒绝图片：提示「当前模型无法查看图片」，不空内容重试。
- 用量只记供应商 usage。没有视觉 token 时不估算。
- 不写 `BUILTIN_CATALOG`，不出现在欢迎页技能里，不用 `sys.fs_read`，不做 OCR，不删除对象。
- 回复与文档中文；代码标识符英文。测试不得把未执行说成通过。
- Commit 仅在用户明确要求时执行；无 git 时跳过 Commit 步骤。

---

## File map

| 文件 | 职责 |
|------|------|
| `backend/migrations/versions/0013_upload_file.py` | 给 `agent_export_file` 加 `origin`、`sha256`、`media_kind`、`in_message` |
| `backend/oa_agent/db/models.py` | `ExportFile` 新列及默认值，旧的导出插入不用改调用点 |
| `backend/oa_agent/ids.py` | `new_upload_file_id()` → `upl_` + ULID |
| `backend/oa_agent/chat/attachment_admit.py` | 整批准入：类型、文件头、空文件、大小、个数、Office 解压上限 |
| `backend/oa_agent/chat/attachment_store.py` | 内容哈希对象键；经 `ExportStore` 写入与读取 |
| `backend/oa_agent/chat/attachment_files.py` | 登记、绑定到消息、按会话列出、员工读取 |
| `backend/oa_agent/chat/attachment_extract.py` | 抽出文本、结构摘要、图片归一化 |
| `backend/oa_agent/chat/attachment_loop.py` | 目录、单次读取、阅读循环 |
| `backend/oa_agent/chat/router.py` | 上传、下载、发送体增加 `attachment_ids` |
| `backend/oa_agent/chat/service.py` | 空正文在有附件时可发送；把附件传入运行 |
| `backend/oa_agent/executor/builtin_runtime.py` | 导出下载拒绝 `origin != export` |
| `backend/oa_agent/admin/export_files_api.py` | 列表返回并筛选 `origin` |
| `backend/oa_agent/runtime/graphs/oa_assistant.py` | 有上传时把目录交给模型；`read` 走循环，`tool` 走原链路 |
| `backend/oa_agent/runtime/engine.py` | `invoke` 接受本轮 `attachment_ids` |
| `frontend/src/admin/files.ts`、`views/FilesView.vue` | 来源列和筛选 |
| `oa-agent-chat` 的 `Composer.vue`、`App.vue`、`api.ts` | 选择、拖拽、粘贴、整批上传后发送 |

本地对象键：`{tenant}/attachments/v1/objects/{sha256前2位}/{sha256}`。OSS 再在前面加已配置的 prefix。必须带租户段，才能通过 `ExportStore._local_path` 的目录约束。同一租户内相同字节只存一份。

---

### Task 1: 迁移、模型、上传 ID

**Files:**
- Create: `backend/migrations/versions/0013_upload_file.py`
- Modify: `backend/oa_agent/db/models.py` 的 `ExportFile`
- Modify: `backend/oa_agent/ids.py`
- Test: `backend/tests/test_upload_file_model.py`

**Interfaces:**
- Produces: `new_upload_file_id() -> str`，前缀 `upl_`
- Produces: `ExportFile.origin` 默认 `"export"`，`sha256` 可空，`media_kind` 可空，`in_message` 默认 `True`
- Migration `revision = "0013_upload_file"`，`down_revision = "0012_export_file"`

- [ ] **Step 1: 写失败测试**

```python
def test_upload_file_id_prefix():
    from oa_agent.ids import new_upload_file_id
    assert new_upload_file_id().startswith("upl_")


def test_export_row_defaults_remain_export(session):
    from oa_agent.db.models import ExportFile
    from oa_agent.ids import new_export_file_id
    row = ExportFile(
        file_id=new_export_file_id(), tenant_id="dscpa", ticket="ticket_export_default_01",
        oa="a", filename="a.txt", size_bytes=1, content_type="text/plain",
        storage="local", object_key="dscpa/ticket_export_default_01.bin",
    )
    session.add(row)
    session.commit()
    assert row.origin == "export"
    assert row.in_message is True
    assert row.sha256 is None
```

`session` 用现有测试里跑过 Alembic 的 SQLite fixture。若仓库里的 fixture 名叫 `db`，用那个名字，不要新造数据库。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_upload_file_model.py -v`（在 `backend/`）

Expected: FAIL，`new_upload_file_id` 不存在或列不存在。

- [ ] **Step 3: 实现**

`ids.py` 增加：

```python
def new_upload_file_id() -> str:
    return _new("upl")
```

`ExportFile` 增加列，默认值让现有 `db.add(ExportFile(...))` 不传新字段也能插入：

```python
origin: Mapped[str] = mapped_column(sa.String(16), default="export", server_default="export")
sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
media_kind: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
in_message: Mapped[bool] = mapped_column(sa.Boolean, default=True, server_default=sa.true())
```

迁移用 `op.add_column`。`origin` 与 `in_message` 带 server_default，旧行成为导出且已发送。SQLite 布尔用 `sa.Boolean()`。索引 `ix_export_origin` 于 `(tenant_id, origin, created_at)`。downgrade 按相反顺序删索引和列。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_upload_file_model.py tests/test_admin_export_files.py -v`

Expected: PASS。旧导出测试仍通过，说明默认值没有破坏现有插入。

- [ ] **Step 5: Commit**

仅当用户要求提交时：

```bash
git add backend/migrations/versions/0013_upload_file.py backend/oa_agent/db/models.py backend/oa_agent/ids.py backend/tests/test_upload_file_model.py
git commit -m "feat: add upload columns on export file registry"
```

---

### Task 2: 整批准入

**Files:**
- Create: `backend/oa_agent/chat/attachment_admit.py`
- Test: `backend/tests/test_attachment_admit.py`

**Interfaces:**
- Produces: `AdmitError(message: str)`
- Produces: `admit_batch(files: list[tuple[str, bytes]]) -> list[Admitted]`
- `Admitted` 字段：`filename: str`，`data: bytes`，`media_kind: Literal["image","document"]`，`content_type: str`，`extension: str`
- 任一文件失败则抛 `AdmitError`，不返回部分结果

- [ ] **Step 1: 写失败测试**

```python
import pytest
from oa_agent.chat.attachment_admit import AdmitError, admit_batch

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

def test_png_and_pdf_pass():
    rows = admit_batch([("shot.png", PNG), ("a.pdf", PDF)])
    assert [r.media_kind for r in rows] == ["image", "document"]

def test_one_bad_rejects_batch():
    with pytest.raises(AdmitError, match="只能上传"):
        admit_batch([("shot.png", PNG), ("a.exe", b"MZ")])

def test_empty_file():
    with pytest.raises(AdmitError, match="文件是空的"):
        admit_batch([("a.csv", b"")])

def test_too_many():
    with pytest.raises(AdmitError, match="一次最多 5 个文件"):
        admit_batch([(f"{i}.csv", b"a") for i in range(6)])

def test_csv_with_nul_rejected():
    with pytest.raises(AdmitError, match="只能上传"):
        admit_batch([("a.csv", b"a\x00b")])

def test_renamed_png_as_pdf_rejected():
    with pytest.raises(AdmitError, match="只能上传"):
        admit_batch([("a.pdf", PNG)])
```

再补：超过 20MB 的消息是「单个文件不能超过 20MB」；`.xlsm`、`.doc` 拒绝；合法 CSV（`b"a,b\n1,2"`）与 UTF-8 Markdown 通过。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_attachment_admit.py -v`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现**

`admit_batch` 先数个数，再逐个检查，全部通过才返回。文件头：

| 扩展名 | 头 |
|--------|----|
| png | `\x89PNG\r\n\x1a\n` |
| jpg/jpeg | `\xff\xd8\xff` |
| gif | `GIF87a` 或 `GIF89a` |
| webp | 前 4 字节 `RIFF` 且第 8–12 字节 `WEBP` |
| pdf | `%PDF` |
| xls | `\xd0\xcf\x11\xe0` |
| xlsx/docx | `PK\x03\x04`，且 zip 内分别有以 `xl/`、`word/` 开头的条目 |

用 `zipfile.ZipFile` 读 xlsx/docx。条目数 `> 2000`，或 `sum(info.file_size) > 50 * 1024 * 1024`，抛「只能上传 Excel、Word、PDF、Markdown、CSV，以及 png、jpeg、webp、gif 图片」。不要把 zip 的内部异常原文返回给员工。

csv/md/markdown：先 UTF-8，失败再 GBK；含 NUL 或两种都解不出，用同一句类型错误。文件名只保留最后一段，去掉路径。

图片像素上限放在 Task 7 的归一化里做（需要 Pillow）。准入阶段只查字节头和 20MB。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_attachment_admit.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交本任务文件，说明写明整批准入。

---

### Task 3: 按哈希存储

**Files:**
- Create: `backend/oa_agent/chat/attachment_store.py`
- Test: `backend/tests/test_attachment_store.py`

**Interfaces:**
- Consumes: `ExportStore.get` / 其 OSS 与本地写入行为
- Produces: `upload_object_key(tenant: str, sha256: str, prefix: str = "") -> str`
- Produces: `put_upload(store: ExportStore, data: bytes) -> tuple[str, str, str]`，返回 `(storage, object_key, sha256)`
- Produces: `read_upload(store: ExportStore, storage: str, object_key: str, sha256: str) -> bytes`；哈希不符抛 `ToolError("ATTACHMENT_CORRUPT", ...)`

- [ ] **Step 1: 写失败测试**

```python
from oa_agent.chat.attachment_store import put_upload, read_upload, upload_object_key
from oa_agent.executor.export_store import ExportStore

def test_same_bytes_one_object(tmp_path):
    store = ExportStore(data_dir=tmp_path, tenant_id="dscpa")
    a = put_upload(store, b"same-bytes")
    b = put_upload(store, b"same-bytes")
    assert a[1] == b[1]
    assert a[2] == b[2]
    assert read_upload(store, *a) == b"same-bytes"

def test_key_has_no_scheme():
    key = upload_object_key("dscpa", "ab" * 32)
    assert "://" not in key
    assert key.startswith("dscpa/attachments/v1/objects/ab/")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_attachment_store.py -v`

Expected: FAIL

- [ ] **Step 3: 实现**

`sha256` 用 `hashlib.sha256(data).hexdigest()`。键：

```python
def upload_object_key(tenant: str, sha256: str, prefix: str = "") -> str:
    body = f"{tenant}/attachments/v1/objects/{sha256[:2]}/{sha256}"
    prefix = prefix.strip().strip("/")
    return f"{prefix}/{body}" if prefix else body
```

`put_upload`：OSS 已配置时用 `store._oss_bucket().put_object`；对象已存在则直接返回现有键，不再写第二份。本地用 `ExportStore._local_path` 写文件；文件已存在则不覆盖。OSS 失败抛现有 `ToolError("EXPORT_STORE_FAILED", "文件保存失败")`，不改写本地。`read_upload` 用 `store.get`，再核对哈希，不符抛 `ToolError("ATTACHMENT_CORRUPT", "附件已损坏或无法读取，请重新上传", user_message="附件已损坏或无法读取，请重新上传")`。

不要把 AccessKey 写进日志。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_attachment_store.py tests/test_export_store.py -v`

Expected: PASS。导出用的 ticket 键测试仍然通过。

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 4: 上传登记与员工下载

**Files:**
- Create: `backend/oa_agent/chat/attachment_files.py`
- Modify: `backend/oa_agent/chat/router.py`
- Modify: `backend/oa_agent/executor/builtin_runtime.py` 的 `take_export`
- Test: `backend/tests/test_chat_attachments.py`

**Interfaces:**
- Consumes: `admit_batch`，`put_upload`，`new_upload_file_id`
- Produces: `save_uploads(db, store, *, tenant_id, oa, thread_id, files) -> list[dict]`
- 返回项只有 `file_id`、`filename`、`size_bytes`、`media_kind`。`in_message` 为 False
- Produces: `bind_uploads(db, *, tenant_id, oa, thread_id, file_ids: list[str]) -> None`
- Produces: `read_owned(db, store, *, tenant_id, oa, file_id) -> tuple[ExportFile, bytes]`
- HTTP: `POST /v1/chat/attachments` 返回 `{"files":[{file_id, filename, size_bytes, media_kind}]}`
- HTTP: `GET /v1/chat/files/{file_id}`

- [ ] **Step 1: 写失败测试**

用 `tests/test_chat.py` 的 `chat` fixture 和 `open_chat`。

```python
def test_upload_hides_object_key_until_sent(chat):
    h = open_chat(chat)
    uploaded = chat.post(
        "/v1/chat/attachments",
        headers=h,
        files=[("files", ("note.csv", b"a,b\n1,2\n", "text/csv"))],
    )
    assert uploaded.status_code == 200
    body = uploaded.json()
    assert "object_key" not in uploaded.text
    file_id = body["files"][0]["file_id"]
    denied = chat.get(f"/v1/chat/files/{file_id}", headers=h)
    assert denied.status_code == 404
    assert denied.json()["error"]["message"] == "文件不存在"

def test_bad_file_rejects_whole_batch(chat):
    h = open_chat(chat)
    resp = chat.post(
        "/v1/chat/attachments",
        headers=h,
        files=[
            ("files", ("note.csv", b"a,b\n1,2\n", "text/csv")),
            ("files", ("run.exe", b"MZ", "application/octet-stream")),
        ],
    )
    assert resp.status_code == 422
```

再写：绑定后本人下载得到原字节；另一个 `oa` 得到 404；上传行的 `ticket` 请求 `/v1/chat/exports/{ticket}` 得到 404。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_chat_attachments.py -v`

Expected: FAIL，路由 404。

- [ ] **Step 3: 实现**

`save_uploads` 在一个事务里：`admit_batch` 失败则不写对象、不插入。通过后逐个 `put_upload`。中途存储失败则已插入的行回滚；已经写出的对象允许留下，不在这里删除。`ticket` 用 `secrets.token_urlsafe(18)`，保证唯一。`filename` 最长 255。

`bind_uploads`：`file_ids` 长度 0–5。每个 id 必须是本租户、本 `oa`、本 `thread_id`、`origin=upload`、`in_message` 为假。缺一则抛 `AppError(404, "NOT_FOUND", "文件不存在")`，整个事务不改任何行。成功则把这些行的 `in_message` 设为 True。

`read_owned`：行必须 `origin=upload`、`in_message` 为真、`oa` 匹配，再用 `read_upload`。否则 `AppError(404, "NOT_FOUND", "文件不存在")`。

`take_export` 读到行后若 `origin != "export"`，按文件不存在返回，不要把字节写出。

上传路由使用现有 `chat_auth`。表单字段名 `files`，可多个。会话还没有 `thread_id` 时先沿用发送消息前创建会话的现有函数，再保存。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_chat_attachments.py tests/test_export_routing.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 5: 发送接口带上附件

**Files:**
- Modify: `backend/oa_agent/chat/router.py` 的 `MessageIn`、`post_message`、`post_message_stream`
- Modify: `backend/oa_agent/chat/service.py` 的 `guard_message`、`handle_message`、`start_run`
- Modify: `backend/oa_agent/runtime/engine.py` 的 `invoke`
- Test: `backend/tests/test_chat_attachments.py` 追加用例

**Interfaces:**
- `MessageIn.attachment_ids: list[str]`，默认空，最多 5，每项最长 40
- `guard_message(..., attachment_ids: list[str] | None = None)`
- `engine.invoke(..., attachment_ids: list[str] | None = None)`，写入图输入 `attachment_ids`

- [ ] **Step 1: 写失败测试**

用 `tests/test_chat.py` 的 `open_chat` 和 `send`（`send` 已把 `**extra` 放进 JSON）。

```python
def test_blank_message_allowed_with_attachment(chat):
    h = open_chat(chat)
    uploaded = chat.post(
        "/v1/chat/attachments",
        headers=h,
        files=[("files", ("note.csv", b"a,b\n1,2\n", "text/csv"))],
    )
    file_id = uploaded.json()["files"][0]["file_id"]
    resp = send(chat, h, "", attachment_ids=[file_id], client_msg_id="att-blank-0001")
    assert resp.status_code == 200
```

再断言该行 `in_message` 为真。另写三条：空正文且没有附件时 422「消息不能为空」；正文长于 `message_max_chars` 时 422；同一个 `client_msg_id` 再送一次为 409。假模型沿用 `tests/test_chat.py` 里已有的替换方式，不要调用真实 LLM。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_chat_attachments.py -v -k "empty or dedupe or max_chars"`

Expected: FAIL

- [ ] **Step 3: 实现**

`guard_message`：`attachment_ids` 非空时允许空白正文；空白且没有附件才报「消息不能为空」。有正文时仍按 `message_max_chars` 拒绝。`client_msg_id` 的 `set_nx` 保持不变。不要按空正文做第二次去重。

在 `handle_message` 进入 `start_run` 之前调用 `bind_uploads`。绑定失败则不要启动运行。`invoke` 的图输入改为：

```python
{"run_id": ctx.recorder.run_id, "message": message, "attachment_ids": list(attachment_ids or [])}
```

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_chat_attachments.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 6: 管理端筛选来源

**Files:**
- Modify: `backend/oa_agent/admin/export_files_api.py`
- Test: `backend/tests/test_admin_export_files.py`

**Interfaces:**
- `GET /v1/admin/export-files?origin=upload|export`
- 列表项增加 `origin`、`media_kind`。不增加 `object_key`、`sha256`、`ticket`

- [ ] **Step 1: 写失败测试**

种子一行 `origin=export`、一行 `origin=upload` 且 `in_message=True`、一行 `origin=upload` 且 `in_message=False`。断言：

- 缺省列表含导出和已发送上传，不含未发送上传。
- `origin=upload` 只有已发送上传。
- `origin=export` 只有导出。
- 列表响应文本里没有 `object_key`。
- 下载上传文件记一条 `export_file.download` 审计。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_admin_export_files.py -v -k origin`

Expected: FAIL

- [ ] **Step 3: 实现**

`_item` 增加 `origin` 与 `media_kind`。查询在 `origin` 有值时加条件。上传行再加 `in_message.is_(True)`。非法 `origin` 返回 422。下载逻辑不用改，它已经按 `file_id` 读 `storage` 和 `object_key`。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_admin_export_files.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 7: 抽出内容与图片归一化

**Files:**
- Modify: `backend/pyproject.toml` 增加 `pillow`、`openpyxl`、`xlrd`、`python-docx`、`pypdf`
- Create: `backend/oa_agent/chat/attachment_extract.py`
- Test: `backend/tests/test_attachment_extract.py`

**Interfaces:**
- Produces: `extract_upload(filename: str, data: bytes) -> Extracted`
- `Extracted` 字段：`text: str`，`profile: str`，`sheets: list[Sheet]`，`pages: list[str]`，`width: int`，`height: int`，`image_png: bytes | None`，`unreadable: str | None`
- `Sheet` 字段：`name: str`，`columns: list[str]`，`rows: list[list[str]]`，`numeric_summary: str`

- [ ] **Step 1: 写失败测试**

1. CSV `a,b\n1,2\n` 的 `text` 含这两行，`profile` 含列名 `a` 和 `b`。
2. 用 openpyxl 在测试里写一个两张表的 xlsx。`profile` 同时含两张表名和各自行数。
3. 最小 PDF（Task 2 的 `PDF` 字节若 pypdf 解不开，就在测试里用 pypdf 写一页「合同正文」）。`pages` 含该句。
4. 一张 1×1 png。`image_png` 非空，`width == 1`。
5. 构造单边 9000 像素的 png，`extract_upload` 抛 `AdmitError`，消息仍是类型那一句。实现可以用 Pillow 新建图，不要提交大文件。
6. 加密 xlsx 解不开时 `unreadable == "已加密，无法读取"`，不抛给调用方。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_attachment_extract.py -v`

Expected: FAIL

- [ ] **Step 3: 实现**

`uv add pillow openpyxl xlrd python-docx pypdf`（在 `backend/`）。

- CSV：UTF-8，失败则 GBK。用 `csv` 模块读全部行。`profile` 写列名和行数。
- Markdown：全文进 `text`。以 `#` 开头的行进 `profile`。
- xlsx：`openpyxl.load_workbook(..., data_only=False, read_only=True)`。单元格用已存值，公式保留公式文本，不算值。
- xls：`xlrd.open_workbook(file_contents=data)`。
- docx：段落和表格。标题样式进 `profile`。
- pdf：`pypdf.PdfReader`。每页 `extract_text()`。抽不出文字的页在 `pages` 里放「没有可提取的文字」。有 outline 则写进 `profile`。
- 图片：Pillow 打开，`ImageOps.exif_transpose`，转 RGB 或 RGBA。长边大于 2048 才缩小到 2048。动图只取第一帧。总像素大于 64_000_000 或单边大于 8192：抛 `AdmitError("只能上传 Excel、Word、PDF、Markdown、CSV，以及 png、jpeg、webp、gif 图片")`。输出 PNG 字节到 `image_png`。
- `BadZipFile`、口令错误、`pypdf` 加密：`unreadable = "已加密，无法读取"`。

`profile` 超过 8000 字时保留每张表的表名和行数，列名截断，末尾加「已截断」。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_attachment_extract.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 8: 目录、读取与阅读循环

**Files:**
- Create: `backend/oa_agent/chat/attachment_loop.py`
- Test: `backend/tests/test_attachment_loop.py`

**Interfaces:**
- Produces: `TEXT_BUDGET = 30_000`，`IMAGE_BUDGET = 8`，`MAX_READS = 20`，`MAX_ROWS = 200`，`MAX_PAGES = 3`，`MAX_SLICE_CHARS = 8000`
- Produces: `project(files: list[LoadedFile]) -> Projection`
- `Projection.mode` 为 `"full"` 或 `"catalog"`
- `Projection.catalog_text: str`
- `Projection.full_text: str`
- `Projection.images: list[tuple[str, bytes]]`，元素是 `(file_id, png)`
- Produces: `read_slice(file: LoadedFile, args: ReadArgs) -> str`
- Produces: `run_loop(files, ask) -> LoopResult`
- `ask(messages: list) -> dict`，字典形如 `{"action":"answer","answer":"..."}` 或 `{"action":"read","file_id","sheet","row_offset","page_from","char_offset"}` 或 `{"action":"tool","steps":[...]}`
- `LoopResult.kind` 为 `"answer"` 或 `"delegate"`
- `LoopResult.answer: str`
- `LoopResult.steps: list`
- `LoopResult.read_note: str`

`LoadedFile` 含 `file_id`、`filename`、`media_kind`、`size_bytes`、`sha256`、`extracted: Extracted`。

- [ ] **Step 1: 写失败测试**

1. 一个 10 字的 CSV：`project(...).mode == "full"`，`full_text` 含正文。
2. 把 `TEXT_BUDGET` 在测试里通过构造超过 3 万字的 `Extracted.text` 触发：`mode == "catalog"`，`catalog_text` 含表名，`full_text == ""`。
3. `read_slice` 对 250 行的表，`row_offset=0` 只返回 200 行。
4. `ask` 第一次返回 read，第二次返回 answer：`run_loop` 的 `answer` 含第二次的句子，`read_note` 含读过的范围。
5. `ask` 连续返回 read：第 21 次不再调用，`answer` 仍非空（用已读内容强制回答；测试里的 `ask` 在第 20 次之后若仍被调用则失败）。
6. `ask` 返回 `{"action":"tool","steps":[{"tool":"builtin.export","args":{}}]}`：`kind == "delegate"`，且 `ask` 只被调用一次。
7. `unreadable == "已加密，无法读取"` 的文件出现在 `catalog_text` 里，`read_slice` 返回同一句，不抛异常。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_attachment_loop.py -v`

Expected: FAIL

- [ ] **Step 3: 实现**

`project`：把每个文件的 `profile` 或 `unreadable` 拼进目录。全文长度（各文件 `text` 之和）不超过 3 万且图片张数不超过 8 时，`mode=full`，带上 `text` 和 `image_png`。否则 `mode=catalog`。

`read_slice`：表格按 `row_offset` 取最多 200 行；PDF 从 `page_from` 取最多 3 页；文本从 `char_offset` 取最多 8000 字。越界返回「没有更多可读内容」。加密和扫描页返回 `unreadable` 或页内的「没有可提取的文字」。

`run_loop`：先 `project`。消息里目录在前，全文在后。图片以调用方稍后放入模型内容块的字节列表放在 `Projection.images`，本函数只把「图片 file_id、宽高」写进文本。`ask` 返回 `tool` 且还没有读过文件时，`kind=delegate`。返回 `answer` 则停止。返回 `read` 则把 `read_slice` 结果追加到消息，最多 20 次。满 20 次或没有更多内容时，再调用一次 `ask`，并在系统侧说明必须根据已读内容回答。`read_note` 用「已读过：表名，第几行到第几行」或「已读过：第几页到第几页」。上下文过长时，更早的读取结果替换成对应的 `read_note` 一行，保留最近一次原文。判定过长：已累积的读取文本超过 3 万字。

模型可见文本里不得出现 `object_key`、盘符、`http`。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_attachment_loop.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 9: 接到对话图

**Files:**
- Modify: `backend/oa_agent/runtime/graphs/oa_assistant.py`
- Modify: `backend/oa_agent/runtime/engine.py`（Task 5 已把 `attachment_ids` 放进输入）
- Test: `backend/tests/test_attachment_graph.py`

**Interfaces:**
- Consumes: `run_loop`，`extract_upload`，`read_owned` 所用的存储读取
- 图状态增加 `thread_files: list`，`remember` 不修改它
- 本轮 `attachment_ids` 只用于确认绑定已完成；目录以数据库里本会话 `in_message` 的上传为准

- [ ] **Step 1: 写失败测试**

用现有图测试的假模型。准备一个已绑定的 CSV「金额,1」。

1. 用户说「合计多少」。假模型第一次看到的人类消息含列名「金额」，并返回回答「合计是 1」。最终 `reply.content` 含「合计是 1」和读过范围（全文模式也要写「已读过」或「已阅读全文」）。
2. 同一线程下一句「查报销」。假模型返回 `{"action":"tool","steps":[{"tool":"<现有测试里的只读工具名>","args":{}}]}`。断言走到了原来的 `call_tool`，而不是把这句话当成文件回答。
3. 存储里的对象被换成别的字节。本轮失败，员工可见文案是「附件已损坏或无法读取，请重新上传」，且假模型的调用次数为 0。

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_attachment_graph.py -v`

Expected: FAIL

- [ ] **Step 3: 实现**

在 `understand` 开头：若本会话有已发送上传，先加载并 `extract_upload`。哈希失败把 `reply` 设为错误并让路由去 `respond`，不要调用模型。

有文件时，用 `run_loop` 的 `ask` 调用现有 `invoke_json`。系统提示写明三选一：`answer`、`read`、`tool`。`tool` 的 JSON 形状与现有 `steps` 相同。`LoopResult.kind == "delegate"` 时把 `steps` 填回现有状态，后面的 `_route` 不用改。`kind == "answer"` 时 `intent` 走现有聊天回复路径，`chat_reply` 为回答加上 `read_note`。

`mode == "full"` 时，把 `Projection.images` 作为 `image_url` 的 data URL 放进这一次模型调用的 human 内容。模型抛出含 image 的错误时，回复「当前模型无法查看图片」，不要去掉图片再调用。

`remember` 的返回值不要包含对 `thread_files` 的清空。把本会话文件摘要列表写入 `thread_files`，元素只有 `file_id`、`filename`、`media_kind`。

抽出的文本包在现有 `<<<UNTRUSTED_DATA` 围栏里，并走 `prepare_user_text` 或 `prompt_guard` 对工具结果使用的同一入口。

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_attachment_graph.py tests/test_chat_attachments.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 10: 管理端文件管理展示来源

**Files:**
- Modify: `frontend/src/admin/files.ts`
- Modify: `frontend/src/admin/views/FilesView.vue`
- Test: `frontend/src/admin/files.spec.ts`（若已有则追加；没有则新建）

**Interfaces:**
- `ExportFileItem` 增加 `origin: 'upload' | 'export' | null`，`media_kind: string | null`
- `listExportFiles` 增加可选参数 `origin`

- [ ] **Step 1: 写失败测试**

```ts
import { describe, expect, it } from 'vitest'

it('来源参数会传给列表', () => {
  const params = { origin: 'upload' as const, page: 1 }
  expect(params.origin).toBe('upload')
})
```

把断言改成对 `listExportFiles` 的请求参数。沿用 `files.ts` 现有测试对 `http.get` 的替身；如果还没有测试文件，就 mock `@/shared/http` 的 `get`，断言 URL 查询含 `origin=upload`。

- [ ] **Step 2: 运行确认失败**

Run: `npm run test -- src/admin/files.spec.ts`（在 `frontend/`）

Expected: FAIL

- [ ] **Step 3: 实现**

`FilesView.vue` 筛选区增加来源下拉：全部、用户上传、助手导出。表格增加一列「来源」，`upload` 显示「用户上传」，`export` 显示「助手导出」，空值显示现有的 `NO_DATA`。不要显示对象键。

- [ ] **Step 4: 测试通过**

Run: `npm run test -- src/admin/files.spec.ts`

Expected: PASS

浏览器里打开文件管理、切换来源并下载，交付说明里标为手工，本任务不把这次手工写成已通过。

- [ ] **Step 5: Commit**

仅当用户要求提交时提交。

---

### Task 11: 对话页上传、拖拽、粘贴

**Files:**
- Modify: `E:/python_project/oa-agent-chat/src/chat/api.ts`
- Modify: `E:/python_project/oa-agent-chat/src/chat/components/Composer.vue`
- Modify: `E:/python_project/oa-agent-chat/src/chat/App.vue`
- Test: `E:/python_project/oa-agent-chat/src/chat/components/composer-files.spec.ts`

**Interfaces:**
- `uploadAttachments(files: File[]) -> Promise<{file_id, filename, size_bytes, media_kind}[]>`
- `sendMessageStream(message, onDelta, signal, attachmentIds?: string[])`
- 请求体 `{ message, client_msg_id, attachment_ids }`

- [ ] **Step 1: 写失败测试**

用 vitest 测纯函数，不要起浏览器：

```ts
export function filesFromClipboard(data: DataTransfer | null): { images: File[]; text: string } {
  /* 实现放在 Composer 同目录 files-from-clipboard.ts，测试先写 */
}
```

用例：

1. clipboard item `image/png` 进入 `images`，`text` 为空。
2. 只有 `text/plain` 时 `images` 为空，`text` 为那段文字。
3. 两者都有时，图片和文字都保留。
4. `image/bmp` 被丢弃，不进入 `images`。

再测：`canSend` 在正文为空但附件个数大于 0 时为真。把这个判断从 `Composer.vue` 提成 `canSendMessage(text: string, attachmentCount: number, sending: boolean): boolean`。

- [ ] **Step 2: 运行确认失败**

Run: `npm run test -- src/chat/components/composer-files.spec.ts`（在 `oa-agent-chat/`）

Expected: FAIL

- [ ] **Step 3: 实现**

`files-from-clipboard.ts` 按上面的规则实现。`Composer.vue`：

- `input` 增加 `accept=".xlsx,.xls,.docx,.pdf,.md,.markdown,.csv,.png,.jpg,.jpeg,.webp,.gif"`。
- 对话区域的拖拽：在包裹输入区的根节点监听 `dragover` 与 `drop`，`preventDefault` 后把 `dataTransfer.files` 加入待发送列表。
- `paste`：调用 `filesFromClipboard`。有图片则阻止默认粘贴，把图片加入附件；有文字则插入到光标处。
- 本地仍可按扩展名提前拒绝，服务端拒绝时用返回的 `message` 提示，并保留输入框内容。
- 去掉「服务端上传未接入」的提示。

`App.vue` 的 `send`：有附件时先 `uploadAttachments`。失败则不调用 `sendMessageStream`，附件留在输入区。成功后把 `file_id` 数组传给 `sendMessageStream`，再清空本地附件。不要把文件字节放进消息 JSON。

`uploadAttachments` 使用 `FormData`，字段名 `files`，带现有 Bearer。不要设置 `Content-Type`，让浏览器写 multipart 边界。

- [ ] **Step 4: 测试通过**

Run: `npm run test -- src/chat/components/composer-files.spec.ts`

Expected: PASS

真实页面上的拖拽和粘贴在交付说明里标为手工。

- [ ] **Step 5: Commit**

仅当用户要求提交时，分别在两个仓库提交各自的文件。

---

### Task 12: 交付说明

**Files:**
- Create: `docs/delivery/2026-11-06-chat-attachment-delivery.md`

- [ ] **Step 1: 跑本计划涉及的自动化测试并记录真实结果**

```bash
cd backend && uv run pytest tests/test_upload_file_model.py tests/test_attachment_admit.py tests/test_attachment_store.py tests/test_chat_attachments.py tests/test_admin_export_files.py tests/test_attachment_extract.py tests/test_attachment_loop.py tests/test_attachment_graph.py -v
cd frontend && npm run test -- src/admin/files.spec.ts
cd ../oa-agent-chat && npm run test -- src/chat/components/composer-files.spec.ts
```

- [ ] **Step 2: 写交付说明**

按项目交付纪律写：功能、文件清单、迁移说明、API、权限与安全、测试结果、未完成项、下一步。测试结果分成自动化通过、手工、未执行、外部依赖未验证。OSS 真实上传若没做，写「外部依赖未验证」。不要写已做浏览器粘贴，除非这一步真的在浏览器里做过。

- [ ] **Step 3: Commit**

仅当用户要求提交时提交。

---

## Self-review 记录

- 规格里的粘贴、拖拽、配额、登记列、来源筛选、本人下载、哈希去重、全文/目录、20 次读取、加密与损坏、历史目录不受 `history_turns` 裁剪、管理端审计、对话页，分别落在 Task 2、3、4、5、6、8、9、10、11。
- 办公查询在有上传的会话里仍可用，对应规格第 5 节补充句，测试在 Task 9。
- 不实现删除、OCR、企微上传、欢迎页技能、视觉 token 估算。
