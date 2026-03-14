---
phase: 02-core-memory-api
verified: 2026-03-14T17:11:06Z
status: gaps_found
score: 5/6 must-haves verified
gaps:
  - truth: "Developer can retrieve memories semantically with POST /v1/memory/search — results ranked by vector similarity"
    status: failed
    reason: "add_vector coroutine is called without await on line 87 of app/routers/memory.py. In production, the vector is NEVER written to the hnswlib index. Memories have embedding blobs in the DB but the index stays empty. Vector search returns no results. The fallback path (recency sort) activates instead."
    artifacts:
      - path: "app/routers/memory.py"
        issue: "Line 87: app_state.index_manager.add_vector(...) missing await — coroutine created and abandoned, index never populated"
    missing:
      - "Add await before app_state.index_manager.add_vector(tenant_id, memory_id, embedding) on line 87"
human_verification:
  - test: "Store a memory, wait for background tasks to complete (~1s), then search for semantically similar text"
    expected: "Search returns the stored memory with a relevance score > 0 (not score=0.0 from recency fallback)"
    why_human: "Background task timing and Fireworks.ai API key required to fully exercise the live path"
---

# Phase 02: Core Memory API — Verification Report

**Phase Goal:** A working memory API — store, search, update, delete — with vector retrieval, entity extraction, temporal decay, and deduplication
**Verified:** 2026-03-14T17:11:06Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                   | Status      | Evidence                                                                                                 |
|----|-------------------------------------------------------------------------|-------------|----------------------------------------------------------------------------------------------------------|
| 1  | Developer can store a memory via POST /v1/memory and receive a memory ID | VERIFIED   | Route exists, inserts UUID, returns 201 + MemoryResponse(status="created"), dedup returns 200+duplicate  |
| 2  | Developer can retrieve memories semantically — results ranked by relevance | FAILED    | add_vector called without await on line 87; index is never populated; vector search returns no results in production |
| 3  | Memories can be scoped to user_id/session_id/agent_id and searched within that scope | VERIFIED | SQL WHERE clause built dynamically; search_memories applies scope filters before vector search; 3 scoped tests pass |
| 4  | Entity extraction runs automatically — querying for "Alice" returns the memory | VERIFIED | background task _extract_entities wired; process_entities_for_memory persists to relations table; e2e test passes |
| 5  | Duplicate writes are silently blocked — same text twice = one stored memory | VERIFIED | text_hash(sha256) checked before insert; case/whitespace normalized; returns existing ID with status=duplicate |
| 6  | Every API call is recorded in usage_log                                | VERIFIED   | log_usage called in all 8 route handlers; test_memory_write/read/search each verify usage_log entries    |

**Score:** 5/6 truths verified

---

## Required Artifacts

| Artifact                              | Expected                                        | Status      | Details                                                                                             |
|---------------------------------------|-------------------------------------------------|-------------|-----------------------------------------------------------------------------------------------------|
| `app/services/dedup.py`               | text_hash + cosine dedup check                  | VERIFIED    | text_hash(sha256), check_exact_duplicate, check_cosine_duplicate all present and substantive        |
| `app/services/decay.py`               | Temporal decay scoring                          | VERIFIED    | apply_decay (80/20 blend), decay_factor, DECAY_HALF_LIFE_DAYS=30                                    |
| `app/services/entity_extraction.py`   | Regex entity + relation extraction              | VERIFIED    | 10+ regex patterns, priority-ordered extraction, find_or_create_entity, process_entities_for_memory |
| `app/services/embedding.py`           | Async Fireworks.ai client with circuit breaker  | VERIFIED    | EmbeddingClient with embed, embed_single, circuit breaker (_trip, _available, cooldown=120s)        |
| `app/services/vector_index.py`        | Per-tenant hnswlib index manager with LRU       | VERIFIED    | TenantIndexManager with add_vector, search, remove_vector, save_all, close, LRU eviction            |
| `app/services/search.py`              | Hybrid search orchestrator                      | VERIFIED    | search_memories with metadata-first filtering, AND/OR logic, decay, recency fallback                |
| `app/routers/memory.py`               | All memory endpoints with rate limiting         | VERIFIED*   | POST, GET, GET/{id}, GET/{id}/entities, PATCH, DELETE all present. *Bug on line 87 (see gaps)       |
| `app/deps.py`                         | FastAPI tenant resolution dependencies          | VERIFIED    | get_tenant (Bearer→SHA256 hash→DB lookup→401 on failure), get_tenant_conn                           |
| `app/models/memory.py`                | Pydantic v2 request/response models             | VERIFIED    | MemoryCreate, MemoryResponse, MemoryUpdate, MemorySearchRequest, MemorySearchResult, MemorySearchResponse, MemoryListResponse |
| `app/limiter.py`                      | slowapi Limiter with tenant key function        | VERIFIED    | Limiter(key_func=get_tenant_key), tenant key hashes Bearer token, falls back to IP                  |
| `tests/test_memory_write.py`          | Integration tests for memory write              | VERIFIED    | 13 tests; all pass                                                                                   |
| `tests/test_memory_read.py`           | Integration tests for CRUD                      | VERIFIED    | 26 tests covering list, get, entities, patch, delete; all pass                                      |
| `tests/test_memory_search.py`         | Integration tests for search                    | VERIFIED    | 17 tests including entity e2e; all pass. Note: tests mock embed_single returning None, masking the add_vector bug |

---

## Key Link Verification

| From                         | To                          | Via                                      | Status      | Details                                                                            |
|------------------------------|-----------------------------|------------------------------------------|-------------|------------------------------------------------------------------------------------|
| `app/routers/memory.py`      | `app/services/dedup.py`     | check_exact_duplicate before insert     | WIRED       | text_hash imported and used on line 172; query at line 173-178                     |
| `app/routers/memory.py`      | `app/services/embedding.py` | BackgroundTasks.add_task(_generate_embedding) | WIRED  | background_tasks.add_task called at lines 234-239                                  |
| `app/routers/memory.py`      | `app/services/entity_extraction.py` | BackgroundTasks.add_task(_extract_entities) | WIRED | background_tasks.add_task called at lines 241-246                                |
| `app/routers/memory.py`      | `app/db/system.py`          | log_usage after every request            | WIRED       | log_usage called in all 8 route handlers                                           |
| `app/routers/memory.py`      | `app/limiter.py`            | @limiter.limit decorators                | WIRED       | @limiter.limit("60/minute") on POST, @limiter.limit("120/minute") on search        |
| `app/services/search.py`     | `app/services/vector_index.py` | index_manager.search with candidate_ids | WIRED     | index_manager.search(..., candidate_ids=set(candidates.keys())) at line 149-154    |
| `app/services/search.py`     | `app/services/decay.py`     | apply_decay on vector scores             | WIRED       | apply_decay(raw_score, row["created_at"]) at line 162                              |
| `app/services/search.py`     | `app/services/embedding.py` | embed_single before vector search        | WIRED       | embedding_client.embed_single(query) at line 118                                   |
| `app/main.py`                | `app/limiter.py`            | Limiter registered on app state          | WIRED       | app.state.limiter = limiter; app.add_exception_handler(RateLimitExceeded, ...) at lines 65-66 |
| `_generate_embedding` bg task | `TenantIndexManager`       | await add_vector (vector persistence)    | BROKEN      | Line 87: missing await — coroutine created but never executed                      |
| `app/deps.py`                | `app/db/system.py`          | get_tenant_by_key_hash                   | WIRED       | get_tenant_by_key_hash(request.app.state.system_db, key_hash) at line 63           |
| `app/deps.py`                | `app/db/manager.py`         | TenantDBManager.get_connection           | WIRED       | request.app.state.tenant_manager.get_connection(tenant["id"]) at line 91           |

---

## Requirements Coverage

| Requirement Group          | Status    | Notes                                                                                     |
|----------------------------|-----------|-------------------------------------------------------------------------------------------|
| MEM-01 (store memory)      | SATISFIED | POST /v1/memory returns 201 + memory ID                                                   |
| MEM-02 (scope by user_id)  | SATISFIED | user_id/agent_id/session_id stored and filterable in both list and search                 |
| MEM-03 (AND/OR metadata filter) | SATISFIED | metadata_filter_operator field in MemorySearchRequest; AND/OR SQL logic in search_memories |
| MEM-04 (scope search)      | SATISFIED | search_memories applies scope filters in SQL WHERE clause before vector search            |
| MEM-09 (temporal decay)    | SATISFIED | apply_decay applied to every vector score in search_memories step 5                       |
| MEM-10 (dedup)             | SATISFIED | text_hash exact dedup; cosine dedup post-embedding (when embedding works)                 |
| MEM-11 (usage log)         | SATISFIED | log_usage called in all route handlers                                                    |
| MEM-12 (rate limiting)     | SATISFIED | slowapi @limiter.limit("60/minute") on POST, @limiter.limit("120/minute") on search       |
| MEM-13 (soft delete)       | SATISFIED | DELETE sets is_deleted=1; GET/PATCH/DELETE return 404 afterwards                          |
| RETR-01 (vector search)    | BLOCKED   | Index never populated due to missing await — search always falls back to recency sort      |
| RETR-02 (ranked results)   | BLOCKED   | Depends on RETR-01 — vector scores unavailable                                            |
| RETR-03 (entity retrieval) | SATISFIED | GET /v1/memory/{id}/entities returns entities and relations via relations.memory_id join   |
| RETR-04 (result fields)    | SATISFIED | MemorySearchResult has id, text, score, metadata, user_id, agent_id, session_id, created_at |
| RETR-05 (metadata-first)   | SATISFIED | Candidate IDs fetched via SQL before any vector operations in search_memories              |

---

## Anti-Patterns Found

| File                        | Line | Pattern                              | Severity | Impact                                                                                |
|-----------------------------|------|--------------------------------------|----------|---------------------------------------------------------------------------------------|
| `app/routers/memory.py`     | 87   | Missing `await` on async method call | BLOCKER  | `add_vector` coroutine abandoned without execution; vector index never populated in production; semantic search silently degrades to recency sort for all tenants |

---

## Test Suite

**162/162 tests pass.** The missing-await bug is masked in tests because all tests mock `embed_single` to return `None` (no Fireworks API key in test env), causing `_generate_embedding` to return early before reaching line 87.

---

## Human Verification Required

### 1. Vector Search Returns Semantic Results

**Test:** Deploy with a valid `FIREWORKS_API_KEY`. Store a memory with text "Alice met Bob at Google." Wait ~2 seconds for background embedding. Then POST to `/v1/memory/search` with query "meeting at a tech company." Inspect the `score` field on results.
**Expected:** Results are returned with score > 0 (indicating vector similarity, not the recency fallback score of 0.0).
**Why human:** Requires a live Fireworks.ai API key and real embedding calls; test suite mocks the embedding client.

---

## Gaps Summary

One blocker gap prevents the core semantic search goal. On line 87 of `app/routers/memory.py`, the background task `_generate_embedding` calls `app_state.index_manager.add_vector(...)` without `await`. Since `add_vector` is an `async` method on `TenantIndexManager`, this creates a coroutine object that is immediately discarded without executing. The embedding blob is correctly saved to the SQLite `memories.embedding` column (lines 80-84 do await correctly), but the hnswlib in-memory index is never populated.

In production with a valid API key, every memory would have an embedding in the DB but the vector index would be empty. `search_memories` filters candidates using `embedding IS NOT NULL` (finding the memories) and then calls `index_manager.search(...)`, which returns an empty list because the index has no items. The search function's fallback path then returns candidates sorted by `created_at DESC` with `score=0.0` for all results.

The fix is one character: add `await` before the call on line 87.

All other components — dedup, decay, entity extraction, CRUD endpoints, rate limiting, tenant auth, usage logging, scoped search, metadata filtering — are fully implemented, wired, and tested. This is the only gap blocking the phase goal.

---

_Verified: 2026-03-14T17:11:06Z_
_Verifier: Claude (gsd-verifier)_
