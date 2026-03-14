---
phase: 01-foundation
plan: 02
subsystem: database
tags: [aiosqlite, sqlite, schema, migrations, pytest, pytest-asyncio]

# Dependency graph
requires: []
provides:
  - "Per-tenant SQLite schema: memories (20 cols), entities (11), relations (15, 3 FKs), feedback (5, 1 FK)"
  - "embedding BLOB DEFAULT NULL column on memories for Phase 2 vector search"
  - "11 performance indexes across memories, entities, relations"
  - "TENANT_SCHEMA_SQL constant and init_tenant_db() async function"
  - "migrations/002_tenant_tables.sql raw SQL for documentation/reference"
  - "9-test suite verifying schema structure, FK enforcement, and embedding readiness"
affects: [01-03-manager, 01-04-api, phase-02-memory, phase-03-auth]

# Tech tracking
tech-stack:
  added: [aiosqlite, pytest-asyncio]
  patterns:
    - "Schema-only module: tenant.py owns DDL, manager.py owns connections — clean separation"
    - "executescript for idempotent DDL, explicit commit after schema init"
    - "PRAGMA foreign_keys=ON set by caller, not by init_tenant_db — pragmas are connection-level"

key-files:
  created:
    - app/db/tenant.py
    - migrations/002_tenant_tables.sql
    - tests/test_tenant_db.py
  modified: []

key-decisions:
  - "embedding BLOB DEFAULT NULL added to memories in Phase 1 to avoid a Phase 2 schema migration"
  - "init_tenant_db receives open connection, not a path — TenantDBManager owns connection lifecycle"
  - "SQLite PRAGMA table_info returns dflt_value as string 'NULL' not Python None for DEFAULT NULL columns"

patterns-established:
  - "Schema constant pattern: TENANT_SCHEMA_SQL is a module-level string, not read from file — faster, single-import"
  - "Test fixture opens connection with WAL + foreign_keys ON before calling init_tenant_db"

# Metrics
duration: 2min
completed: 2026-03-14
---

# Phase 1 Plan 02: Tenant DB Schema Summary

**ZimMemory v15 schema ported to per-tenant SQLite with 20-column memories table (embedding BLOB added), 3-FK relations graph, and 9 passing pytest-asyncio tests covering structure, FK enforcement, and Phase 2 readiness**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-14T15:29:10Z
- **Completed:** 2026-03-14T15:31:04Z
- **Tasks:** 2
- **Files modified:** 3 (created)

## Accomplishments

- Per-tenant schema module with all ZimMemory v15 tables exactly ported, plus embedding BLOB for Phase 2
- migrations/002_tenant_tables.sql as standalone SQL reference (same schema as TENANT_SCHEMA_SQL constant)
- 9 pytest-asyncio tests covering all schema contracts: table existence, column constraints, FK definitions, index presence, schema versioning, NULL embedding insert, and FK enforcement

## Task Commits

Each task was committed atomically:

1. **Task 1: Tenant DB schema SQL and init function** - `0055468` (feat)
2. **Task 2: Tenant DB schema tests** - `04710a5` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `/Users/sevs/memoralabs/app/db/tenant.py` - TENANT_SCHEMA_SQL constant + init_tenant_db(conn) async function
- `/Users/sevs/memoralabs/migrations/002_tenant_tables.sql` - Raw SQL migration file (same schema, for reference)
- `/Users/sevs/memoralabs/tests/test_tenant_db.py` - 9 pytest-asyncio tests covering full schema contracts

## Decisions Made

- Added `embedding BLOB DEFAULT NULL` to memories table now (Phase 1) to avoid requiring a migration in Phase 2 when vector search is implemented. Column is present but null — no Phase 2 migration needed.
- `init_tenant_db()` accepts an already-open `aiosqlite.Connection` rather than opening its own. Connection lifecycle belongs to TenantDBManager (Plan 03); schema application belongs to this module. Clean separation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect test assertion for SQLite DEFAULT NULL**
- **Found during:** Task 2 (test execution)
- **Issue:** Test asserted `col_map["embedding"][4] is None` but SQLite PRAGMA table_info returns the string `'NULL'` (not Python `None`) for `DEFAULT NULL` columns
- **Fix:** Changed assertion to accept either `None` or `'NULL'` — both are valid representations of the null default depending on SQLite version/driver behavior
- **Files modified:** tests/test_tenant_db.py
- **Verification:** All 9 tests pass after fix
- **Committed in:** `04710a5` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - incorrect test expectation about SQLite PRAGMA output)
**Impact on plan:** Minor test behavior fix. Schema itself was correct from the start.

## Issues Encountered

None beyond the SQLite PRAGMA behavior documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Tenant schema module complete and tested — Plan 03 (TenantDBManager) can import and use `init_tenant_db`
- All FK constraints verified working — relation graph is safe to use
- embedding column ready for Phase 2 vector search without migration
- Blocker: none

## Self-Check: PASSED

- app/db/tenant.py: FOUND
- migrations/002_tenant_tables.sql: FOUND
- tests/test_tenant_db.py: FOUND
- commit 0055468: FOUND
- commit 04710a5: FOUND
- 9/9 tests passing: VERIFIED

---
*Phase: 01-foundation*
*Completed: 2026-03-14*
