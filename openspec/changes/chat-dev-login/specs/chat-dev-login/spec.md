## ADDED Requirements

### Requirement: Admin can enable chat development login

The system SHALL expose configuration under the existing「员工对话」settings group for development login: a boolean master switch (with a danger-oriented help text) and a shared development passphrase stored as a secret field (write-only readback consistent with other secrets). When the master switch is off, all development-login chat APIs MUST refuse the request.

#### Scenario: Switch off rejects session

- **WHEN** an client calls `POST /v1/chat/dev/session` while the master switch is disabled
- **THEN** the system responds with 403 (or 404) and does not mint or issue a ticket

#### Scenario: Switch on with empty passphrase rejects session

- **WHEN** the master switch is enabled but the configured passphrase is empty
- **THEN** `POST /v1/chat/dev/session` is rejected and no ticket is issued

### Requirement: Development status probe without leaking secrets

The system SHALL provide an unauthenticated read-only probe (e.g. `GET /v1/chat/dev/status`) that returns whether development login is currently usable (`enabled: true` only when the master switch is on and a non-empty passphrase is configured). The response MUST NOT include the passphrase or any office token.

#### Scenario: Probe when usable

- **WHEN** the master switch is on and a passphrase is configured
- **THEN** the probe returns `enabled: true` and no secret fields

#### Scenario: Probe when not usable

- **WHEN** the master switch is off or the passphrase is empty
- **THEN** the probe returns `enabled: false`

### Requirement: Dev session mints office token and issues chat ticket

When development login is usable, `POST /v1/chat/dev/session` MUST accept `oa` and `passphrase`, verify the passphrase with a constant-time compare against the configured secret, mint an employee Authorization via the existing office mint path for that `oa`, and issue a chat ticket/session equivalent to a successful formal redeem (including `display_name` / `uid` from mint when available). The session `channel` MUST be `dev_login`. Mint failure MUST hard-fail with a clear error and MUST NOT issue a ticket without an office token.

#### Scenario: Successful exchange

- **WHEN** development login is usable, the passphrase matches, and mint succeeds for the given `oa`
- **THEN** the response includes `ticket`, `expires_in`, `display_name`, `thread_id`, and the session is usable with `Authorization: Bearer <ticket>` for subsequent `/v1/chat/*` calls

#### Scenario: Wrong passphrase

- **WHEN** the passphrase does not match
- **THEN** the system rejects the request without minting and without issuing a ticket

#### Scenario: Mint failure

- **WHEN** the passphrase is correct but office mint fails or returns an unusable token
- **THEN** the system returns an error describing mint failure and does not issue a ticket

### Requirement: Development login is audited

Each successful or failed `POST /v1/chat/dev/session` attempt that reaches passphrase verification MUST record an audit entry (action such as `chat.dev_login`) including the target `oa` and outcome. The audit payload MUST NOT store the passphrase.

#### Scenario: Successful login audited

- **WHEN** a development session is issued successfully
- **THEN** an audit record exists with actor/resource identifying the `oa` and success outcome, without the passphrase

#### Scenario: Failed passphrase audited

- **WHEN** a development session is rejected for wrong passphrase
- **THEN** an audit record exists with failure outcome and does not store the passphrase

### Requirement: Chat UI shows development bar only when allowed

The employee chat frontend SHALL show the development login bar only when the URL contains `dev=1` (or equivalent query) **and** the status probe reports `enabled: true`. The bar MUST include fields for OA account, development passphrase, an enter/switch action, and the current identity (`oa` / `display_name`) after a successful exchange. The production build MAY include this code path; visibility MUST still obey the two conditions above.

#### Scenario: Hidden without query

- **WHEN** a user opens the chat page without `dev=1` even if the probe is enabled
- **THEN** the development bar is not shown

#### Scenario: Hidden when backend disabled

- **WHEN** a user opens the chat page with `dev=1` but the probe returns `enabled: false`
- **THEN** the development bar is not shown (or shows a non-interactive unavailable state without a working submit)

#### Scenario: Shown when both conditions met

- **WHEN** the page has `dev=1` and the probe returns `enabled: true`
- **THEN** the development bar is visible at the top of the chat shell

### Requirement: Switching identity resets the chat shell

Submitting a new OA (or re-entering) via the development bar MUST replace the in-memory ticket, obtain a new default thread for the new identity, and clear the visible message UI so prior identity messages are not shown under the new session.

#### Scenario: Switch OA

- **WHEN** a user already in a development session submits a different `oa` with a valid passphrase
- **THEN** the client uses the new ticket and thread, and the message list is cleared for the new identity

### Requirement: Formal OA launch path unchanged

The existing `POST /v1/chat/launch` and `POST /v1/chat/session` (launch_code) flow MUST remain the production path and MUST NOT require development-login settings.

#### Scenario: Formal launch still works with dev switch off

- **WHEN** development login is disabled and a valid OA assertion is presented to `/v1/chat/launch`
- **THEN** launch_code issuance and redeem behave as before
