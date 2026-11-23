## 1. Agent 配置

- [x] 1.1 在 `config/schema.py`「员工对话」组增加 `dev_login_enabled`（bool，默认 false，危险 help）与 `dev_login_passphrase`（secret）
- [x] 1.2 确认 admin 设置页自动渲染新字段（或补文案/危险样式若需手工）

## 2. Agent 开发登录 API

- [x] 2.1 实现「开发登录可用」判定：`dev_login_enabled` 且 passphrase 非空
- [x] 2.2 实现 `GET /v1/chat/dev/status` → `{ enabled }`，不返回密钥
- [x] 2.3 实现 `POST /v1/chat/dev/session`：口令常量时间校验 → mint → `ChatSession(channel=dev_login)` → ticket + `_session_extras`；关闭/空口令 → 403 `DEV_LOGIN_DISABLED`；口令错 → 401；mint 失败不发 ticket
- [x] 2.4 换票路径写 audit `chat.dev_login`（成功/口令失败均记；禁止记录 passphrase）
- [x] 2.5 抽取与正式 session 共用的开票/extras 辅助，避免字段漂移

## 3. Agent 测试

- [x] 3.1 单测：开关关 / 口令空 / 口令错 / mint 失败 / mint 成功（ticket 可用、channel、audit）
- [x] 3.2 单测：正式 `launch`→`session` 在开发开关关闭时仍通过

## 4. 对话前端（oa-agent-chat）

- [x] 4.1 增加 `devStatus` / `openDevSession` API 封装
- [x] 4.2 `?dev=1` 时探测 status；仅 `enabled` 时渲染页顶开发条（OA、口令、进入/切换、当前身份）
- [x] 4.3 提交成功后写入 ticket 并完成与正式 `openSession` 同等的 bootstrap；切换身份清空消息 UI + 新 thread
- [x] 4.4 前端单测：无 `dev` / probe false 不展示；成功换票与切换清会话

## 5. 文档与验收

- [x] 5.1 更新 `oa-agent-chat` README：删除/更正 `?demo=1`，写明 `?dev=1` + 后台开关/口令步骤
- [x] 5.2 可选：`oa-langGraph/docs/ops/deployment.md` 补本机开发登录一句
- [ ] 5.3 手工验收：后台开开关设口令 → `5173/?dev=1` 换票真聊；关开关 → UI 不可用且 API 403
- [x] 5.4 `openspec validate chat-dev-login` 通过
