---
phase: 02-core-memory-api
plan: 01
subsystem: api
tags: [dedup, decay, entity-extraction, fastapi, pydantic, aiosqlite, numpy]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: TenantDBManager, init_tenant_db, get_tenant_by_key_hash, init_system_db
provides:
  - text_hash dedup (SHA-256, 32-char) + cosine similarity dedup
  - temporal decay scoring (30-day half-life, 80/20 blend)
  - regex entity extraction (person, org, location, date, topic) + relation extraction
  - find_or_create_entity + process_entities_for_memory DB persistence
  - FastAPI get_tenant + get_tenant_conn dependency injection
  - Pydantic v2 memory models (MemoryCreate, MemoryResponse, MemoryUpdate, MemorySearchRequest, MemorySearchResponse, MemoryListResponse)
  - config vars (FIREWORKS_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM, VECTOR_INDEX_DIR, MAX_VECTOR_INDEXES)
affects: [02-03-memory-crud, 02-04-search, 02-05-entity-graph, all memory endpoint plans]

# Tech tracking
tech-stack:
  added: [numpy (cosine similarity), hashlib, re (regex entity patterns), aiosqlite (entity/relation DB writes)]
  patterns:
    - "Dedup-before-persist: text_hash checked before any DB write to block exact duplicates"
    - "80/20 decay blend: 80% base score + 20% recency bonus decays with 30-day half-life"
    - "Priority-ordered entity extraction: org > date > standalone location > location-in > person > topic (prevents overlap misclassification)"
    - "Starlette TestClient with portal.call() for sync tests that need async DB setup"

key-files:
  created:
    - app/services/dedup.py
    - app/services/decay.py
    - app/services/entity_extraction.py
    - app/deps.py
    - app/models/memory.py
    - tests/test_dedup.py
    - tests/test_decay.py
    - tests/test_entity_extraction.py
    - tests/test_deps.py
  modified:
    - app/config.py (added FIREWORKS_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM, VECTOR_INDEX_DIR, MAX_VECTOR_INDEXES)
    - app/main.py (added get_tenant import, /_test/tenant endpoint for dep injection testing)

key-decisions:
  - "Priority-ordered entity extraction (org > date > standalone location > location-in > person): single-word capitalized names like Alice match person pattern but also org suffixes and date months — execution order prevents misclassification"
  - "Starlette TestClient (not httpx AsyncClient) for deps tests: httpx ASGITransport only sends http ASGI scopes, never lifespan scope — TestClient properly triggers startup/shutdown"
  - "/_test/tenant endpoint added to main.py: enables deps testing without a dedicated memory endpoint; returns id/email/plan only"

patterns-established:
  - "Overlap tracking in extract_entities: claimed set prevents lower-priority patterns from re-capturing spans already classified"
  - "find_or_create_entity idempotency: name_normalized + entity_type lookup before insert; increments mention_count on re-find"
  - "get_tenant dependency: always SHA-256 hashes raw key before DB lookup — raw key never stored or logged"

# Metrics
duration: 13min
completed: 2026-03-14
---

# Phase 02 Plan 01: Core Service Modules Summary

**SHA-256 dedup, 30-day exponential decay, regex entity/relation extraction, FastAPI Bearer auth dependency, and Pydantic v2 memory models — 105/105 tests passing**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-03-14T00:06:29Z
- **Completed:** 2026-03-14T00:19:41Z
- **Tasks:** 2
- **Files modified:** 10 (6 created, 4 modified)

## Accomplishments

- 4 service modules built: dedup (text_hash + cosine check), decay (80/20 blend, 30-day half-life), entity extraction (person/org/location/date/topic + 7 relation patterns), and DB persistence helpers
- FastAPI dependency injection for tenant resolution via Bearer API key hashing + system DB lookup
- Pydantic v2 models for all memory endpoint shapes (create, response, update, search, list)
- 48 new tests covering all modules; 105/105 total tests pass

## Task Commits

1. **Task 1: Services + deps + models** - `10e37dc` (feat)
2. **Task 2: Tests** - `c8630df` (test)

## Files Created/Modified

- `app/services/dedup.py` - text_hash (SHA-256), check_exact_duplicate, check_cosine_duplicate
- `app/services/decay.py` - apply_decay, decay_factor, DECAY_HALF_LIFE_DAYS=30
- `app/services/entity_extraction.py` - extract_entities, extract_relations, find_or_create_entity, process_entities_for_memory
- `app/deps.py` - get_tenant (Bearer→tenant dict), get_tenant_conn (LRU pool connection)
- `app/models/memory.py` - MemoryCreate, MemoryResponse, MemoryUpdate, MemorySearchRequest, MemorySearchResult, MemorySearchResponse, MemoryListResponse
- `app/config.py` - added FIREWORKS_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIM, VECTOR_INDEX_DIR, MAX_VECTOR_INDEXES
- `app/main.py` - added get_tenant import + /_test/tenant test helper endpoint
- `tests/test_dedup.py` - 14 tests
- `tests/test_decay.py` - 8 tests
- `tests/test_entity_extraction.py` - 22 tests
- `tests/test_deps.py` - 6 tests

## Decisions Made

- **Priority-ordered entity extraction:** Organizations are extracted first, then dates (to prevent month names like "January" matching as persons), then standalone locations, then preposition-anchored locations, then persons last. This prevents single capitalized words from being misclassified.
- **Starlette TestClient for deps tests:** httpx's ASGITransport only dispatches `http` ASGI scopes — the lifespan `startup`/`shutdown` scopes are never sent. TestClient properly manages the app lifespan and provides `portal.call()` for async DB operations in sync test context.
- **/_test/tenant endpoint in main.py:** Added as a permanent test helper that exercises `Depends(get_tenant)`. Returns only id/email/plan — no sensitive data. Harmless in production until real memory endpoints exist.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Entity extraction pattern priority ordering**
- **Found during:** Task 1 verification
- **Issue:** Single capitalized words (person names like "Alice") were being matched by person pattern, but month names ("January") and org names ("Google Inc") were also matching person pattern — causing misclassification
- **Fix:** Restructured `extract_entities` to run patterns in priority order (org → date → standalone location → location-in → person → topic) with a `claimed` span set that prevents lower-priority patterns from overlapping higher-priority matches
- **Files modified:** app/services/entity_extraction.py
- **Verification:** "Alice works at Google Inc in New York" → 3+ correct entities (person:Alice, org:Google Inc, location:New York); "January 15, 2024" → date entity not person
- **Committed in:** 10e37dc (Task 1 commit)

**2. [Rule 3 - Blocking] Used Starlette TestClient instead of httpx AsyncClient for deps tests**
- **Found during:** Task 2 (test_deps.py implementation)
- **Issue:** httpx `ASGITransport` does not send ASGI `lifespan` scope — only `http` scope. The FastAPI lifespan (which populates `app.state.system_db`) never runs with ASGITransport. Tests requiring `app.state.system_db` failed with `AttributeError`.
- **Fix:** Replaced httpx `AsyncClient` approach with Starlette `TestClient` which uses `anyio.from_thread` to properly trigger ASGI lifespan. Used `client.portal.call()` for async DB seed operations.
- **Files modified:** tests/test_deps.py
- **Verification:** All 6 deps tests pass including valid key resolution, inactive key rejection, suspended tenant rejection
- **Committed in:** c8630df (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 blocking issue)
**Impact on plan:** Both fixes required for correctness. No scope creep — plan deliverables met exactly.

## Issues Encountered

None beyond the two auto-fixed deviations above.

## Next Phase Readiness

- All service modules ready for composition into memory endpoints (02-03 through 02-05)
- `get_tenant` and `get_tenant_conn` dependencies ready for use in all protected routes
- Pydantic models ready for request/response validation in all memory endpoints
- Entity extraction ready for background processing after memory insert

---
*Phase: 02-core-memory-api*
*Completed: 2026-03-14*
