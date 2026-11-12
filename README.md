# oa-agent

OA 智能助手 **Agent 编排服务**：员工在 OA / 企业微信中查询本人业务数据；LangGraph 负责意图与工具编排，业务数据只来自已配置的 HTTP 上游（如 office-api），**不直连 OA 业务库**。本仓库提供：

- Agent API（`/v1/chat/*`）与渠道（OA Web、企业微信）
- 管理后台与首次安装向导
- Tool / Skill / 流程配置 / 领域包（Pack）等能力

员工对话页是独立静态站点 `frontend/oa-agent`，本进程**不托管**对话 SPA

---

## 组件关系

| 组件                  | 说明                                                                            |
| ------------------- | ----------------------------------------------------------------------------- |
| 本仓库 Agent           | FastAPI + LangGraph，**单进程单 worker**；托管 `/admin/`、`/setup/`、`/v1/chat/`*       |
| `frontend/oa-agent` | 员工对话前端（页面 + `embed.js`），单独构建部署                                                |
| MySQL `agent_ops`   | 运营库（账号、审计、配置、运行、Tool/Skill 等）                                                 |
| Redis（建议）           | 后台会话、chat ticket、限流、幂等；未配置时用进程内存（重启丢失）                                        |
| `data/`             | `master.key`、`bootstrap.json`、`setup.token`、`checkpoints.sqlite`；**不入库，必须备份** |
| *-api / 业务上游        | 业务数据唯一来源；以员工本人 token 调用                                                       |

多实例前须先迁移进程内状态（取消标记、实时 Tool 注册表、SQLite Checkpointer 等），见设计文档。

---

## 环境要求

- Python ≥ 3.11，[uv](https://docs.astral.sh/uv/)
- Node.js 18+（构建本仓库管理后台；对话页在 `frontend/oa-agent`构建）
- MySQL 5.7+ / 8.0（utf8mb4）
- Redis 5+（生产建议）
- HTTPS 反向代理（后台 Cookie 默认 `Secure`）

---

## 快速启动（本机）

```powershell
# Windows
.\scripts\start.ps1 -BindHost 127.0.0.1 -Port 8765

# 强制重新构建管理后台前端
.\scripts\start.ps1 -BindHost 127.0.0.1 -Port 8765 -Build
```

```bash
# Linux / macOS
HOST=127.0.0.1 PORT=8765 scripts/start.sh
HOST=0.0.0.0 PORT=8765 scripts/start.sh --build
```

启动脚本会：`uv sync` → 必要时构建 `frontend` → 已安装则 `alembic upgrade head` → 单 worker 启动 uvicorn。

**首次安装：**

1. 打开 `http://127.0.0.1:8765/setup/`，安装令牌在 `data/setup.token`。
2. 填写 MySQL、创建超级管理员；向导写完 `bootstrap.json` 后自动退出安装模式。
3. **立即备份** `data/master.key`（丢失后密文密钥无法解密）。
4. 登录 `http://127.0.0.1:8765/admin/`，依次配置 Redis、LLM、OA/上游对接、Tool/Skill、账号权限。

纯 HTTP 内网调试可设 `export OA_AGENT_COOKIE_SECURE=false`（生产勿用）。

---

## 部署

### 1. 准备数据库

```sql
CREATE DATABASE agent_ops DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'agent_ops'@'%' IDENTIFIED BY '<强密码>';
GRANT ALL PRIVILEGES ON agent_ops.* TO 'agent_ops'@'%';
```

### 2. 启动 Agent

生产建议绑定内网并由 Nginx 反代：

```powershell
.\scripts\start.ps1 -BindHost 0.0.0.0 -Port 8765
```

Nginx 示例（Agent 管理后台）：

```nginx
server {
    listen 443 ssl http2;
    server_name agent.example.com;
    client_max_body_size 25m;   # 含对话附件上传（单文件最大 20MB）
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

不要覆盖 Agent 返回的 `Content-Security-Policy` / `X-Frame-Options`（管理后台禁止被嵌入）。

### 3. 部署员工对话站（`frontend/oa-agent`）

推荐与 API **同域名**：静态页直接返回，`/v1/` 反代到 Agent（相对路径、无需 CORS）。

```bash
# 在 oa-agent-chat 仓库
npm ci
# VITE_API_BASE_URL 留空 → 浏览器请求 /v1/*，由 Nginx 转到 Agent
npm run build
# 将 dist/ 放到静态目录，例如 /var/www/oa-agent-chat
```

```nginx
server {
    listen 443 ssl http2;
    server_name chat.example.com;
    root /var/www/oa-agent-chat;
    index index.html;

    # 按实际 OA 域名填写；能否被 iframe 嵌入只看这里
    add_header Content-Security-Policy "frame-ancestors 'self' https://oa.example.com" always;

    location /v1/ {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;       # SSE：/v1/chat/messages/stream
        proxy_read_timeout 120s;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

若对话站与 Agent **不同源**，在 Agent 进程设置：

```bash
CHAT_CORS_ORIGINS=https://chat.example.com
```

并在管理后台「OA 对接」填写 `chat_ui_base_url`（员工对话页基址）。

### 4. 环境变量（仅启动参数；业务配置走管理后台）

| 变量 | 默认 | 说明 |
|------|------|------|
| `OA_AGENT_DATA_DIR` | `<仓库>/data` | data 目录 |
| `OA_AGENT_FRONTEND_DIST` | `<仓库>/frontend/dist` | 管理后台构建产物 |
| `OA_AGENT_MASTER_KEY` | 空 | base64 的 32 字节主密钥，覆盖 `data/master.key` |
| `OA_AGENT_COOKIE_SECURE` | `true` | 后台 Cookie Secure |
| `OA_AGENT_TENANT_ID` | `dscpa` | 租户标识 |
| `CHAT_CORS_ORIGINS` | 空 | 逗号分隔的对话站 Origin；仅作用于 `/v1/chat/*` |
| `OA_AGENT_ALLOW_SQLITE` | `false` | 仅测试；生产禁止 |

### 5. 系统服务 / 升级 / 备份

- Linux：systemd 示例与备份策略见 [部署与运维手册](docs/ops/deployment.md) §7–§10。
- 升级：备份 `agent_ops` 与 `data/` → 替换代码（保留 `data/`）→ `-Build` / `--build` 启动（自动迁移）→ 检查 `/readyz`。
- 健康检查：`GET /healthz`、`GET /readyz`。

---

## 本地开发

### Agent（本仓库）

```powershell
# 启动（含依赖同步 / 迁移）
.\scripts\start.ps1 -BindHost 127.0.0.1 -Port 8765

# 或手动
cd backend
$env:OA_AGENT_DATA_DIR = '..\data'
uv sync
uv run alembic upgrade head   # 已安装时
uv run uvicorn oa_agent.main:app --host 127.0.0.1 --port 8765 --workers 1 --proxy-headers
```

管理后台前端热更新：

```powershell
cd frontend
npm ci
npm run dev
```

测试与构建：

```powershell
cd backend;  uv run pytest -p no:cacheprovider -q --basetemp=.pytest_tmp
cd frontend; npm test; npm run build
```

### 与对话页联调（本机）

| 进程 | 地址 | 作用 |
|------|------|------|
| Agent | `http://127.0.0.1:8765` | `/v1/chat/*`、`/admin/` |
| 对话页 | `http://127.0.0.1:5173` | Vite；`/v1`、`/healthz` 代理到 8765 |

```powershell
# 1. 本仓库
.\scripts\start.ps1 -BindHost 127.0.0.1 -Port 8765

# 2. oa-agent-chat：.env.local 中 VITE_API_BASE_URL 必须留空
npm run dev
```

**注意：** `VITE_API_BASE_URL` 若写成 `http://127.0.0.1:8765`，浏览器会跨域直连；默认未开 CORS 时会出现「暂时无法连接」。留空走同源相对路径 + Vite 代理即可。

接通标志：`http://127.0.0.1:5173/healthz` 经代理返回与 Agent 相同的健康结果；带 `?launch=` 打开对话页后能成功 `POST /v1/chat/session`。

---

## 对话页端交互对接

员工身份**只认 OA 服务端签发的断言**；模型或前端自报的 `oa` 一律丢弃。Token 只存在 Agent 服务端，不下发浏览器。

### OA 宿主页流程

1. OA 服务端构造断言 `{oa, uid, display_name, exp(≤60s), nonce, iss:"oa-host", aud:"oa-langgraph"}`，base64url + HMAC-SHA256 → `<body>.<hex>`。
2. 服务端 `POST {Agent}/v1/chat/launch`，body `{"assertion":"..."}` → `launch_code`（约 60 秒、一次性）。
3. 浏览器打开对话站：`https://chat.example.com/?launch={launch_code}`；嵌入场景加 `&embed=1`。
4. 对话页 `POST /v1/chat/session` 兑换 `ticket`，之后请求带 `Authorization: Bearer <ticket>`。

字段与 PHP 参考见 [`docs/design/2026-10-09-oa-service-side-design.md`](docs/design/2026-10-09-oa-service-side-design.md)。

### 核心 API（对话页调用）

除 `POST /launch` 外，均需 `Authorization: Bearer <ticket>`。

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/v1/chat/launch` | OA 服务端：assertion → launch_code |
| `POST` | `/v1/chat/session` | launch_code → ticket、skills、workflows 等 |
| `GET` | `/v1/chat/session` | 当前会话信息 |
| `POST` | `/v1/chat/session/refresh` | 续期 |
| `GET/POST/PATCH/DELETE` | `/v1/chat/threads…` | 历史会话 |
| `POST` | `/v1/chat/session/switch` | 切换 thread |
| `POST` | `/v1/chat/messages` | 同步发消息（`message`、`client_msg_id`、可选 `attachment_ids`） |
| `POST` | `/v1/chat/messages/stream` | SSE：`delta` 增量、`done` 完整结果；空闲心跳注释行 |
| `POST` | `/v1/chat/attachments` | multipart 字段 `files`；先上传再发消息 |
| `GET` | `/v1/chat/files/{file_id}` | 本人下载已发送附件 |
| `GET` | `/v1/chat/runs/{run_id}` | 转人工后轮询结果 |
| `GET/DELETE` | `/v1/chat/memory…` | 长期记忆 |
| `POST` | `/v1/chat/confirmations/{task_id}` | 员工确认写操作 |
| `GET/POST` | `/v1/chat/workflows…` | 固定 Workflow 目录与启动 |

附件约束（摘要）：单次最多 5 个、单文件 ≤20MB；类型含 xlsx/xls/docx/pdf/md/csv 与常见图片；可仅附件无正文发送。

### 企业微信

管理后台填写 BotID / Secret 后长连接；OA 签发入口需支持按 `wework_user_id` mint。仅单聊；同一 Bot 只能有一个 Agent 实例连接。详见 [使用说明 §4.2](docs/ops/user-guide.md#42-企业微信智能机器人长连接)。

---

## 系统操作（管理后台）

入口：`https://<Agent 域名>/admin/`。

| 菜单 | 用途 |
|------|------|
| 运行总览 / 运行记录 | 成功率、时间线、取消与重试 |
| 对话记录 | 完整对话与模型调用原文；可导出 JSONL |
| 介入中心 | 上游故障「转人工」时的恢复 / 终止 |
| Tool / Skill 管理 | 注册只读查询能力、启停、版本、从 OpenAPI/Apipost 导入 |
| 领域包 | 启停本机 `packs/` |
| 流程配置 | 意图方式、默认条数、上游故障策略等；草稿 → 校验 → 发布 / 回滚 |
| 连接配置 | Redis、OA/上游、企业微信、运行参数、IdP |
| LLM 配置 | 提供方与模型 |
| 文件管理 | 导出与已发送上传 |
| 账号 / 角色 / 审计 | RBAC 与写操作审计 |

安装后建议顺序：Redis → LLM → OA/上游 → 确认 Tool/Skill → 流程发布 → 账号权限。更细操作与权限点见 [使用说明](docs/ops/user-guide.md)。

接入新的 HTTP JSON 业务系统见 [新系统接入手册](docs/ops/integrate-external-system.md)。

---

## 项目目录结构

```
oa-langGraph/
├── backend/                 # Agent 服务
│   ├── oa_agent/
│   │   ├── main.py          # FastAPI 入口、静态挂载、CORS
│   │   ├── admin/           # 管理 API
│   │   ├── auth/            # 后台会话、chat launch、RBAC
│   │   ├── bootstrap/       # 安装向导
│   │   ├── channels/        # 企业微信等
│   │   ├── chat/            # /v1/chat/*、附件、记忆、会话线程
│   │   ├── config/          # 配置 schema、密钥保管
│   │   ├── connectors/      # HTTP 上游与响应信封
│   │   ├── db/              # SQLAlchemy 模型
│   │   ├── executor/        # Tool 执行、导出、Builtin/MCP
│   │   ├── identity/        # IdP（OA assertion / 企微 / demo）
│   │   ├── integrations/    # *-api、LLM 探测
│   │   ├── observability/   # 审计、事件、对话落库
│   │   ├── packs/           # 领域包加载
│   │   ├── runtime/         # LangGraph 引擎、介入、发布配置
│   │   └── security/        # 提示词防护等
│   ├── migrations/          # Alembic
│   ├── tests/
│   └── pyproject.toml
├── frontend/                # 管理后台 + 安装向导（Vue）
│   ├── src/admin/
│   ├── src/setup/
│   └── public/              # 构建期静态资源（对话页已外置）
├── packs/                   # 领域包（如 oa_travel、demo_http）
├── openapi/                 # Tool 契约 YAML（表空时导入）
├── skills/                  # Skill YAML（表空时导入）
├── contracts/               # 写类等契约
├── scripts/                 # start.ps1 / start.sh
├── data/                    # 运行时密钥与检查点（勿提交）
└── docs/
    ├── design/              # 权威设计
    ├── ops/                 # 部署、使用、接入
    ├── delivery/            # 阶段交付说明
    └── STATUS.md            # 完成度看板
```

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [部署与运维手册](docs/ops/deployment.md) | 安装、反代、对话站、备份、排障 |
| [使用说明](docs/ops/user-guide.md) | 后台操作、OA/企微对接、角色权限 |
| [新系统接入手册](docs/ops/integrate-external-system.md) | 上游、Tool/Skill、Pack、IdP |
| [设计文档](docs/design/2026-10-09-oa-langgraph-design.md) | 权威架构与硬约束 |
| [OA / Service 侧设计](docs/design/2026-10-09-oa-service-side-design.md) | 断言、mint、企微身份 |
| [文档目录](docs/README.md) | 全量索引 |
| [完成度看板](docs/STATUS.md) | 交付状态与后续扩展 |

`docs/history/`、`docs/reference/` 仅供追溯，冲突时以 `docs/design/` 为准。
