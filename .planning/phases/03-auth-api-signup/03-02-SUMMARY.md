---
phase: 03-auth-api-signup
plan: "02"
subsystem: auth
tags: [fastapi, exception-handlers, structured-errors, last_used_at, sqlite, starlette]

# Dependency graph
requires:
  - phase: 03-auth-api-signup
    provides: "01 — get_tenant dependency with Bearer token auth and WWW-Authenticate headers"
provides:
  - "Global StarletteHTTPException handler returns structured JSON with error+message"
  - "RequestValidationError handler returns JSON 422 with error+message+details array"
  - "Catch-all Exception handler returns JSON 500, never leaks stack traces"
  - "update_key_last_used() updates last_used_at on every successful auth"
  - "7 tests covering 401/422/404 JSON shape, WWW-Authenticate header, Content-Type, last_used_at"
affects: [03-03-auth-api-signup, all-future-phases]

# Tech tracking
tech-stack:
  added: []
  patterns: [global-exception-handlers, fire-and-forget-update, raise_server_exceptions-false-for-error-tests]

key-files:
  created:
    - tests/test_error_handlers.py
  modified:
    - app/main.py
    - app/deps.py
    - app/db/system.py

key-decisions:
  - "exc.headers passthrough in StarletteHTTPException handler preserves WWW-Authenticate: Bearer on 401 responses"
  - "update_key_last_used wrapped in try/except in deps.py — auth never fails due to usage tracking"
  - "raise_server_exceptions=False in TestClient for error tests — lets 500s return JSON instead of raising"
  - "test_404 and test_last_used_at require create_tenant_db — test fixture must initialize tenant DB, not just system DB records"

patterns-established:
  - "Error handler pattern: @app.exception_handler(ExcType) returns JSONResponse with error+message shape"
  - "Fire-and-forget DB update: wrapped in try/except pass, never blocks or fails the primary operation"
  - "Error test fixture: must call create_tenant_db after create_tenant+create_api_key"

# Metrics
duration: 2min
completed: 2026-03-14
---

# Phase 3 Plan 02: Error Handlers and last_used_at Summary

**Three global exception handlers enforce structured JSON errors across all routes; last_used_at is written on every successful API key auth via fire-and-forget UPDATE**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-14T00:12:01Z
- **Completed:** 2026-03-14T00:14:29Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- StarletteHTTPException handler converts all HTTP errors to `{"error": "...", "message": "..."}` JSON, preserving `WWW-Authenticate: Bearer` on 401 via `exc.headers` passthrough
- RequestValidationError handler returns 422 with `{"error": "VALIDATION_ERROR", "message": "...", "details": [...]}` including Pydantic field errors
- Catch-all Exception handler returns 500 with no stack trace exposure
- `update_key_last_used()` added to `app/db/system.py`, called in `get_tenant()` after successful auth with best-effort try/except
- 7 tests covering all error shapes, Content-Type, WWW-Authenticate, and last_used_at behavior — 176/176 total tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Add global exception handlers and last_used_at tracking** - `cb8438b` (feat)
2. **Task 2: Write structured error response tests** - `bb8b8b0` (test)

**Plan metadata:** (docs commit — see final commit)

## Files Created/Modified
- `app/main.py` - Added imports, `_status_to_error_code()` helper, 3 exception handlers
- `app/deps.py` - Import `update_key_last_used`, fire-and-forget call after successful auth
- `app/db/system.py` - Added `update_key_last_used()` function
- `tests/test_error_handlers.py` - 7 tests: 401 shape, WWW-Authenticate, invalid key, 422 shape, 404 shape, Content-Type check, last_used_at update

## Decisions Made
- `exc.headers` passthrough in `http_exception_handler` ensures the `WWW-Authenticate: Bearer` header set by `deps.py` is preserved in 401 responses — no changes needed to deps.py 401 raises
- `update_key_last_used` wrapped in `try/except pass` in `get_tenant()` — usage tracking must never fail or slow down authentication
- Test file uses `raise_server_exceptions=False` — allows 500 responses to be returned as JSON responses in tests rather than raising in the test process
- Test fixture must call `app.state.tenant_manager.create_tenant_db(tenant_id)` to initialize tenant DB; tests that reach memory endpoints 500 without it (discovered and fixed inline)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture missing create_tenant_db call**
- **Found during:** Task 2 (Write structured error response tests)
- **Issue:** `_setup_tenant()` only inserted system DB records (tenant + api_key) without initializing the tenant DB. The GET /v1/memory and GET /v1/memory/{id} endpoints attempt to open a connection to the tenant DB, which did not exist, causing 500 instead of the expected 200/404
- **Fix:** Added `await app.state.tenant_manager.create_tenant_db(tenant_id)` to `_setup_tenant()` async block, matching the pattern used in `test_memory_read.py` and `test_memory_write.py`
- **Files modified:** tests/test_error_handlers.py
- **Verification:** test_404_structured_json and test_last_used_at_updated both passed after fix; 176/176 total tests pass
- **Committed in:** bb8b8b0 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — missing test fixture setup)
**Impact on plan:** Necessary correctness fix. No scope creep. Tests now match established fixture pattern.

## Issues Encountered
None beyond the test fixture deviation documented above.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- All error responses are structured JSON — 03-03 (signup API) can rely on consistent error contract
- last_used_at tracking active — usage analytics ready when needed
- 176 tests passing — full regression baseline for Phase 3 Plan 3

---
*Phase: 03-auth-api-signup*
*Completed: 2026-03-14*
