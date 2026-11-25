## ADDED Requirements

### Requirement: Model max input tokens configuration
The system SHALL store each LLM model's maximum input context size as `max_input_tokens` in `params_json`. When unset, the system MUST use a default of 100000 tokens. Administrators MUST be able to set this value in the LLM admin UI and API.

#### Scenario: Unconfigured model uses default
- **WHEN** a model has no `max_input_tokens` in `params_json`
- **THEN** input budget calculations MUST use 100000 tokens as `max_input_tokens`

#### Scenario: Admin sets max_input_tokens
- **WHEN** an admin saves a model with `max_input_tokens` = 128000
- **THEN** subsequent budget calculations for that model MUST use 128000

### Requirement: Input budget reserves output tokens
The system SHALL compute available input budget as `max_input_tokens` minus an output reserve of `max(configured max_tokens, 256)`.

#### Scenario: Reserve uses configured max_tokens
- **WHEN** a model has `max_input_tokens` = 10000 and `max_tokens` = 2000
- **THEN** available input budget MUST be 8000 tokens

### Requirement: No fixed entry hard caps for chat text
The system MUST NOT reject employee chat messages solely because they exceed a fixed admin setting like the former `message_max_chars` (500–2000). Entry validation MAY enforce only an abuse ceiling of approximately 100000 characters (or the character equivalent of the default model input budget, whichever policy is documented in design). Publish-config fields `assistant_persona` and `chat_instructions` MUST NOT be limited to 500/1000 characters respectively.

#### Scenario: Long employee message is accepted at the API
- **WHEN** an employee sends a message longer than 2000 characters but under the abuse ceiling
- **THEN** the API MUST NOT return a validation error for message length alone

### Requirement: Over-budget context is compressed
Before invoking the model, the system SHALL estimate prompt tokens with `chars ≈ tokens × 2`. If the prompt exceeds the available input budget, the system MUST compress context in this order: drop oldest history turns; further truncate history/memory using configured `history_message_chars` / `compress_truncate_chars` / `compress_memory_chars` rules; shrink observations; preserve the core system prompt when possible; truncate the current user message last. When the current user message is truncated, the system MUST indicate that context was compressed.

#### Scenario: History dropped before user truncation
- **WHEN** system + history + user message exceed the input budget and history is non-empty
- **THEN** the system MUST remove or shrink history before truncating the current user message

#### Scenario: User truncation is visible
- **WHEN** the current user message must be truncated to fit the budget
- **THEN** the content sent to the model or the employee-visible reply path MUST include a clear compressed/truncated indication

### Requirement: Capabilities expose effective message ceiling
The chat capabilities endpoint SHALL return `message_max_chars` as the effective entry ceiling (abuse floor / model-derived), not a separate small fixed setting.

#### Scenario: Frontend receives large ceiling
- **WHEN** the employee client loads capabilities
- **THEN** `message_max_chars` MUST be large enough to allow messages up to the abuse/model policy (not capped at 2000)
