---
phase: 03-auth-api-signup
plan: 01
subsystem: auth
tags: [fastapi, aiosqlite, pydantic, slowapi, secrets, sha256]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: system.db schema — tenants + api_keys tables, create_tenant, create_api_key, get_tenant_by_key_hash
  - phase: 02-core-memory-api
    provides: limiter module, get_tenant dependency, TestClient test pattern with portal.call

provides:
  - POST /v1/auth/signup endpoint (public, rate limited 5/min)
  - _generate_key() helper — ml_<64hex>, 256-bit entropy, returns (plaintext, sha256_hash, key_prefix)
  - SignupResponse Pydantic model
  - auth_router mounted at /v1/auth in main.py
  - 7 integration tests for signup behavior

affects:
  - 03-auth-api-signup/03-02 (key rotation, revocation — reuses _generate_key)
  - 03-auth-api-signup/03-03 (auth middleware — exempts /v1/auth/signup)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Public endpoint with no Depends(get_tenant) — limiter uses IP fallback for unauthenticated requests
    - aiosqlite.IntegrityError caught at router layer for 409 Conflict on duplicate email
    - secrets.token_hex(32) for cryptographic key generation (NOT uuid4)
    - SHA-256 hash stored, plaintext returned exactly once and never persisted

key-files:
  created:
    - app/routers/auth.py
    - tests/test_auth_signup.py
  modified:
    - app/models/schemas.py
    - app/main.py

key-decisions:
  - "03-01 — _generate_key is module-level in auth.py: reused by key rotation in 03-03 without reimporting from deps"
  - "03-01 — validation_exception_handler ctx values stringified: Pydantic v2 ctx contains ValueError objects that break json.dumps — str() coercion required"
  - "03-01 — autouse limiter reset fixture: slowapi in-memory storage bleeds across tests when all share testclient IP; reset before/after each test"

patterns-established:
  - "Limiter reset fixture: autouse pytest fixture calling limiter._storage.reset() prevents rate limit pollution between tests"
  - "Exception handler response shape: {error: CODE, message: str} — tests must use body.get('message') not body['detail']"

# Metrics
duration: 3min
completed: 2026-03-14
---

# Phase 3 Plan 1: Auth Signup Summary

**POST /v1/auth/signup endpoint returning a plaintext ml_ API key (SHA-256 hash stored only), with 409 on duplicate email, rate-limited 5/min, and 7 integration tests — 176/176 tests passing**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-14T17:31:55Z
- **Completed:** 2026-03-14T17:34:27Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `POST /v1/auth/signup` endpoint — public, no auth required, returns 201 with `ml_<64hex>` API key shown once
- `_generate_key()` helper using `secrets.token_hex(32)` for 256-bit entropy — module-level for reuse in key rotation
- Duplicate email caught via `aiosqlite.IntegrityError` → 409 Conflict (not 500)
- 7 integration tests covering: success, key works immediately, plaintext not stored (DB verified), duplicate 409, missing/invalid email 422, no auth required
- All 176 tests (7 new + 169 existing) pass

## Task Commits

1. **Task 1: Create auth router with signup endpoint and response model** - `57c23b2` (feat)
2. **Task 2: Write signup integration tests** - `1fbe0b6` (feat)

**Plan metadata:** `[pending]` (docs: complete plan)

## Files Created/Modified

- `app/routers/auth.py` — Auth router with `POST /v1/auth/signup` and `_generate_key()` helper
- `app/models/schemas.py` — Added `SignupResponse` Pydantic model
- `app/main.py` — Mounted `auth_router`; fixed `validation_exception_handler` to stringify Pydantic v2 ctx values
- `tests/test_auth_signup.py` — 7 integration tests with rate limiter reset fixture

## Decisions Made

- `_generate_key()` is module-level (not inside the endpoint) so plan 03-03 (key rotation) can import it without circular dependency
- `validation_exception_handler` ctx values must be stringified — Pydantic v2 returns `ValueError` objects in error context that are not JSON-serializable
- Rate limiter storage reset between tests via autouse fixture — TestClient always uses the same IP, causing bleed across tests when endpoint is rate-limited

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed non-serializable ValueError in validation_exception_handler**
- **Found during:** Task 2 (test_signup_invalid_email_422 failure)
- **Issue:** The linter-added `validation_exception_handler` in `main.py` called `exc.errors()` which returns Pydantic v2 dicts with `ctx` containing raw `ValueError` instances — `json.dumps` raised `TypeError: Object of type ValueError is not JSON serializable`
- **Fix:** Added `_safe_error()` helper that stringifies all `ctx` dict values before serialization
- **Files modified:** `app/main.py`
- **Verification:** `test_signup_invalid_email_422` passes; validation errors return valid JSON
- **Committed in:** `1fbe0b6` (Task 2 commit)

**2. [Rule 1 - Bug] Fixed rate limiter cross-test pollution**
- **Found during:** Task 2 (test_signup_no_auth_required getting 429)
- **Issue:** All TestClient requests share the same IP ("testclient"); 5 prior signup requests exhausted the 5/min rate limit, causing the final test to receive 429 instead of 201
- **Fix:** Added autouse pytest fixture to reset `limiter._storage` before and after each test
- **Files modified:** `tests/test_auth_signup.py`
- **Verification:** All 7 tests pass without 429 errors
- **Committed in:** `1fbe0b6` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — bugs from linter-added code)
**Impact on plan:** Both fixes required for test correctness. No scope creep.

## Issues Encountered

- Linter automatically added structured exception handlers (`http_exception_handler`, `validation_exception_handler`, `unhandled_exception_handler`) to `main.py` during the Task 1 commit. The `validation_exception_handler` had a serialization bug. The `http_exception_handler` changed the 409 response shape from `{"detail": ...}` to `{"error": ..., "message": ...}` — tests updated accordingly.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `/v1/auth/signup` is complete and tested
- `_generate_key()` ready for reuse in key rotation (03-03)
- Auth router mounted and all 176 tests pass
- Ready for plan 03-02 (key rotation/revocation endpoints)

## Self-Check: PASSED

- app/routers/auth.py: FOUND
- app/models/schemas.py: FOUND
- tests/test_auth_signup.py: FOUND
- 03-01-SUMMARY.md: FOUND
- commit 57c23b2: FOUND
- commit 1fbe0b6: FOUND

---
*Phase: 03-auth-api-signup*
*Completed: 2026-03-14*
