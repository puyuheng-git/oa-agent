## Context

入口层用固定字数限制员工消息与发布配置文本；模型侧只有 `max_tokens`（输出），无上下文窗口字段。对话图在 `_history_messages` / `memory.compress` 已有压缩旋钮，但不会按模型窗口做总预算。

## Goals / Non-Goals

**Goals:**
- 以 `params_json.max_input_tokens`（默认 100k）为硬顶
- 入口取消固定硬顶；超窗按既有压缩规则收上下文
- 管理端可配置 max_input_tokens；能力接口下发可用消息上限

**Non-Goals:**
- tiktoken / 实时前端预算条
- 企微体积、业务 hint/remark 截断
- 新 DB 列

## Decisions

1. **预算模块** `runtime/context_budget.py`：估算、预算、`fit_messages` 压缩。
2. **换算** `chars ≈ tokens × 2`；可用输入 = `max_input_tokens - max(max_tokens, 256)`。
3. **压缩优先级**：丢最旧历史 → 按 `compress_truncate_chars` / `history_message_chars` 再缩历史与记忆注入 → 缩 observation → 系统提示主体尽量保留 → 最后截本条 human 并加截断说明。
4. **入口**：删除 `chat.message_max_chars`；`SendMessage.message` 用大上限（如与兜底一致的字符上限）；`guard_message` 仅拦「空」与兜底滥用上限（100k 字符）或按当前默认模型预算换算的字符上限取较小者。
5. **发布文本**：`assistant_persona` / `chat_instructions` 去掉小 max（或提到与预算同量级）；Skill instructions 同步放开。
6. **保留** history/memory 配置项作为压缩参数，不再当入口拒绝条件。
7. **双仓**：Agent 能力字段仍返回 `message_max_chars`（语义改为「当前可用上限」）；chat 壳用该值作软 maxlength，不再假设 500。

## Risks / Trade-offs

- [估算偏差] → 预留输出 token；默认 100k 偏保守于常见长上下文模型时可再配
- [超长系统提示本身超窗] → 最后仍可能截 human；极端情况截 system 尾部并标记 compressed
- [删配置项] → 旧 `message_max_chars` 忽略；测试改写

## Migration Plan

1. 部署代码；管理员按需填 `max_input_tokens`
2. 回滚：恢复旧入口校验即可；无 schema 迁移

## Open Questions

无（grill-me 已关闭）
