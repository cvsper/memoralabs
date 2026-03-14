---
phase: 01-foundation
plan: 03
subsystem: database
tags: [aiosqlite, sqlite, lru-cache, connection-pool, path-traversal, pytest-asyncio]

# Dependency graph
requires:
  - phase: 01-foundation/01-02
    provides: init_tenant_db function that applies per-tenant schema to an open connection
  - phase: 01-foundation/01-01
    provides: project scaffold, app/config.py with DATA_DIR

provides:
  - TenantDBManager class with OrderedDict LRU connection pool (app/db/manager.py)
  - UUID validation guarding against path traversal on all tenant_id inputs
  - WAL mode + foreign_keys enforcement on every connection
  - 14 passing tests covering eviction, isolation, pragmas, and path protection

affects:
  - all future phases that need per-tenant DB connections
  - API layer (Phase 2) — will call TenantDBManager.get_connection / create_tenant_db
  - embedding pipeline (Phase 2) — writes to tenant DB via pooled connection

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OrderedDict as LRU pool: move_to_end on cache hit, popitem(last=False) on eviction"
    - "Single asyncio.Lock guards all pool mutations — no double-open risk for same tenant"
    - "Schema separation: tenant.py knows WHAT, manager.py knows WHERE/HOW"

key-files:
  created:
    - app/db/manager.py
    - tests/test_manager.py
    - tests/test_isolation.py
  modified: []

key-decisions:
  - "UUID regex (lowercase only) is the path-traversal guard — no filesystem join tricks possible"
  - "Lock held during entire get_connection to prevent duplicate opens for same tenant_id under concurrent load"
  - "create_tenant_db raises if file exists — no silent overwrite, callers must handle idempotency"

patterns-established:
  - "Validate before any filesystem I/O: _validate_tenant_id called in _tenant_db_path"
  - "Evict-then-open: LRU closed before new connection opened to keep pool bounded"
  - "Fixture pattern for async tests: pytest_asyncio.fixture with close_all teardown"

# Metrics
duration: 2min
completed: 2026-03-14
---

# Phase 1 Plan 3: TenantDBManager Summary

**Async LRU connection pool for per-tenant SQLite DBs with UUID-validated path traversal protection, WAL enforcement, and 14 passing tests proving cross-tenant isolation and LRU eviction semantics**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-14T15:33:38Z
- **Completed:** 2026-03-14T15:35:06Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- TenantDBManager with OrderedDict LRU pool: cache hit promotes to MRU, capacity miss closes evicted connection before opening new one
- UUID regex validation blocks path traversal at the only entry point (_tenant_db_path), no filesystem ops reachable with malicious input
- 14 tests: 11 unit tests (pragmas, eviction, teardown) + 3 cross-tenant isolation proofs

## Task Commits

1. **Task 1: TenantDBManager implementation** - `22ead24` (feat)
2. **Task 2: Manager unit tests + cross-tenant isolation tests** - `b97e7aa` (feat)

## Files Created/Modified

- `app/db/manager.py` - TenantDBManager class: LRU pool, UUID validation, WAL/pragma setup, create_tenant_db, close_all
- `tests/test_manager.py` - 11 unit tests for connection pooling, eviction, pragma enforcement, path traversal rejection
- `tests/test_isolation.py` - 3 cross-tenant isolation tests: data separation, separate .db files, correct on-disk path

## Decisions Made

- UUID regex (`^[a-f0-9]{8}-...$` lowercase only) is the sole path-traversal guard — simple, zero-overhead, no filesystem access possible with invalid input
- Lock held for the entire `get_connection` body to prevent two coroutines opening the same tenant DB simultaneously under concurrent requests
- `create_tenant_db` raises ValueError if .db file already exists — idempotency is caller responsibility, no silent overwrite

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- TenantDBManager is the complete connection layer; Phase 2 (API) can call `get_connection` and `create_tenant_db` directly
- Pool defaults (max_connections=50) read from `app/config.py MAX_TENANT_CONNECTIONS` — ready for environment override on Render
- All three foundation schema files (system.py, tenant.py, manager.py) are in place for the FastAPI app wiring in Phase 2

---
*Phase: 01-foundation*
*Completed: 2026-03-14*

## Self-Check: PASSED

- app/db/manager.py: FOUND
- tests/test_manager.py: FOUND
- tests/test_isolation.py: FOUND
- .planning/phases/01-foundation/01-03-SUMMARY.md: FOUND
- Commit 22ead24 (Task 1): FOUND
- Commit b97e7aa (Task 2): FOUND
