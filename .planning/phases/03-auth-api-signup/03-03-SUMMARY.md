---
phase: 03-auth-api-signup
plan: 03
subsystem: auth
tags: [fastapi, aiosqlite, pydantic, sha256, secrets, key-rotation]

# Dependency graph
requires:
  - phase: 03-auth-api-signup/03-01
    provides: _generate_key() helper, auth router, SignupResponse, create_api_key, create_tenant
  - phase: 03-auth-api-signup/03-02
    provides: update_key_last_used, global exception handlers, get_tenant dependency

provides:
  - POST /v1/auth/keys/rotate endpoint — requires Bearer auth, deactivates all old keys, returns new key once
  - deactivate_keys_for_tenant() DB helper in system.py
  - KeyRotateResponse Pydantic model in schemas.py
  - 7 rotation integration tests in tests/test_auth_rotate.py
  - Bug fix: signup now calls create_tenant_db so memories work immediately after signup

affects:
  - Phase 4+ (all phases using memory endpoints — signup now fully initialises tenant)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Key rotation: deactivate ALL old keys atomically before issuing new key — clean slate, no key enumeration risk
    - Rotation uses Depends(get_tenant) — current valid key authenticates the rotation, no separate credential needed
    - Tenant DB initialised at signup: create_tenant_db called in signup endpoint so first POST /v1/memory works immediately
    - Rotation tests use signup as setup: natural API flow (signup → rotate → verify) rather than raw DB fixture setup

key-files:
  created:
    - tests/test_auth_rotate.py
  modified:
    - app/routers/auth.py
    - app/db/system.py
    - app/models/schemas.py

key-decisions:
  - "03-03 — deactivate_keys_for_tenant deactivates ALL keys (not just the one used): prevents key accumulation, no ambiguity about which key is active after rotation"
  - "03-03 — signup calls create_tenant_db: tenant DB must exist before any memory endpoint call; without this, signup works but first memory POST returns 500"
  - "03-03 — rotation tests use signup API not raw DB setup: proves the full API flow works end-to-end, not just the rotation endpoint in isolation"

patterns-established:
  - "Full-flow integration tests: use public API endpoints for setup (signup) rather than raw DB fixtures where the endpoint is being tested"
  - "Tenant lifecycle: signup = create system records + init tenant DB; rotation = deactivate old keys + issue new key; memories unaffected throughout"

# Metrics
duration: 3min
completed: 2026-03-14
---

# Phase 3 Plan 3: Key Rotation Summary

**POST /v1/auth/keys/rotate deactivating all prior keys and issuing a new ml_ key atomically, with 7 integration tests proving old key revocation, new key auth, memory persistence through rotation, and double-rotation correctness — 183/183 tests passing**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-14T17:36:42Z
- **Completed:** 2026-03-14T17:39:43Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `POST /v1/auth/keys/rotate` endpoint — requires valid Bearer token, deactivates ALL existing keys for the tenant, issues a new `ml_<64hex>` key returned exactly once
- `deactivate_keys_for_tenant()` DB helper — single UPDATE sets `is_active=0` for all tenant keys, returns deactivated count
- `KeyRotateResponse` Pydantic model
- 7 integration tests: new key returned, old key 401, new key works, memories survive rotation (AUTH-05 core requirement), no-auth 401, invalid-key 401, double rotation (A→B→C: A+B dead, C works)
- Bug fix: signup now calls `create_tenant_db` so `POST /v1/memory` works immediately after signup without 500

## Task Commits

1. **Task 1: Add key rotation endpoint and DB helper** - `98a1816` (feat)
2. **Task 2: Write key rotation integration tests and fix signup tenant DB init** - `4cf1745` (feat)

**Plan metadata:** `[pending]` (docs: complete plan)

## Files Created/Modified

- `app/db/system.py` — Added `deactivate_keys_for_tenant()` helper
- `app/models/schemas.py` — Added `KeyRotateResponse` Pydantic model
- `app/routers/auth.py` — Added `POST /keys/rotate` endpoint; fixed signup to call `create_tenant_db`
- `tests/test_auth_rotate.py` — 7 rotation integration tests

## Decisions Made

- `deactivate_keys_for_tenant` deactivates ALL keys for a tenant (not just the key used in the request) — prevents key accumulation, ensures exactly one active key after rotation, eliminates ambiguity
- Signup endpoint must call `create_tenant_db` — without it, the tenant's SQLite file is never schema-initialized, so the first `POST /v1/memory` returns a 500 with `no such table: memories`
- Rotation tests use the signup API endpoint for setup rather than raw DB fixtures — exercises the full API flow and caught the `create_tenant_db` bug in the process

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed signup not initialising tenant DB**
- **Found during:** Task 2 (`test_rotate_preserves_memories` failing)
- **Issue:** The signup endpoint created records in the system DB (tenants, api_keys) but never called `create_tenant_db`. The tenant's per-tenant SQLite file was opened lazily but `init_tenant_db` (which applies the schema) was only called via `create_tenant_db`, not `get_connection`. Result: `POST /v1/memory` immediately after signup returns 500 with `sqlite3.OperationalError: no such table: memories`.
- **Fix:** Added `await request.app.state.tenant_manager.create_tenant_db(tenant_id)` at the end of the signup handler, after `create_api_key`.
- **Files modified:** `app/routers/auth.py`
- **Verification:** `test_rotate_preserves_memories` now passes; full test suite 183/183 passes
- **Committed in:** `4cf1745` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — production bug)
**Impact on plan:** Required for correctness. The natural API flow (signup → create memory) was broken without this fix. No scope creep.

## Issues Encountered

- Rotation verification command in plan checked for `/keys/rotate` but the router path is `/v1/auth/keys/rotate` (router has `prefix="/v1/auth"`). Verified against the full path instead — correct behavior.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `/v1/auth/keys/rotate` complete and tested
- Tenant DB lifecycle fully correct: signup initialises DB, rotation preserves tenant_id and all memories
- All 183 tests pass
- Phase 3 complete — ready for Phase 4

## Self-Check: PASSED

- app/db/system.py: FOUND
- app/models/schemas.py: FOUND
- app/routers/auth.py: FOUND
- tests/test_auth_rotate.py: FOUND
- commit 98a1816: FOUND
- commit 4cf1745: FOUND

---
*Phase: 03-auth-api-signup*
*Completed: 2026-03-14*
