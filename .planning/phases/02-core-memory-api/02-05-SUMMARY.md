---
phase: 02-core-memory-api
plan: 05
subsystem: api
tags: [fastapi, hnswlib, sqlite, search, vector-search, temporal-decay, rate-limiting]

# Dependency graph
requires:
  - phase: 02-02
    provides: TenantIndexManager.search with candidate_ids filtering
  - phase: 02-03
    provides: EmbeddingClient.embed_single, limiter module, POST /v1/memory
  - phase: 02-04
    provides: entity extraction + GET /v1/memory/{id}/entities endpoint
provides:
  - app/services/search.py — metadata-first hybrid search orchestrator with AND/OR metadata filtering, vector ANN search, temporal decay, recency fallback
  - POST /v1/memory/search — rate-limited semantic search endpoint (120/min)
  - count_tenant_memories helper for DX-05 memories_used field
  - 18 integration tests covering all search behaviors end-to-end
affects: [03-auth-and-billing, 04-retrieval-intelligence, 05-self-improvement]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Metadata-first search (RETR-05): SQL candidate filtering before vector ANN search reduces index scan scope
    - AND/OR metadata filter logic via parameterized json_extract SQL conditions
    - Recency fallback: return candidates sorted by created_at DESC when embedding client circuit breaker is open
    - Mock embedding in tests via AsyncMock on app.state.embedding_client.embed_single

key-files:
  created:
    - app/services/search.py
    - tests/test_memory_search.py
  modified:
    - app/models/memory.py
    - app/routers/memory.py

key-decisions:
  - "metadata_filter_operator AND/OR logic applied via parameterized json_extract in SQL WHERE clause — no post-filter needed"
  - "Recency fallback returns candidates sorted by created_at DESC (not empty list) when embedding client is unavailable"
  - "POST /v1/memory/search registered before GET /memory/{memory_id} — HTTP method difference prevents collision but explicit ordering is defensive"
  - "Test embeddings seeded with deterministic np.random.RandomState, noisy variants via abs+mod uint32 seed derivation"

patterns-established:
  - "Metadata-first pattern: build SQL candidate set, then pass candidate_ids to index_manager.search — cheaper than full ANN scan"
  - "Search fallback pattern: check query_embedding is None, sort candidates by created_at DESC, return with score=0.0"

# Metrics
duration: 4min
completed: 2026-03-14
---

# Phase 2 Plan 05: Semantic Search — Summary

**Metadata-first hybrid search with AND/OR filtering, vector ANN scoring, temporal decay, and recency fallback — completing the core memory API (162/162 tests pass)**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-14T16:53:56Z
- **Completed:** 2026-03-14T16:58:05Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Built `app/services/search.py` search orchestrator implementing the metadata-first pattern (RETR-05): SQL candidate set → ANN vector search → temporal decay scoring
- Added `metadata_filter_operator: "and" | "or"` to `MemorySearchRequest` (MEM-03), enabling both AND (all conditions) and OR (any condition) metadata filter logic via parameterized `json_extract` SQL clauses
- Wired `POST /v1/memory/search` endpoint with `@limiter.limit("120/minute")` (MEM-12), returning `MemorySearchResponse` with `memories_used`/`memories_limit` (DX-05) and usage logging
- Implemented recency fallback: when `embed_single` returns `None` (circuit breaker open), returns candidates sorted by `created_at DESC` with `score=0.0` — never returns empty on embedding failure
- Wrote 18 integration tests covering every success criterion including the entity-extraction → search e2e pipeline

## Task Commits

1. **Task 1: Search service and POST /v1/memory/search endpoint** - `7420f67` (feat)
2. **Task 2: Integration tests for memory search** - `cb79891` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `app/services/search.py` — Hybrid search orchestrator: metadata SQL filtering, vector ANN, decay scoring, recency fallback, count_tenant_memories helper
- `app/models/memory.py` — Added `metadata_filter_operator: Literal["and", "or"]` to `MemorySearchRequest`
- `app/routers/memory.py` — Added `POST /v1/memory/search` endpoint with rate limiting, imports for search service and models
- `tests/test_memory_search.py` — 18 integration tests for all search behaviors

## Decisions Made
- `metadata_filter_operator` implemented via parameterized `json_extract` SQL conditions — keeps filtering in DB, no post-processing needed, clean SQL injection prevention via `?` params
- Recency fallback returns non-empty results (sorted by `created_at DESC`) rather than empty list, preserving usefulness under embedding client outages
- `POST /v1/memory/search` uses POST to allow structured request body; HTTP method difference from `GET /memory/{memory_id}` eliminates routing collision risk entirely

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `_noisy_embedding` seed overflow causing `ValueError`**
- **Found during:** Task 2 (integration tests)
- **Issue:** `int(np.sum(base * 1000))` can produce negative values or values exceeding 2**32 for unit-normalized 1024-dim vectors, causing `ValueError: Seed must be between 0 and 2**32 - 1` in `np.random.RandomState`
- **Fix:** Changed to `int(abs(np.sum(base * 1000))) % (2**32)` — clamps to valid uint32 range deterministically
- **Files modified:** `tests/test_memory_search.py`
- **Verification:** All 9 previously failing tests now pass after fix
- **Committed in:** `cb79891` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test helper)
**Impact on plan:** Auto-fix required for tests to run. No scope creep — fix was a 1-line change in test utility function.

## Issues Encountered
None — plan executed cleanly after the test helper bug fix.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Core Memory API (Phase 2) is now complete: all 5 plans done, 162/162 tests pass
- Search endpoint is production-ready: metadata filtering, vector similarity, temporal decay, rate limiting, usage logging, quota responses
- Phase 3 (Auth and Billing) can proceed — the full CRUD + search surface area is stable
- Phase 4 (Retrieval Intelligence) can build on this search foundation to add Q-learning, BM25 hybrid scoring, feedback loops

---
*Phase: 02-core-memory-api*
*Completed: 2026-03-14*
