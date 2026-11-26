## ADDED Requirements

### Requirement: Unified invoke entry for Agent

The OA system SHALL expose a single Agent entry at `/general/ds/agent/invoke.php` that authenticates the caller, binds request-local identity, includes a configured target script under the webroot, and returns that script's response. Existing business interface files MUST NOT be modified for this capability.

#### Scenario: Missing credentials rejected
- **WHEN** a request hits `invoke.php` without a valid employee `Authorization` or without a valid gateway secret
- **THEN** the system MUST reject the request and MUST NOT include any target script

#### Scenario: Successful read invoke
- **WHEN** a request supplies valid `Authorization` and gateway secret, a safe `target` under an allowed prefix, and a GET (or other read) method without requiring confirm
- **THEN** the system MUST resolve the employee via Service `checkLogin`, bind request-local session identity for that employee, include the target script, strip `Set-Cookie` from the response, and return the included script's body and status

### Requirement: Gateway secret and employee token

`invoke.php` MUST require both a valid employee Authorization (validated via `ANew('oa/user')->checkLogin` or equivalent Passport check) and a gateway secret matching the configured Agent gateway secret (header `X-Agent-Gateway-Secret` or project-equivalent). Gateway secret alone MUST NOT grant access to business targets.

#### Scenario: Gateway secret alone insufficient
- **WHEN** a request presents a valid gateway secret but no valid employee Authorization
- **THEN** the system MUST reject the request

#### Scenario: Employee token alone insufficient
- **WHEN** a request presents a valid employee Authorization but no valid gateway secret
- **THEN** the system MUST reject the request

### Requirement: Target path guardrails

The system SHALL accept a target path from header `X-Agent-Target` or agreed parameter `target` (not from model-controlled free text on OA). After URL-decoding and normalization, the path MUST reject `..` and absolute paths, MUST end with `.php`, MUST refer to an existing file, and MUST fall under one of the allowed root prefixes: `general/`, `inc/`, `helper/`, `task/` (defaults; configurable extension allowed).

#### Scenario: Path traversal rejected
- **WHEN** `target` contains `..` or resolves outside allowed prefixes
- **THEN** the system MUST reject the request and MUST NOT include a file

#### Scenario: Allowed prefix accepted
- **WHEN** `target` is a normalized relative path such as `general/ds/example/foo_api.php` that exists
- **THEN** the system MUST allow include after auth succeeds

### Requirement: Request-local session bind without login cookie

After successful employee authentication, the system MUST populate the same identity globals/session keys expected by `inc/auth.php` / `helper/auth_login.php` for the current request only, MUST NOT treat this as a durable browser login, and MUST strip `Set-Cookie` headers from the response to the Agent.

#### Scenario: Identity available to included script
- **WHEN** invoke successfully binds identity and includes a script that checks session login
- **THEN** the included script MUST see the Bearer-resolved employee as logged in for that request

#### Scenario: No session cookie to Agent
- **WHEN** invoke returns a response after include
- **THEN** the response to Agent MUST NOT include `Set-Cookie` that would establish an OA login session for the caller

### Requirement: Identity parameter override

Before include, the system MUST override request identity parameters (including `oa` and `user_id` where present) with the Bearer-resolved employee, and MUST remove gateway secret, confirm assertion, and `target` from the parameter bags passed through to business logic.

#### Scenario: Spoofed oa ignored
- **WHEN** the caller sends a different `oa` in query or body than the Authorization subject
- **THEN** the included script MUST observe the Authorization subject, not the spoofed value

### Requirement: Write confirm HMAC assertion

For write invocations (non-GET and/or high-risk as agreed with Agent), `invoke.php` MUST require header `X-Agent-Confirm-Assertion` (or equivalent). The assertion MUST be HMAC-SHA256 over a payload using the shared OA assertion HMAC secret, with `iss`/`aud` distinct from login assertions (login host assertion MUST NOT be accepted as write confirm). Payload MUST include at least `oa`, `action`, `exp`, `nonce`, `iss`, `aud`. The system MUST verify signature, expiry, `oa` match to Bearer subject, and that `nonce` is unused in Redis; then mark `nonce` used.

#### Scenario: Write without assertion rejected
- **WHEN** a write invoke has valid B2 credentials but no valid confirm assertion
- **THEN** the system MUST reject the request and MUST NOT include the target

#### Scenario: Assertion oa mismatch rejected
- **WHEN** confirm assertion `oa` differs from the Authorization subject
- **THEN** the system MUST reject the request

#### Scenario: Replay nonce rejected
- **WHEN** a previously accepted confirm assertion nonce is presented again
- **THEN** the system MUST reject the request

#### Scenario: Read without assertion allowed
- **WHEN** a read invoke has valid B2 credentials and no confirm assertion
- **THEN** the system MUST proceed without requiring confirm assertion

### Requirement: Parameter merging L1

Business parameters MUST be accepted via normal query string and body. The system MUST merge them into `$_GET` / `$_POST` as appropriate for the included script after stripping sensitive keys and applying identity overrides.

#### Scenario: Query params visible to included script
- **WHEN** Agent calls invoke with business query parameters
- **THEN** the included script MUST read those parameters from its usual `$_GET` / request helpers
