---
phase: 05-self-improving-memory
plan: 03
subsystem: api
tags: [fastapi, pydantic, sqlite, entity-extraction, gap-detection]

requires:
  - phase: 05-01
    provides: retrieval_log table with query history for window-based scanning
  - phase: 02-01
    provides: extract_entities() and normalize_entity_name() functions from entity_extraction.py

provides:
  - detect_knowledge_gaps() async service — scans retrieval_log, extracts entities, diffs against entities table
  - POST /v1/memory/gaps endpoint — returns GapDetectionResponse with gaps, total, window_days, queries_analyzed
  - KnowledgeGap, GapDetectionRequest, GapDetectionResponse Pydantic models in intelligence.py
  - 8 tests covering all gap detection behavior

affects: [05-04, any plan consuming intelligence endpoints or gap data]

tech-stack:
  added: []
  patterns:
    - "Gap detection is on-demand only — never inline during search, only via explicit API call"
    - "Short query skip (< 5 words) prevents false positives from regex entity extractor"
    - "Reuse existing extract_entities()/normalize_entity_name() — no new NLP pipeline"
    - "Gap endpoint on memory router (/v1/memory/gaps) for correct URL path, tagged 'intelligence' for docs grouping"

key-files:
  created:
    - app/services/gap_detection.py
    - tests/test_gap_detection.py
  modified:
    - app/models/intelligence.py
    - app/routers/memory.py

key-decisions:
  - "05-03 — gap_detection uses extract_entities()/normalize_entity_name() not a new NLP pipeline: consistent with 02-01 entity extraction decision, avoids dependency explosion"
  - "05-03 — POST /v1/memory/gaps on memory router not intelligence router: memory router prefix /v1/memory produces correct path; intelligence router prefix /v1/intelligence would produce wrong path"
  - "05-03 — Short query threshold < 5 words: regex person/topic patterns produce false positives on short inputs (e.g. 'about Alice' matches Alice as person but generates noisy gaps)"
  - "05-03 — Test uses person-name extraction pattern not topic pattern: topic pattern requires explicit trigger words (about/regarding); person pattern reliably extracts proper names like Alice from long queries"

patterns-established:
  - "Gap endpoint uses tags=['intelligence'] for OpenAPI grouping while living on memory router for URL correctness"
  - "Entity extraction queries written as: normalize+compare against entities.name_normalized for consistent dedup"

duration: 5min
completed: 2026-03-14
---

# Phase 5 Plan 3: Knowledge Gap Detection API Summary

**Knowledge gap detection API — POST /v1/memory/gaps surfaces entities queried 3+ times but absent from stored memories, using existing regex entity extractor with short-query guard**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-14T19:09:57Z
- **Completed:** 2026-03-14T19:14:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Built `detect_knowledge_gaps()` service that scans retrieval_log, extracts entities from queries, and diffs against entities table — returning entities queried >= N times but with no matching stored entity
- Added POST /v1/memory/gaps endpoint to memory router (not intelligence router) producing correct URL path, authenticated and rate-limited at 30/minute
- Added KnowledgeGap, GapDetectionRequest, GapDetectionResponse Pydantic models to intelligence.py without disturbing existing RouterStats/QTableEntry models from 05-02
- 8 passing tests (227 total suite), all gap detection requirements covered

## Task Commits

1. **Task 1: Create gap detection service and add Pydantic models** - `9f1901d` (feat)
2. **Task 2: Add POST /v1/memory/gaps endpoint and write tests** - `fc2ab80` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `app/services/gap_detection.py` — detect_knowledge_gaps() async function; imports extract_entities/normalize_entity_name from entity_extraction.py; skips queries < 5 words; queries retrieval_log by window, diffs against entities table
- `app/models/intelligence.py` — Added KnowledgeGap, GapDetectionRequest, GapDetectionResponse; preserved existing RouterStats/QTableEntry
- `app/routers/memory.py` — Added POST /v1/memory/gaps endpoint with auth, rate limiting, and usage logging
- `tests/test_gap_detection.py` — 8 tests covering empty log, entity already exists, missing entity found, min_mentions threshold, short query skip, days window, endpoint 200, custom params

## Decisions Made

- Placed POST /v1/memory/gaps on the memory router (prefix `/v1/memory`) rather than the intelligence router (prefix `/v1/intelligence`) — the plan explicitly flags this to produce the correct URL path `/v1/memory/gaps`
- Test query strategy: used person-name extraction ("Alice" in long queries) rather than topic extraction because the topic pattern requires explicit trigger words ("about X", "regarding X") which limits its reliability for gap detection tests

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test query strategy for entity extraction**
- **Found during:** Task 2 (test_detect_gaps_finds_missing_entity)
- **Issue:** Initial test used "Can you tell me about the status of ProjectX deployment..." — the topic pattern requires explicit trigger words ("about X") and "ProjectX" without a trigger word is not extracted. Test produced 4 queries_analyzed but 0 gaps.
- **Fix:** Rewrote queries to use "Alice" (a proper-name person) which the person pattern reliably extracts from long queries. Verified extraction output before writing final test.
- **Files modified:** tests/test_gap_detection.py
- **Verification:** All 8 tests pass with corrected queries
- **Committed in:** fc2ab80 (Task 2 commit, included in same commit after immediate fix)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in test query design)
**Impact on plan:** Caught during Task 2 execution, fixed inline. No scope creep. Test now correctly validates the requirement.

## Issues Encountered

- Entity extractor behavior needed verification — "ProjectX" without a topic trigger word is not extracted as a topic entity. Debugged by running extract_entities() interactively on the test queries before finalizing test text.

## Next Phase Readiness

- POST /v1/memory/gaps endpoint live and tested — ready for 05-04 (Q-router integration or next phase)
- Gap detection is purely on-demand — no background jobs introduced, no schema changes needed
- All 227 tests passing

---
*Phase: 05-self-improving-memory*
*Completed: 2026-03-14*

## Self-Check: PASSED

All files verified on disk. All commits verified in git history.

| Item | Status |
|------|--------|
| app/services/gap_detection.py | FOUND |
| app/models/intelligence.py | FOUND |
| tests/test_gap_detection.py | FOUND |
| .planning/phases/05-self-improving-memory/05-03-SUMMARY.md | FOUND |
| Commit 9f1901d | FOUND |
| Commit fc2ab80 | FOUND |
