---
phase: 05-self-improving-memory
plan: 02
subsystem: api
tags: [q-learning, bandit-routing, sqlite, fastapi, pydantic, aiosqlite]

# Dependency graph
requires:
  - phase: 05-01
    provides: retrieval_log table, retrieval_feedback service, search pipeline with Step 8 logging
provides:
  - Q-learning bandit router (app/services/q_router.py) with compute_reward, update_q_value, select_strategy, get_router_stats
  - retrieval_q_table DDL in TENANT_SCHEMA_SQL (schema_version 3)
  - GET /v1/intelligence/router/stats endpoint returning RouterStats JSON
  - Q-router wired into search pipeline (Step 9) at both main and fallback paths
  - Pydantic v2 models QTableEntry and RouterStats in app/models/intelligence.py
  - 13 tests in tests/test_q_router.py covering all router behaviors
affects: [05-03, 05-04, future-phases-using-intelligence-endpoint]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Q-learning bandit: ALPHA=0.2 learning rate, EPSILON=0.15 exploration, ACTIVATION_THRESHOLD=30 visits before routing
    - Proxy reward without explicit feedback: 0.4*count_component + 0.6*avg_score
    - Feedback loop closure: select_strategy() called before compute_reward, strategy name passed to update_q_value
    - Router stats endpoint follows memory.py pattern: get_tenant dep, log_usage, response_model

key-files:
  created:
    - app/services/q_router.py
    - app/models/intelligence.py
    - app/routers/intelligence.py
    - tests/test_q_router.py
  modified:
    - app/db/tenant.py
    - app/services/search.py
    - app/main.py

key-decisions:
  - "05-02 — select_strategy() called before compute_reward: strategy name flows to update_q_value, closing the feedback loop — without this, all rewards accumulate under hardcoded 'default' and Q-table never differentiates strategies"
  - "05-02 — ACTIVATION_THRESHOLD=30: prevents noise-driven routing for sparse tenant DBs; returns 'default' until statistically meaningful observations accumulate"
  - "05-02 — EPSILON=0.15 (vs ZimMemory 0.1): higher exploration rate for SaaS diversity across heterogeneous tenant workloads"
  - "05-02 — Proxy reward (count + avg_score): no explicit user feedback required; observable retrieval signals drive Q-learning"
  - "05-02 — Step 9 in both main and fallback search paths: Q-table accumulates even when embedding service is down"

patterns-established:
  - "Intelligence router: separate APIRouter at /v1/intelligence prefix, registered after memory_router in main.py"
  - "Q-router failure isolation: try/except around all Q-router calls in search.py — Q-update failures never degrade search availability"

# Metrics
duration: 5min
completed: 2026-03-14
---

# Phase 5 Plan 02: Q-Learning Bandit Router Summary

**Epsilon-greedy Q-learning router with 30-visit activation threshold, proxy reward signal, and /v1/intelligence/router/stats endpoint — 227 tests passing**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-14T19:09:53Z
- **Completed:** 2026-03-14T19:15:13Z
- **Tasks:** 2
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- Q-learning bandit router with epsilon-greedy selection, ALPHA=0.2, EPSILON=0.15, ACTIVATION_THRESHOLD=30
- Feedback loop closed: `select_strategy()` called per search, strategy name passed to `update_q_value()` — Q-table tracks which strategy was active when reward was observed
- GET /v1/intelligence/router/stats exposes Q-table state with activation status, authenticated, 30/minute rate limit
- 13 new tests covering compute_reward correctness, Q-value convergence, activation threshold, strategy selection stats, endpoint auth, and feedback loop closure

## Task Commits

1. **Task 1: Q-table DDL, Q-learning router, intelligence models** - `075f985` (feat)
2. **Task 2: Wire Q-router into search, add intelligence API, add tests** - `7fe942c` (feat)

## Files Created/Modified
- `app/services/q_router.py` - Q-learning bandit: compute_reward, update_q_value, select_strategy, get_router_stats
- `app/models/intelligence.py` - QTableEntry and RouterStats Pydantic v2 models
- `app/routers/intelligence.py` - GET /v1/intelligence/router/stats endpoint
- `tests/test_q_router.py` - 13 tests, all passing
- `app/db/tenant.py` - Added retrieval_q_table DDL + schema_version 3
- `app/services/search.py` - Added Step 9 Q-router update in both main and fallback paths
- `app/main.py` - Registered intelligence_router, added intelligence openapi_tags entry

## Decisions Made
- `select_strategy()` called BEFORE `compute_reward()` — strategy name flows through to `update_q_value()`, closing the feedback loop. Without this ordering, all Q-values accumulate under the strategy that happened to be active, not the one that caused the reward.
- ACTIVATION_THRESHOLD=30 keeps Q-router dormant during sparse early usage; returns "default" until meaningful data accumulates.
- Proxy reward (0.4 * count_normalized + 0.6 * avg_score) requires no explicit user signals — observable retrieval outcomes drive learning from day one.
- Step 9 added to both main path and fallback path — Q-table accumulates even during Fireworks.ai outages.

## Deviations from Plan

None — plan executed exactly as written. The linter added confidence scoring (from a prior plan) to search.py automatically; our Q-router additions were independent and required no conflict resolution.

## Issues Encountered
- Full test suite showed 1 failure on first run (`test_detect_gaps_finds_missing_entity`) due to test ordering state contamination between TestClient contexts. Second run: 227/227 pass. Pre-existing issue unrelated to 05-02 changes.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- Q-table accumulates per-strategy Q-values from day one (search calls Step 9)
- Router stats endpoint available for observability and debugging
- Q-values below activation threshold until 30 visits/pair — safe to deploy immediately
- Ready for Phase 5 Plan 03 (knowledge gap detection) and Plan 04 (convergence tracking / adaptive limits)

---
*Phase: 05-self-improving-memory*
*Completed: 2026-03-14*

## Self-Check: PASSED

- app/services/q_router.py: FOUND
- app/models/intelligence.py: FOUND
- app/routers/intelligence.py: FOUND
- tests/test_q_router.py: FOUND
- Commit 075f985: FOUND
- Commit 7fe942c: FOUND
