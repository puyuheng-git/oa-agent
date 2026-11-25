## 1. Budget core

- [x] 1.1 Add `runtime/context_budget.py` (estimate, default 100k, output reserve, fit_messages)
- [x] 1.2 Unit tests for budget math and compression priority

## 2. LLM admin

- [x] 2.1 Extend `ModelIn` / `_model_view` / save path for `max_input_tokens`
- [x] 2.2 Update `LlmView.vue` form + table column

## 3. Remove entry hard caps

- [x] 3.1 Remove `chat.message_max_chars` from `config/schema.py`
- [x] 3.2 Raise/remove Pydantic max on chat message; update `guard_message` + capabilities
- [x] 3.3 Raise `assistant_persona` / `chat_instructions` max in `releases.py`; Skill instructions max
- [x] 3.4 Update oa-agent-chat Composer/App for new ceiling semantics

## 4. Wire graph invoke path

- [x] 4.1 Apply `fit_messages` before model calls in `oa_assistant.py` understand path
- [x] 4.2 Surface compression notice when user text truncated

## 5. Tests & verify

- [x] 5.1 Rewrite tests that depended on `message_max_chars`
- [x] 5.2 Run targeted pytest for chat/llm/budget
