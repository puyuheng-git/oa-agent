# 部署与运维手册

本文面向运维人员，覆盖安装、配置、升级、备份、监控与排障。管理员日常操作见 [使用说明](user-guide.md)。

## 1. 组件与硬约束

| 组件 | 说明 |
|------|------|
| Agent 进程 | FastAPI + LangGraph，单进程**单 worker**；同时托管管理后台、员工对话页与安装向导的静态页面 |
| MySQL `agent_ops` | 运营库：账号/角色/审计/配置/运行与事件/介入任务/Tool·Skill·Workflow 版本。**不访问 OA 业务库 `td_oa`** |
| Redis（建议） | 后台会话、员工 chat ticket、office token、限流、幂等键。未配置时用进程内存兜底（重启即丢会话） |
| `data/` 目录 | `master.key`（主密钥）、`bootstrap.json`（数据库连接，密码已加密）、`setup.token`（一次性安装令牌）、`checkpoints.sqlite`（LangGraph 检查点）。**不入库、必须备份** |
| office-api | 业务数据唯一来源，以员工本人 token 调用；Agent 只走 HTTP 契约 |

必须单 worker 的原因：运行取消标记、实时 Tool 注册表、事件写入队列、SQLite Checkpointer 都在进程内。多实例部署前需要先迁移这些组件（设计 §15）。

## 2. 环境要求

- Python ≥ 3.11（开发验证用 3.13），[uv](https://docs.astral.sh/uv/)
- Node.js 18+（仅构建前端时需要；也可在其他机器构建后拷贝 `frontend/dist`）
- MySQL 5.7+/8.0，字符集 utf8mb4
- Redis 5+（可选但生产建议）
- HTTPS 反向代理（Nginx 等）：后台 Cookie 带 `Secure`；OA iframe 嵌入要求两端都是 HTTPS

## 3. 准备 MySQL

```sql
CREATE DATABASE agent_ops DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'agent_ops'@'%' IDENTIFIED BY '<强密码>';
-- 迁移需要建表/改表权限
GRANT ALL PRIVILEGES ON agent_ops.* TO 'agent_ops'@'%';
```

## 4. 首次安装

```powershell
# Windows
.\scripts\start.ps1 -BindHost 0.0.0.0 -Port 8765
```

```bash
# Linux
HOST=0.0.0.0 PORT=8765 scripts/start.sh
```

启动脚本依次执行：`uv sync` → 前端未构建则 `npm ci && npm run build` → 已安装则 `alembic upgrade head` → 以单 worker 启动 uvicorn。

首次启动处于**安装模式**（除 `/setup` 外所有接口返回 503）：

1. 日志和 `data/setup.token` 中有一次性安装令牌；启动日志同时提示**立即备份 `data/master.key`**。
2. 浏览器打开 `https://<域名>/setup/`，输入令牌 → 填 MySQL 并“测试连接” → 创建超级管理员（强密码）。
3. 向导执行数据库迁移、写入 `bootstrap.json`、删除 `setup.token`，随即退出安装模式，无需重启。

安装后 `/setup` 永久关闭。需要重装时：停服务 → 删除 `data/bootstrap.json` → 重新启动（数据库中已有数据不会被删除）。

## 5. 安装后的配置顺序

用超级管理员登录 `https://<域名>/admin/`，依次完成：

1. **连接配置 → Redis**：填写地址/DB/密码，“测试连接”通过后热切换；内存中的会话会迁移过去。
2. **LLM 配置**：新增提供方（OpenAI 兼容协议，填 base_url 与 API Key）→ 新增模型（建议打上 `intent` 用途标签）→ 测试。未配置 LLM 时意图解析自动走规则，不影响查询功能。
3. **连接配置 → OA 对接**：office-api 地址、`AGENT_GATEWAY_SECRET`（mint 用）、OA assertion HMAC 密钥、允许嵌入的 OA 域名（写入 `frame-ancestors`）、office-api 成功码。
4. **连接配置 → 运行参数**（可保持默认）：运行超时 60 秒、疑似卡住阈值 30 秒、事件保留 180 天、每员工每分钟 30 条、介入任务有效期 30 分钟。
5. **Tool 管理 / Skill 管理**：确认两条行程 Tool 已注册、Skill “行程报销查询”校验通过（首次启动已自动同步）。
6. **流程配置**：按需调整（如把“上游故障处理”改为“转人工介入”），走草稿 → 校验 → 发布。
7. **账号 / 角色与权限**：为运维、值班人员建账号，按最小权限分配（见使用说明 §6）。

所有密钥只写不读，页面只显示 `已设置 · ****abcd`；修改需重新输入完整值。

## 6. 反向代理示例（Nginx）

```nginx
server {
    listen 443 ssl http2;
    server_name agent.example.com;
    # ssl_certificate ... ;

    client_max_body_size 1m;
    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;   # 大于运行超时（默认 60s）
    }
}
```

不要在代理层覆盖 Agent 返回的 `Content-Security-Policy` / `X-Frame-Options`：员工对话页按“允许嵌入的 OA 域名”输出 `frame-ancestors`，其余页面禁止被嵌入。

## 7. 作为系统服务运行

Linux（systemd）：

```ini
# /etc/systemd/system/oa-agent.service
[Unit]
Description=OA LangGraph Agent
After=network.target

[Service]
WorkingDirectory=/opt/oa-langGraph
Environment=OA_AGENT_DATA_DIR=/opt/oa-langGraph/data
ExecStart=/opt/oa-langGraph/scripts/start.sh
Restart=on-failure
User=oaagent

[Install]
WantedBy=multi-user.target
```

Windows：可用 NSSM 把 `powershell -ExecutionPolicy Bypass -File E:\...\scripts\start.ps1` 注册为服务。

进程异常退出后重启时，Agent 会把上次停在“执行中”的运行标记为 `failed(RUNTIME_INTERRUPTED)`，把“已请求取消”的运行标记为 `cancelled`；等待人工的运行保持原状，可继续在介入中心处理。

## 8. 环境变量

只有启动参数用环境变量，业务配置一律在管理后台。

| 变量 | 默认 | 说明 |
|------|------|------|
| `OA_AGENT_DATA_DIR` | `<仓库>/data` | data 目录位置 |
| `OA_AGENT_FRONTEND_DIST` | `<仓库>/frontend/dist` | 前端构建产物目录 |
| `OA_AGENT_MASTER_KEY` | 空 | base64 编码的 32 字节主密钥；设置后覆盖 `data/master.key`（适合放进密钥管理系统） |
| `OA_AGENT_COOKIE_SECURE` | `true` | 后台 Cookie 带 Secure。未走 HTTPS 的内网环境需设 `false`（不推荐） |
| `OA_AGENT_TENANT_ID` | `dscpa` | 租户标识 |
| `OA_AGENT_ALLOW_SQLITE` | `false` | 仅自动化测试使用：允许 SQLite 代替 MySQL。**生产禁止** |

## 9. 升级

1. 备份（见 §10），尤其是 MySQL `agent_ops` 与 `data/`。
2. 停止服务，替换代码（保留 `data/`）。
3. 启动脚本加 `-Build`（Linux：`--build`）重新构建前端；脚本会自动 `alembic upgrade head`。
4. 访问 `/readyz`，确认 `database.migration.up_to_date = true`。

不经启动脚本、直接 `uv run uvicorn oa_agent.main:app` 启动时，Agent 也会在启动时检测并自动补跑迁移（日志：“数据库迁移版本落后，自动执行迁移”）。如果数据库账号没有建表权限导致失败，日志会给出一条明确错误，此时手动执行 `cd backend && uv run alembic upgrade head` 后重启。

当前迁移链：`0001_p0_init → 0002_p1_run_event → 0003_p2_run_failed_node → 0004_p3_intervention → 0005_p4_tool_skill → 0006_p5_config_release → 0007_conversation_log`。迁移同时兼容 MySQL 与 SQLite，只新增表和列，不改写已有数据。

**升级到“后台可配置 Tool/Skill”版本（2026-10-10）的注意事项：**

- 无新迁移；Tool/Skill 仍存在 `agent_tool*` / `agent_skill*` 表。仓库 `openapi/`、`skills/` 下的 YAML 只在表为空时导入，已有部署的数据保持不变。需要新的显示名称、示例问题时，在后台 Tool 管理、Skill 管理各点一次“从文件导入”。
- 流程版本号从 `1` 变为 `2`：升级前处于“等待人工”的运行不能再恢复（介入中心会显示“流程版本不一致”），只能终止，员工重新提问即可。建议在没有待处理介入任务时升级。
- 后台新增的 Tool 需要配置 LLM 才能被选中；只有内置行程报销查询有无模型时的规则兜底。

## 10. 备份与恢复

| 对象 | 频率 | 说明 |
|------|------|------|
| `data/master.key` | 安装后立即、异地保存 | **丢失后所有密钥（LLM Key、OA 密钥、Redis 密码、数据库密码）都无法解密，只能重新录入**；也可改用 `OA_AGENT_MASTER_KEY` |
| `data/bootstrap.json` | 变更数据库连接后 | 丢失需重新走安装向导 |
| MySQL `agent_ops` | 每日 | `mysqldump --single-transaction agent_ops` |
| MySQL `agent_conversation_message` / `agent_model_call_log` | 随 `agent_ops` 每日备份 | 完整对话原文（含个人信息），训练数据来源；不自动清理，注意磁盘与访问控制 |
| `data/checkpoints.sqlite` | 每日（可选） | 只影响“等待人工”运行能否恢复；丢失后介入中心会如实显示“检查点缺失，不可恢复” |

恢复：停服务 → 放回 `data/` 与数据库 → 启动。master key 必须与 `bootstrap.json`、数据库中的密钥密文配套。

## 11. 健康检查与监控

- `GET /healthz`：进程存活，返回 `{"status":"ok","mode":"normal|setup"}`。
- `GET /readyz`：就绪检查，数据库不可用或未安装时返回 503。字段：
  - `database`：状态与迁移版本（`migration_pending` 表示需执行迁移）
  - `redis`：当前使用 Redis 还是内存兜底
  - `llm`：只报告“已配置（未检测）/未配置”，不伪造健康状态
  - `observability`：事件写入队列状态（积压、丢弃数）
  - `agent`：已注册 Tool、Skill 可用性、当前生效的流程发布版本
- 后台“运行总览”提供成功率、P95、错误 Top、疑似卡住数量；无数据时显示“暂无数据”。

后台巡检（每 30 秒）：运行超时 → `timed_out`；介入任务过期 → 运行 `failed(INTERVENTION_EXPIRED)`；每小时按保留天数清理过期事件。运行超时按“本段执行”计时，等待人工的时间不计入。

## 12. 日志

- uvicorn 标准输出/错误输出即应用日志（由 systemd / NSSM 收集）。
- 日志、审计、异常信息都经过脱敏处理，不含明文密钥、token、assertion。
- 审计日志在后台“审计日志”页查询；审计写入失败时对应管理操作整体失败。

## 13. 故障排查

| 现象 | 排查 |
|------|------|
| 所有接口 503 “系统未安装” | `data/bootstrap.json` 不存在；按 §4 安装，或检查 `OA_AGENT_DATA_DIR` 是否指向正确目录 |
| 后台登录后立刻掉线 | HTTP 访问但 `OA_AGENT_COOKIE_SECURE=true`；应走 HTTPS 反代；确实只能 HTTP 时设 `OA_AGENT_COOKIE_SECURE=false` |
| OA 页面里助手空白 / 拒绝嵌入 | “允许嵌入的 OA 域名”未包含 OA 的协议+域名；两端需同为 HTTPS |
| 员工进入提示 launch 失败 | HMAC 密钥与 OA 不一致、assertion 过期（≤60s）或 nonce 重放；看 Agent 日志中的错误码 |
| 员工查询提示“业务系统暂时不可用” | office-api 地址或网络问题；运行详情的失败节点与错误码可定位（UPSTREAM_TIMEOUT / UNAVAILABLE / HTTP_ERROR） |
| 提示“该功能暂未开放” | Skill 被停用或依赖 Tool 未注册；看 Tool 管理页“未注册”原因 |
| `/readyz` 中 `migration_pending` | 执行 `cd backend && uv run alembic upgrade head`（启动脚本会自动执行） |
| 介入任务“不可恢复” | 页面列出具体原因：员工会话过期、运行已被新消息取代、流程版本不一致、检查点缺失等；此时只能终止 |
| 迁移报权限错误 | 数据库账号缺 CREATE/ALTER 权限 |
| 主密钥丢失 | 无法找回；删除 `bootstrap.json` 重装，并在后台重新录入所有密钥 |
