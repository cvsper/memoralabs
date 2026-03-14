---
phase: 02-core-memory-api
plan: 03
subsystem: api
tags: [fastapi, sqlite, aiosqlite, slowapi, rate-limiting, background-tasks, dedup]

# Dependency graph
requires:
  - phase: 02-01
    provides: dedup service (text_hash, check_exact_duplicate, check_cosine_duplicate), entity extraction service (process_entities_for_memory), Pydantic models (MemoryCreate, MemoryResponse), deps (get_tenant), db/system (log_usage)
  - phase: 02-02
    provides: EmbeddingClient (embed_single), TenantIndexManager (add_vector), slowapi Limiter in app.main
provides:
  - POST /v1/memory endpoint — primary memory ingestion with dedup, background embedding, background entity extraction, usage logging, and per-tenant rate limiting
  - app/limiter.py — shared Limiter instance module (eliminates circular import pattern)
  - 13 integration tests covering success, dedup, scoping, validation, auth enforcement, and usage logging
affects: [02-04, 02-05, 03-auth-middleware, 04-retrieval, 05-intelligence]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Shared limiter module (app/limiter.py) imported by both app/main.py and routers — avoids circular imports from @limiter.limit decorator usage
    - BackgroundTasks for non-blocking embedding and entity extraction — response returns immediately, side effects happen after
    - JSONResponse wrapping for 200 duplicate returns from 201-default endpoint
    - Starlette TestClient + monkeypatch DATA_DIR pattern for integration tests (same as test_deps.py)

key-files:
  created:
    - app/limiter.py
    - app/routers/memory.py
    - tests/test_memory_write.py
  modified:
    - app/main.py

key-decisions:
  - "02-03 — Shared app/limiter.py module: limiter extracted from app.main to avoid circular import when app.routers.memory imports @limiter.limit decorator"
  - "02-03 — JSONResponse for duplicate 200: endpoint defaults to 201, duplicate returns explicit JSONResponse(status_code=200) with MemoryResponse serialized via model_dump()"
  - "02-03 — Background embedding logs warning on circuit breaker open: no failure thrown, observability via logger.warning"
  - "02-03 — Cosine dedup runs post-embedding in background: only soft-deletes new memory if near-duplicate found, original is preserved"

patterns-established:
  - "Router files import limiter from app.limiter (not app.main) to prevent circular imports"
  - "BackgroundTasks functions wrap entire body in try/except + logger.exception — silently swallowed exceptions are made observable"
  - "Duplicate HTTP 200 response uses JSONResponse wrapper when endpoint default status_code is 201"

# Metrics
duration: 3min
completed: 2026-03-14
---

# Phase 2 Plan 3: POST /v1/memory — Memory Write Endpoint Summary

**POST /v1/memory with exact-match dedup (text_hash), background embedding + cosine dedup, background entity extraction, usage logging, and 60/min per-tenant rate limiting via slowapi — 13/13 integration tests pass**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-14T16:42:43Z
- **Completed:** 2026-03-14T16:45:48Z
- **Tasks:** 2
- **Files modified:** 4 (1 created limiter module, 1 memory router, 1 test file, 1 main.py updated)

## Accomplishments
- POST /v1/memory endpoint: 201 for new memories, 200 for exact duplicates (case/whitespace-insensitive text_hash)
- Non-blocking background tasks: embedding generation (with cosine dedup + soft-delete) and entity extraction queued via BackgroundTasks
- Per-tenant rate limiting at 60/minute using @limiter.limit decorator (SHA-256 hashed key, not raw)
- Every request logged in usage_log (memory.create for new, memory.create.duplicate for dupes)
- 13 integration tests covering all success, error, dedup, and usage-log cases

## Task Commits

Each task was committed atomically:

1. **Task 1: POST /v1/memory endpoint with background tasks and rate limiting** - `f4ae882` (feat)
2. **Task 2: Integration tests for memory write endpoint** - `cd64c4b` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `app/limiter.py` - Shared Limiter instance with get_tenant_key key function; extracted from app/main.py to break circular import
- `app/routers/memory.py` - POST /v1/memory endpoint: dedup, background embedding+cosine-dedup, background entity extraction, usage logging, rate limiting
- `app/main.py` - Import limiter from app.limiter; wire memory_router after health_router
- `tests/test_memory_write.py` - 13 integration tests using Starlette TestClient + monkeypatch pattern

## Decisions Made
- Extracted `limiter` to `app/limiter.py` to avoid circular import (`app.main` imports routers, routers need `limiter` — a shared module breaks the cycle)
- Duplicate response uses `JSONResponse(status_code=200, content=MemoryResponse(...).model_dump())` because the endpoint declares `status_code=201` — explicit JSONResponse is the only way to override per-response
- Background embedding wraps in `try/except` with `logger.exception` — BackgroundTasks silently swallows all exceptions, so explicit logging is mandatory for observability (Pitfall 6 from research)
- Cosine dedup runs in background after embedding: soft-deletes new memory if a near-duplicate (similarity >= 0.95) is found among existing memories

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extracted limiter to app/limiter.py to prevent circular import**
- **Found during:** Task 1 (POST /v1/memory endpoint)
- **Issue:** Plan specified `from app.main import limiter` in the router, but `app.main` imports `from app.routers.memory import router` — circular import that would crash at startup
- **Fix:** Created `app/limiter.py` with the `Limiter` instance and `get_tenant_key` function. Updated `app/main.py` to import from `app.limiter`. Router imports from `app.limiter` instead.
- **Files modified:** app/limiter.py (created), app/main.py (updated import), app/routers/memory.py (import from app.limiter)
- **Verification:** `python3 -c "from app.routers.memory import router"` imports cleanly; `python3 -c "from app.main import app"` starts without error
- **Committed in:** f4ae882 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — circular import)
**Impact on plan:** Essential fix. Without it, the app crashes at startup. Same pattern slowapi docs recommend.

## Issues Encountered
None beyond the circular import deviation above.

## Next Phase Readiness
- POST /v1/memory is fully operational — the core write path is complete
- Dedup (exact + post-embedding cosine), background tasks, rate limiting, and usage logging all verified
- Ready for 02-04 (GET /v1/memory/{id} + PATCH + DELETE) or 02-05 (POST /v1/memory/search)
- No blockers

## Self-Check: PASSED

- app/limiter.py: FOUND
- app/routers/memory.py: FOUND
- tests/test_memory_write.py: FOUND
- 02-03-SUMMARY.md: FOUND
- Commit f4ae882: FOUND
- Commit cd64c4b: FOUND

---
*Phase: 02-core-memory-api*
*Completed: 2026-03-14*
