---
phase: 05-self-improving-memory
plan: 01
subsystem: database
tags: [sqlite, aiosqlite, retrieval-logging, feedback, q-learning, search]

# Dependency graph
requires:
  - phase: 02-core-memory-api
    provides: search_memories() in app/services/search.py and text_hash() in dedup.py
  - phase: 01-foundation
    provides: init_tenant_db() and TENANT_SCHEMA_SQL in app/db/tenant.py
provides:
  - retrieval_log table in every tenant SQLite DB (per-tenant isolated)
  - log_retrieval() — async INSERT of query/result_ids/scores/strategy/hit into retrieval_log
  - get_feedback_stats() — diagnostic aggregation over retrieval_log window
  - Search pipeline instrumented — every search call (vector + fallback paths) writes a row
affects:
  - 05-02 (Q-learning router — depends on retrieval_log for reward signal)
  - 05-03 (knowledge gap detector — queries retrieval_log for coverage gaps)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - fire-and-forget feedback INSERT wrapped in try/except at search call site
    - text_hash() reuse for query normalization (no hand-rolled hashing)
    - per-tenant schema version tracked via INSERT OR IGNORE into schema_version

key-files:
  created:
    - app/services/retrieval_feedback.py
    - tests/test_retrieval_feedback.py
  modified:
    - app/db/tenant.py
    - app/services/search.py

key-decisions:
  - "05-01 — log_retrieval uses text_hash() from dedup.py: reuses existing SHA-256 normalization, no hand-rolled hash"
  - "05-01 — Both vector and fallback search paths log feedback: fallback path uses strategy='fallback' to distinguish recency-sort retrievals"
  - "05-01 — Feedback logging wrapped in try/except at both call sites: logging failure must never degrade search reliability"
  - "05-01 — schema_version v2 added via INSERT OR IGNORE: idempotent migration tracking for 005_retrieval_log"

patterns-established:
  - "Feedback logging pattern: try/except around await log_retrieval() inline in hot path — sub-millisecond SQLite INSERT is acceptable latency"
  - "Strategy label pattern: pass strategy string to log_retrieval to distinguish search paths for Q-learning router"

# Metrics
duration: 3min
completed: 2026-03-14
---

# Phase 05 Plan 01: Retrieval Feedback Logging Summary

**Per-tenant retrieval_log table with log_retrieval()/get_feedback_stats() service and search pipeline instrumentation creating the training signal for Q-learning and knowledge gap detection**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-14T19:04:20Z
- **Completed:** 2026-03-14T19:07:20Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- retrieval_log table added to TENANT_SCHEMA_SQL with created_at and query_hash indexes
- app/services/retrieval_feedback.py with log_retrieval() (UUID, text_hash, JSON arrays) and get_feedback_stats() (30-day window aggregation)
- Both vector search and recency fallback paths in search_memories() now call log_retrieval(), wrapped in try/except
- 7 tests covering unit (log_retrieval, get_feedback_stats) and integration (search endpoint writes row)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add retrieval_log DDL and create retrieval_feedback service** - `f080da9` (feat)
2. **Task 2: Wire feedback logging into search pipeline and write tests** - `548e591` (feat)

**Plan metadata:** to be committed with SUMMARY.md

## Files Created/Modified
- `app/db/tenant.py` - Added retrieval_log DDL, two indexes, schema_version v2 INSERT
- `app/services/retrieval_feedback.py` - New: log_retrieval() and get_feedback_stats() async functions
- `app/services/search.py` - Import log_retrieval; call it after Step 7 and in fallback path
- `tests/test_retrieval_feedback.py` - New: 7 tests for the service and e2e endpoint logging

## Decisions Made
- log_retrieval reuses text_hash() from dedup.py — same SHA-256 normalization (strip+lowercase), no redundant hashing utility
- Fallback (recency sort) path logs with strategy="fallback" to allow Q-learning router to weight these outcomes differently
- Logging is inline await (not background task) — a single SQLite INSERT is sub-millisecond and within acceptable hot-path budget

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- retrieval_log table is created on every new tenant DB init and populated on every search
- 196/196 tests pass — ready to build Q-learning router (05-02) on top of this data
- get_feedback_stats() diagnostic endpoint ready for 05-02 to expose as admin API

---
*Phase: 05-self-improving-memory*
*Completed: 2026-03-14*

## Self-Check: PASSED

- FOUND: app/services/retrieval_feedback.py
- FOUND: tests/test_retrieval_feedback.py
- FOUND: .planning/phases/05-self-improving-memory/05-01-SUMMARY.md
- FOUND: commit f080da9 (Task 1)
- FOUND: commit 548e591 (Task 2)
