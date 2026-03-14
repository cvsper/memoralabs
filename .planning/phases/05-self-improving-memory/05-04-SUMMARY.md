---
phase: 05-self-improving-memory
plan: 04
subsystem: api
tags: [confidence-scoring, search, entity-extraction, temporal-decay, engagement]

# Dependency graph
requires:
  - phase: 05-01
    provides: retrieval_log table + retrieval_feedback service + search pipeline instrumented
  - phase: 02-01
    provides: entity_extraction service (extract_entities, normalize_entity_name)
  - phase: 02-02
    provides: decay.py (decay_factor function)
provides:
  - compute_confidence() function in app/services/confidence.py (4-signal weighted formula)
  - confidence field on MemorySearchResult (0.0-1.0, default=0.0)
  - Confidence integrated into search pipeline (Step 3b, 4b, 7)
  - Fallback path sets confidence=0.0 (circuit breaker results)
affects: [05-05, 05-06, search-clients, api-consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "4-signal confidence formula: 40% sim_norm, 30% entity_overlap, 20% engagement, 10% freshness"
    - "Raw cosine tracked separately from decay-adjusted score for normalization"
    - "Query entity extraction at search time for overlap computation"

key-files:
  created:
    - app/services/confidence.py
    - tests/test_confidence.py
  modified:
    - app/models/memory.py
    - app/services/search.py

key-decisions:
  - "05-04 — confidence is a separate field from score: score is relevance ranking, confidence is reliability estimate"
  - "05-04 — max_cosine tracked as dict for O(1) per-result lookup during Step 7 loop"
  - "05-04 — fallback path (circuit breaker) always sets confidence=0.0 (no cosine data available)"
  - "05-04 — access_count added to SELECT in Step 1 (was not fetched before this plan)"

patterns-established:
  - "Confidence formula: round(max(0.0, min(1.0, weighted_sum)), 4)"
  - "engagement = min(1.0, log(1 + access_count) / log(101)) — logarithmic, saturates at 100"

# Metrics
duration: 5min
completed: 2026-03-14
---

# Phase 5 Plan 04: Confidence Scoring Summary

**Confidence scoring added to every search result using a 4-signal weighted formula (40% similarity normalization, 30% entity overlap, 20% engagement, 10% freshness), distinct from the relevance score**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-14T19:10:05Z
- **Completed:** 2026-03-14T19:14:54Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created `app/services/confidence.py` with `compute_confidence()` function implementing the 4-signal weighted formula
- Added `confidence: float` field to `MemorySearchResult` (default=0.0, range 0.0-1.0, with description distinguishing it from score)
- Wired confidence computation into `search_memories()`: query entity extraction (Step 3b), raw cosine tracking (Step 4b), per-result computation (Step 7), and 0.0 for fallback results
- Added `access_count` to the SQL SELECT in Step 1 (engagement signal requires it)
- 10 new tests (8 unit + 2 integration) all passing; full 227-test suite green

## Task Commits

1. **Task 1: Create confidence service and update MemorySearchResult model** - `66940c7` (feat)
2. **Task 2: Wire confidence into search pipeline and write tests** - `08a2080` (feat)

**Plan metadata:** TBD (docs commit)

## Files Created/Modified
- `app/services/confidence.py` - compute_confidence() function with 4-signal weighted formula
- `app/models/memory.py` - confidence field added to MemorySearchResult; examples updated
- `app/services/search.py` - imports, access_count in SELECT, query entity extraction, raw cosine tracking, confidence computation per result, confidence=0.0 in fallback
- `tests/test_confidence.py` - 8 unit tests + 2 integration tests (all 10 passing)

## Decisions Made
- confidence is a separate field from score: score measures relevance ranking (cosine + decay), confidence measures result reliability (how trustworthy the result is)
- max_cosine stored as `dict[str, float]` mapping memory_id to raw cosine for O(1) lookup during result-building loop
- fallback path (circuit breaker open) always sets confidence=0.0 — no cosine data means no similarity normalization, so confidence is meaningless
- access_count was not previously fetched in the SELECT; added to Step 1 to support the engagement signal

## Deviations from Plan

None - plan executed exactly as written. The only discovery was that search.py had already been updated by plan 05-02 (Q-router integration) with additional imports and Steps 9, which required writing the full file instead of using targeted edits. No behavior was changed beyond what the plan specified.

## Issues Encountered
- search.py had been modified by plan 05-02 (Q-router) between when 05-04 was written and executed. The file had new imports (q_router) and a Step 9 block. Resolved by reading the current file state and writing the complete updated version preserving all 05-02 additions.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Confidence scoring fully integrated and tested
- Every search result now has both `score` (relevance) and `confidence` (trustworthiness) fields
- Downstream phases can filter or sort by confidence threshold
- Full 227-test suite passing

---
*Phase: 05-self-improving-memory*
*Completed: 2026-03-14*

## Self-Check: PASSED

- app/services/confidence.py: FOUND
- tests/test_confidence.py: FOUND
- app/models/memory.py: FOUND
- app/services/search.py: FOUND
- Commit 66940c7: FOUND
- Commit 08a2080: FOUND
