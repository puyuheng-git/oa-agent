## Context

员工对话正式链路：OA 宿主登录 → HMAC assertion → `POST /v1/chat/launch`（mint office token）→ 一次性 `launch_code` → 对话壳 `POST /v1/chat/session` → Bearer ticket。本地测对话页必须先走 OA，成本高。

对话页仓库 `oa-agent-chat` 与 Agent `oa-langGraph` 本机经 Vite 代理联调。README 曾写 `?demo=1` Mock，代码未实现；本次不做 Mock，做真 mint 开发登录。

对齐结论（grill-me）：后台总开关即可（不要 env 双开）、对话页填 OA+共享口令、新 API `POST /v1/chat/dev/session`、`?dev=1`+probe 才显示顶栏、切换身份整页重登、mint 硬失败、`channel=dev_login`+audit。

## Goals / Non-Goals

**Goals:**

- 后台可开/关开发登录并配置共享口令
- 开发者用 `?dev=1` 在页顶换真 ticket（含 office token），可测对话与 Tool
- 与正式 launch 路径隔离；可审计

**Non-Goals:**

- 不实现 `?demo=1` 纯前端 Mock
- 不设 OA 白名单、不要 env 第二道闸
- 不改 OA 宿主页 / assertion 协议
- 不在无 mint 时发假会话

## Decisions

1. **配置落点**：`config/schema.py`「员工对话」组新增字段，例如：
   - `dev_login_enabled`（bool，默认 false，help 标明危险）
   - `dev_login_passphrase`（secret，只写不读惯例与 `gateway_secret` 一致）
   - 「可用」判定：`enabled && passphrase 非空`

2. **API**
   - `GET /v1/chat/dev/status` → `{ "enabled": bool }`（无鉴权，无密钥）
   - `POST /v1/chat/dev/session` body `{ "oa", "passphrase" }` → 与正式 session 开票响应同形（`ticket` / `expires_in` / `display_name` / `thread_id` / skills 等 extras）
   - 开关关或口令空 → 403 `DEV_LOGIN_DISABLED`（或统一 404，实现时二选一并写死测试）
   - 口令错 → 401 `DEV_LOGIN_INVALID`；用 `hmac.compare_digest` 比常量时间

3. **建会话**：复用 `OfficeApiClient.mint` + 现有 `ChatSession` / `store_session` / `pick_entry_thread`；**不**走 launch_code。强制 `channel="dev_login"`。`display_name`/`uid` 优先用 mint 返回，否则 `display_name=oa`。

4. **审计**：对齐 `chat.launch` 的「失败不阻断」或「口令失败也记」——规格要求校验到达后必记；实现用 `rt.audit.record`，action `chat.dev_login`，`meta`/`after` 含 `ok`、错误码，禁止口令字段。

5. **前端（oa-agent-chat）**
   - 启动时若 `dev=1`：先 `GET .../dev/status`；`enabled` 才渲染顶栏
   - 提交调 `POST .../dev/session`，写入与 `openSession` 相同的内存 ticket 路径
   - 切换身份：清消息状态、换 ticket、拉新 thread（等价重新 bootstrap）
   - 生产构建可保留该路径；可见性仍靠 query + probe

6. **文档**：`oa-agent-chat` README 去掉 `demo=1`，改为开发登录步骤；Agent `docs/ops/deployment.md` 可补一句本机联调可选路径

7. **测试**：`backend/tests` 扩夹具——开/关、口令错、mint mock 成功/失败、channel、audit；前端单测覆盖「无 dev / probe false 不展示」

**Alternatives considered:**

- 脚本代签 assertion：零新 API，但与「页内填 OA」不符
- env+后台双开：更安全，对齐时明确否决
- 注入静态 office token：分叉多，对齐要求走 mint

## Risks / Trade-offs

- [后台误开 + 口令泄露 → 任意 oa mint] → 危险文案、secret 字段、audit；运维勿把口令写入公开文档
- [probe 暴露「是否开启」] → 可接受；不泄露口令；无 `dev=1` 时 UI 不展示
- [生产包含开发 UI 代码] → 双条件门控；攻击面仍在 API，靠开关与口令
- [与正式 session 响应字段漂移] → 共用 `_session_extras` / 同一建会话辅助函数

## Migration Plan

1. 部署 Agent（新 settings + API）；默认 `dev_login_enabled=false`，行为与现网一致
2. 部署/联调 `oa-agent-chat`（开发条）
3. 测试环境：后台打开开关、设置口令，用 `http://127.0.0.1:5173/?dev=1` 验证
4. 回滚：关开关或回退版本；无 DDL

## Open Questions

- 开关关闭时用 **403** 还是 **404**（实现前在 tasks 里定死，推荐 403 + 稳定 error code）
- mint 返回的 `display_name` 为空时是否再调员工资料接口（推荐：不调，退回 `oa`）
