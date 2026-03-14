---
phase: 02-core-memory-api
plan: "04"
subsystem: api
tags: [fastapi, sqlite, aiosqlite, pagination, soft-delete, entity-graph, crud]

# Dependency graph
requires:
  - phase: 02-01
    provides: entity extraction service + process_entities_for_memory
  - phase: 02-03
    provides: POST /v1/memory, _generate_embedding, _extract_entities background helpers, router structure

provides:
  - GET /v1/memory paginated list with scope filters
  - GET /v1/memory/{id} single memory with access_count tracking
  - GET /v1/memory/{id}/entities entity+relation graph for a memory (RETR-03)
  - PATCH /v1/memory/{id} partial field update with re-embedding on text change
  - DELETE /v1/memory/{id} soft-delete with vector index removal
  - 26 integration tests covering all endpoints
affects: [02-05, phase-03-search, phase-04-retrieval-intelligence]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dynamic WHERE clause building with list accumulation for optional scope filters"
    - "Route ordering: /entities before /{memory_id} to avoid FastAPI path match conflict"
    - "Soft-delete pattern: is_deleted=1, never physical removal; vector index marked deleted separately"
    - "access_count increment on GET (not just creation) for retrieval signal generation"

key-files:
  created:
    - tests/test_memory_read.py
  modified:
    - app/routers/memory.py

key-decisions:
  - "02-04 — Entity retrieval via relations table not memory_entities join table: actual schema uses relations.memory_id to link entities to memories; no memory_entities join table exists"
  - "02-04 — Entities list derived from relation source/target IDs: only entities referenced in relations are returned for a memory, matching what entity extraction actually stores"

patterns-established:
  - "Route ordering: register /memory/{id}/entities before /memory/{id} — FastAPI routes match in registration order"
  - "Scope filter pattern: build conditions/params lists, join with AND, pass as parameterized query"

# Metrics
duration: 3min
completed: 2026-03-14
---

# Phase 2 Plan 04: Memory Read, Update, Delete, and Entity Retrieval Summary

**Full CRUD surface for /v1/memory: paginated list, get-by-id, entity graph (RETR-03), patch with re-embedding, and soft-delete — completing the memory management API**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-14T16:48:17Z
- **Completed:** 2026-03-14T16:51:34Z
- **Tasks:** 2
- **Files modified:** 2 (1 modified + 1 created)

## Accomplishments

- 5 new route handlers in app/routers/memory.py completing the memory CRUD surface
- GET /v1/memory/{id}/entities exposes the entity knowledge graph built during ingestion (RETR-03)
- 26 integration tests covering all endpoints and edge cases — 144/144 total tests green

## Task Commits

Each task was committed atomically:

1. **Task 1: GET, PATCH, DELETE /v1/memory endpoints + GET /v1/memory/{id}/entities** - `68e6a43` (feat)
2. **Task 2: Integration tests for memory read, update, delete, and entity retrieval** - `c97e1ff` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `app/routers/memory.py` - Added 5 route handlers: list, entities, get, patch, delete; updated imports
- `tests/test_memory_read.py` - 26 integration tests for all new endpoints

## Decisions Made

- **Entity retrieval uses relations table, not memory_entities:** The plan referenced a `memory_entities` join table that does not exist in the actual schema. The tenant schema uses `relations.memory_id` to link entity pairs to memories. Entity endpoint derives entity list from distinct source/target IDs in relations for the memory. This matches what `process_entities_for_memory` actually stores.

- **Entities endpoint returns only relation-linked entities:** Only entities that appear as source or target in a relation for this memory are returned. Standalone entities without relations would not appear — but per the schema design, all entity extraction produces relations or skips storage, so this is correct.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used relations table instead of non-existent memory_entities join table**
- **Found during:** Task 1 (GET /v1/memory/{id}/entities implementation)
- **Issue:** Plan's entity query referenced `JOIN memory_entities me ON e.id = me.entity_id` — the `memory_entities` table does not exist in `app/db/tenant.py` schema. The actual schema links entities to memories via `relations.memory_id`.
- **Fix:** Entity endpoint queries `relations WHERE memory_id = ?`, joins both `entities` tables for source/target names, then fetches unique entity details by ID set collected from relations.
- **Files modified:** app/routers/memory.py
- **Verification:** test_get_entities_with_data inserts entities + relation directly and verifies both are returned; 26/26 tests pass.
- **Committed in:** 68e6a43 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in plan's assumed schema)
**Impact on plan:** Essential fix — plan would have produced a runtime error. Actual behavior matches intent (return entities linked to a memory). No scope creep.

## Issues Encountered

None — schema discrepancy identified during pre-implementation review and corrected before writing code.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Full CRUD surface complete: POST (02-03) + GET list + GET by id + GET entities + PATCH + DELETE
- Entity graph queryable via GET /v1/memory/{id}/entities (RETR-03 satisfied)
- 02-05 can now implement search with confidence that memories are manageable end-to-end
- No blockers

---
*Phase: 02-core-memory-api*
*Completed: 2026-03-14*

## Self-Check: PASSED

- app/routers/memory.py: FOUND
- tests/test_memory_read.py: FOUND
- 02-04-SUMMARY.md: FOUND
- Commit 68e6a43 (Task 1): FOUND
- Commit c97e1ff (Task 2): FOUND
