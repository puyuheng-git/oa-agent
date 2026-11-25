## Why

员工单条消息与系统提示（角色设定、回答补充要求等）被固定字数上限卡住（如 500/2000、persona 500、instructions 1000），无法吃满模型上下文窗口。需要改为以模型最大输入为准，超限时按既有压缩规则收上下文，而不是入口直接拒绝。

## What Changes

- 取消入口层固定字数硬顶：`message_max_chars` 配置与接口 2000 上限；放开 `assistant_persona` / `chat_instructions` 等文本 max；Skill `instructions` 等同理。
- 模型 `params_json` 增加 `max_input_tokens`（管理端可填）；未配置默认 **100k tokens**。
- 调用模型前按「可用输入 = max_input_tokens − 输出预留」做预算；超限按配置压缩（先历史/记忆 → observation → 尽量不动系统提示 → 最后截本条用户输入并提示）。
- Token 估算：`chars ≈ tokens × 2`，不引入 tiktoken。
- 无模型 / help 路径：兜底约 100k 字符防滥用。
- 员工端去掉硬 maxlength 红字拦截（可仍用能力接口下发的大上限）；一期不做实时 Token 条。
- **保留** `history_compress*`、`history_message_chars` 等作为压缩规则。
- Non-goals：精确 tokenizer、企微 20KB、业务 hint/remark 截断、新 DB 列。

## Capabilities

### New Capabilities

- `model-context-budget`: 以模型 max_input_tokens 为硬顶的输入预算、估算与超限压缩行为

### Modified Capabilities

- （无既有 openspec/specs；行为变更记入上述新 capability）

## Impact

- **oa-langGraph**：`config/schema.py`、`chat/router.py`、`chat/service.py`、`runtime/releases.py`、`runtime/graphs/oa_assistant.py`、新建 `runtime/context_budget.py`、`admin/llm_api.py`、`frontend` LlmView、相关测试
- **oa-agent-chat**：`Composer.vue` / `App.vue` 对 `message_max_chars` 的用法
- 管理员需按模型手册填写 `max_input_tokens`；旧环境未填则用 100k 默认
