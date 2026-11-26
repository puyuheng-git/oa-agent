## ADDED Requirements

### Requirement: Tool mounts only through invoke

Agent Tools that call OA Webroot scripts MUST use the OA upstream base URL with path `/general/ds/agent/invoke.php`. The legacy script relative path MUST be sent as `X-Agent-Target` (or agreed `target`) from server-side Tool configuration. `target` MUST NOT be a model-fillable parameter.

#### Scenario: Outbound includes target from config
- **WHEN** the runtime executes such a Tool
- **THEN** the HTTP request MUST go to `invoke.php` and MUST include the configured target header/parameter from Tool config, not from model args

#### Scenario: Model cannot choose arbitrary target
- **WHEN** a Tool schema is registered for OA invoke
- **THEN** `model_params` MUST NOT include `target`, route file path, or gateway/confirm secrets

### Requirement: Outbound auth headers

For OA invoke Tools, the Agent Connector MUST attach the session employee Authorization and the configured gateway secret header on every call. Employee tokens MUST remain server-side only (not exposed to the browser or model).

#### Scenario: Runtime call has B2 headers
- **WHEN** a chat run invokes an OA-web Tool
- **THEN** the outbound request MUST include valid employee Authorization and `X-Agent-Gateway-Secret`

### Requirement: Write confirmation assertion issuance

High-risk / write Tools that target OA invoke MUST wait for employee confirmation. After confirmation succeeds, the Agent MUST issue a short-lived confirm HMAC assertion using the same secret as OA assertion HMAC, with distinct `iss`/`aud` for write confirm, bound to the employee `oa` and Tool `action`, and MUST send it on the outbound invoke request. Login host assertions MUST NOT be reused as write confirm assertions.

#### Scenario: Write blocked before confirm
- **WHEN** a write OA-invoke Tool is selected but the employee has not confirmed
- **THEN** the runtime MUST NOT call `invoke.php` for that write

#### Scenario: Confirmed write carries assertion
- **WHEN** the employee confirms a pending write to an OA-invoke Tool
- **THEN** the subsequent outbound request MUST include `X-Agent-Confirm-Assertion` (or equivalent) matching the confirm payload rules

### Requirement: Admin probe same gates

Admin Tool test/probe against OA invoke MUST use the same `invoke.php`, a minted test-employee Authorization, the gateway secret, and for writes a short-lived confirm assertion. The system MUST NOT provide an unauthenticated or confirm-exempt debug entry for these targets.

#### Scenario: Admin read probe
- **WHEN** an admin probes a read OA-invoke Tool with a selected test employee
- **THEN** the probe MUST mint/use that employee's token and gateway secret against `invoke.php`

#### Scenario: Admin write probe requires confirm assertion
- **WHEN** an admin probes a write OA-invoke Tool
- **THEN** the probe MUST include a valid confirm assertion; probes without it MUST fail authentication/authorization at OA or be refused by the admin API before send

### Requirement: Upstream configuration

Operators MUST be able to configure an HTTP upstream (peer) whose base URL is the OA Web origin used for `invoke.php`. Tools select that upstream by key; relative Tool path remains `/general/ds/agent/invoke.php`.

#### Scenario: Configure OA web upstream
- **WHEN** an operator adds an upstream pointing at the OA Web origin and creates a Tool with path `/general/ds/agent/invoke.php` and a server-side target
- **THEN** runtime execution MUST resolve calls to `{upstream}{invoke path}` with the configured target
