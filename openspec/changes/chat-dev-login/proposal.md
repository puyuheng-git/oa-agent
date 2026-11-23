## Why

本地/测试环境测员工对话页目前必须先登录 OA 宿主换 `launch_code`，开发摩擦大。需要在**管理后台显式开启**的前提下，用对话页开发入口（`?dev=1`）填 OA 号 + 开发口令，直接 mint 员工 token 并进入真会话，以便联调对话与 Tool。

## What Changes

- 管理后台「员工对话」新增 **开发登录** 配置：总开关（危险提示）、共享开发口令（secret）
- 新增 `POST /v1/chat/dev/session`：校验开关与口令 → 按 OA 号 mint → 签发与正式链路同等的 chat ticket（`channel=dev_login`）
- 新增只读探测（供前端判断是否展示开发条），例如 `GET /v1/chat/dev/status`：仅返回 `enabled`（不泄露口令）
- 每次开发换票写 audit（`chat.dev_login`），不含口令
- 对话前端（`oa-agent-chat`）：`?dev=1` 且后端 enabled 时，页顶开发条（OA、口令、进入/切换、当前身份）；切换身份 = 新 ticket + 新 thread + 清空 UI
- mint 失败硬失败，不发无 token 的假会话
- README：删除/更正未实现的 `?demo=1` 说明，改为 `?dev=1` 开发登录文档

## Capabilities

### New Capabilities

- `chat-dev-login`：开发态旁路 OA 宿主登录——后台开关与口令、dev session API、探测接口、审计标记、对话页开发条与换身份行为

### Modified Capabilities

- （无既有 openspec/specs 基线；本仓库首次引入该能力）

## Impact

- **oa-langGraph**：`config/schema.py`（员工对话组字段）、`chat/router.py`、`auth/chat_launch.py`（或旁路建会话）、admin settings UI、audit、测试
- **oa-agent-chat**：bootstrap / 顶栏开发条、换票清会话、`README.md`
- **依赖**：现有 office-api mint（`gateway_secret`、`mint_base_url`）；正式 `POST /v1/chat/launch` 不变
- **风险**：后台误开 + 口令泄露 ≈ 可冒充任意员工 mint；靠危险文案、口令 secret、审计与运维纪律缓解（对齐结论：不要 env 双开、不要 OA 白名单）
