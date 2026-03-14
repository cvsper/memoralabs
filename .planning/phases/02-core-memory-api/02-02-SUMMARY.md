---
phase: 02-core-memory-api
plan: 02
subsystem: api
tags: [hnswlib, numpy, slowapi, httpx, fireworks-ai, vector-search, circuit-breaker, rate-limiting]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: FastAPI app, config, TenantDBManager, aiosqlite connections

provides:
  - EmbeddingClient with async Fireworks.ai batching and circuit breaker
  - TenantIndexManager with per-tenant hnswlib LRU cache and disk persistence
  - slowapi Limiter wired into FastAPI app with tenant-aware key function

affects:
  - 02-03-memory-crud (imports EmbeddingClient, TenantIndexManager, limiter)
  - 02-05-search (imports limiter for @limiter.limit decorator)

# Tech tracking
tech-stack:
  added:
    - hnswlib>=0.8.0 (C++ HNSW vector index with Python bindings)
    - numpy>=1.26.0 (vector math, float32 array handling)
    - slowapi>=0.1.9 (FastAPI rate limiting with custom key functions)
  patterns:
    - Circuit breaker: 3 consecutive failures trip breaker, 120s cooldown auto-recovery
    - LRU cache with OrderedDict for both TenantDBManager (connections) and TenantIndexManager (indexes)
    - asyncio.Lock guards all hnswlib mutations (hnswlib is NOT thread-safe)
    - run_in_executor wraps synchronous C++ hnswlib I/O (save/load) to avoid blocking event loop
    - Per-tenant rate limiting via SHA-256(Bearer token)[:16] as key function

key-files:
  created:
    - app/services/__init__.py
    - app/services/embedding.py
    - app/services/vector_index.py
    - tests/test_embedding.py
    - tests/test_vector_index.py
  modified:
    - app/config.py (FIREWORKS_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM, VECTOR_INDEX_DIR, MAX_VECTOR_INDEXES)
    - app/main.py (slowapi Limiter, EmbeddingClient + TenantIndexManager in lifespan)
    - requirements.txt (hnswlib, numpy, slowapi)

key-decisions:
  - "hnswlib RuntimeError on knn_query with all-deleted results is caught and returns [] rather than propagating"
  - "Per-tenant index files use .idx (hnswlib binary) + .ids.json (position-to-UUID map) under VECTOR_INDEX_DIR"
  - "Circuit breaker resets consecutive_failures to 0 on any fully successful embed() call"
  - "Rate limit key is SHA-256(Bearer token)[:16] — raw API key never stored in rate limiter memory"
  - "INITIAL_MAX_ELEMENTS=10000 per tenant index, resize at 80% capacity using 2x growth factor"

patterns-established:
  - "LRU cache pattern: OrderedDict + move_to_end on hit + popitem(last=False) on evict (matches TenantDBManager)"
  - "Lock duplication: add_vector/search/remove_vector each acquire lock and handle miss inline (avoid nested lock waits)"
  - "Disk I/O in executor: loop.run_in_executor(None, sync_fn, *args) for all hnswlib save/load operations"

# Metrics
duration: 5min
completed: 2026-03-14
---

# Phase 2 Plan 2: Embedding Client, Vector Index, and Rate Limiting Summary

**Async Fireworks.ai EmbeddingClient with 3-failure circuit breaker, per-tenant hnswlib TenantIndexManager with LRU eviction and disk persistence, and slowapi Limiter wired into FastAPI with SHA-256 tenant key function**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-14T16:26:29Z
- **Completed:** 2026-03-14T16:31:48Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- EmbeddingClient: async batched POST to Fireworks.ai, circuit breaker (3 failures → 120s cooldown → auto-recover), embed/embed_single/close/is_available
- TenantIndexManager: per-tenant .idx + .ids.json files, OrderedDict LRU cache (max 20 tenants), add_vector/search/remove_vector/save_all/close, asyncio.Lock on all mutations, hnswlib I/O in executor
- slowapi Limiter: get_tenant_key hashes Bearer token with SHA-256, registered on app.state + exception handler, importable from app.main for route decorators in plans 02-03 and 02-05
- 57/57 tests passing (37 existing + 20 new)

## Task Commits

Each task was committed atomically:

1. **Task 1: Embedding client, vector index manager, and rate limiting infrastructure** - `72855f1` (feat)
2. **Task 2: Tests for embedding client and vector index manager** - `e5b506e` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `app/services/__init__.py` - Services package marker
- `app/services/embedding.py` - EmbeddingClient with circuit breaker and async httpx batching
- `app/services/vector_index.py` - TenantIndexManager with hnswlib LRU cache, disk persistence, asyncio.Lock
- `app/config.py` - Added FIREWORKS_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM, VECTOR_INDEX_DIR, MAX_VECTOR_INDEXES
- `app/main.py` - Added slowapi Limiter, get_tenant_key, EmbeddingClient + TenantIndexManager in lifespan
- `requirements.txt` - Added hnswlib>=0.8.0, numpy>=1.26.0, slowapi>=0.1.9
- `tests/test_embedding.py` - 10 tests: success, no key, 429, breaker recovery, timeout, connect error, batching
- `tests/test_vector_index.py` - 10 tests: create, add+search, top-k, empty, filter, remove, persist, LRU, resize, concurrent

## Decisions Made

- hnswlib RuntimeError when knn_query can't form contiguous results (all deleted) caught and returns [] rather than raising to caller.
- Per-tenant index files at VECTOR_INDEX_DIR/{tenant_id}.idx and .ids.json — matches DATA_DIR/tenants/{tenant_id}.db pattern from Phase 1.
- Rate limit key uses SHA-256 of Bearer token, not the raw key, so API keys are never stored in slowapi's in-memory store.
- INITIAL_MAX_ELEMENTS=10,000 per tenant (generous headroom for free plan's 1,000 memory limit), grows 2x at 80% fill.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Caught hnswlib RuntimeError on knn_query when all vectors are deleted**
- **Found during:** Task 2 (test_remove_vector test)
- **Issue:** After mark_deleted, hnswlib raises RuntimeError "Cannot return the results in a contiguous 2D array" when fetch_k exceeds the number of non-deleted elements. Plan did not account for this hnswlib behavior.
- **Fix:** Wrapped knn_query in try/except RuntimeError returning [] — matches the intent (no results found) without crashing.
- **Files modified:** app/services/vector_index.py
- **Verification:** test_remove_vector passes, all 57 tests pass
- **Committed in:** e5b506e (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential correctness fix — search would crash on any tenant that removes their only vector.

## Issues Encountered

None beyond the hnswlib RuntimeError documented above.

## User Setup Required

None — no external service configuration required. FIREWORKS_API_KEY is optional at startup; EmbeddingClient returns None from embed() when no key is set.

## Next Phase Readiness

- EmbeddingClient ready for use in POST /v1/memory background tasks (Plan 02-03)
- TenantIndexManager ready for add_vector in background embedding tasks and search in Plan 02-05
- limiter importable from app.main — route decorators (@limiter.limit("60/minute")) can be applied immediately
- All 57 tests passing, no regressions

## Self-Check: PASSED

- app/services/embedding.py — FOUND
- app/services/vector_index.py — FOUND
- tests/test_embedding.py — FOUND
- tests/test_vector_index.py — FOUND
- 02-02-SUMMARY.md — FOUND
- Commit 72855f1 — FOUND
- Commit e5b506e — FOUND

---
*Phase: 02-core-memory-api*
*Completed: 2026-03-14*
