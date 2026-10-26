# Task 1 Report: LoginConst + checkLogin + agentMintOfficeToken

## Status

**DONE_WITH_CONCERNS**

## Commits

none (per plan Global Constraint / user request)

## Summary

Implemented Service auth foundation for OA Agent MVP-1:

1. `LoginConst::TOKEN_BIZ_CODE_OFFICE = 'office'` and `LOGIN_EXPIRE_OFFICE = 1800`, wired into `TOKEN_EXPIRE`.
2. `Export::checkLogin` now loads DB user via `UserImpl::getUserInfo($uid, $fields)` and returns the **DB row** (not Passport payload).
3. New `AgentTokenImpl::mint` + `Export::agentMintOfficeToken` with gateway secret check, `DuplicateSubmit` key `oa.user.agentMintOfficeToken`, user/NOT_LOGIN guards, Passport office token mint, audit log.
4. New `app\service\oa\user\Error` codes for mint failures.

## Files changed

| Path | Action |
|------|--------|
| `framework/com-lib/src/constant/user/LoginConst.php` | Modified |
| `service/service-app/src/service/oa/user/Export.php` | Modified |
| `service/service-app/src/service/oa/user/logic/AgentTokenImpl.php` | Created |
| `service/service-app/src/service/oa/user/Error.php` | Created |
| `site/tool/_smoke_agent_mint_v2.php` | Ephemeral smoke helper |

## Smoke test

Script: `site/tool/_smoke_agent_mint_v2.php`

| Case | Result |
|------|--------|
| Constants TOKEN_BIZ_CODE_OFFICE / expire map | PASS (office, 1800) |
| Wrong gateway_secret | PASS (Exception code 1000280101) |
| Correct secret mint + checkLogin | BLOCKED - local Redis 127.0.0.1:6379 refused |
| php -l on changed PHP | PASS |

One-line: wrong-secret + constants OK; full mint/checkLogin blocked by Redis down on this machine.

## Stack code review

**Changed files:** LoginConst.php, Export.php, AgentTokenImpl.php, Error.php
**OA files:** none | **Service files:** all of the above

### Service checklist (service-php73-architect)

- S1 PHP <=7.3 syntax: PASS
- S2 UTF-8 + snake_case array keys + <=5 params: PASS
- S3 Module layout Export/logic/Error: PASS
- S4 Exception via lib\exception\Exception::user: PASS
- S5 No raw SQL / no Model include in business: PASS
- S6 Secret not echoed; empty env secret rejected: PASS
- S7 Comments on new logic: PASS
- S8 Minimal diff: PASS
- S9 DuplicateSubmit::assert + clear on business failure: PASS (oa.user.agentMintOfficeToken)

### Cross-stack

- X1-X4: N/A (Service-only Task 1)

**Result:** PASS

## Concerns

1. Redis unavailable locally - could not end-to-end verify mint token + checkLogin USER_ID round-trip; re-run smoke after Redis is up.
2. AGENT_GATEWAY_SECRET not in .env yet - must be configured before Task 2 gateway mint route works.
3. Export.php historically contains truncated UTF-8 in some old docblocks (pre-existing); new/edited sections for this task are valid UTF-8.
4. Ephemeral smoke script left at site/tool/_smoke_agent_mint_v2.php for local re-run; safe to delete.

## Contract for Task 2

```
ANew('oa/user')->agentMintOfficeToken($oa, $gatewaySecret, $operateUser = 'agent-gateway')
=> ['authorization' => string, 'uid' => int, 'oa' => string, 'expire' => int]
env: AGENT_GATEWAY_SECRET
```
