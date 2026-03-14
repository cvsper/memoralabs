# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-14)

**Core value:** Self-improving memory retrieval — agents that get smarter over time, not just bigger
**Current focus:** Phase 4 — next phase

## Current Position

Phase: 4 of 6 (Developer Experience)
Plan: 2 of ? in phase 04 (done: 04-01, 04-02)
Status: Phase 4 in progress
Last activity: 2026-03-14 — 04-02 complete: OpenAPI docs enriched with field descriptions, examples, grouped tags (auth/memory/health), error responses on all endpoints; /_test/tenant hidden; 189/189 tests

Progress: [█████████░] 62%

## Performance Metrics

**Velocity:**
- Total plans completed: 14 (01-01, 01-02, 01-03, 01-04, 02-01, 02-02, 02-03, 02-04, 02-05, 03-01, 03-02, 03-03, 04-01, 04-02)
- Average duration: ~3 min/plan
- Total execution time: ~37 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 4 | ~10 min | ~2.5 min |
| 02-core-memory-api | 5 | ~14 min | ~2.8 min |
| 03-auth-api-signup | 3 | ~7 min | ~2.3 min |
| 04-developer-experience | 2 | ~7 min | ~3.5 min |

**Recent Trend:**
- Last 5 plans: 03-01 (~2 min), 03-02 (~2 min), 03-03 (~3 min), 04-01 (~3 min)
- Trend: Consistent — ~2-3 min/plan average
- Trend: Consistent — ~2-3 min/plan average

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions logged in PROJECT.md Key Decisions table.
Key decisions in effect:

- Flask → **FastAPI**: Research confirmed FastAPI is strictly better for an API product (native async, auto-generated OpenAPI, Pydantic v2). ZimMemory already uses it.
- **SQLite per tenant**: Simple isolation, no shared DB complexity for v1. Each tenant gets a `.db` file.
- **Fireworks.ai embeddings**: mxbai-embed-large-v1 (1024-dim). Already integrated. Free tier with async queue.
- **No Stripe for v1**: Ship faster, validate demand before billing complexity.
- **No SDKs for v1**: REST API only; SDKs after API surface is stable.
- **01-01 — Inline SYSTEM_SCHEMA_SQL**: String constant in system.py rather than runtime file read — simpler, no path issues. Migration file kept as documentation.
- **01-01 — Email regex not pydantic[email]**: Avoids extra dependency for simple format check.
- **embedding BLOB in Phase 1**: Added embedding BLOB DEFAULT NULL to memories table now to avoid Phase 2 migration.
- **init_tenant_db takes open connection**: TenantDBManager owns connection lifecycle; schema module only applies DDL.
- **01-03 — UUID regex as path-traversal guard**: Only lowercase UUIDs accepted for tenant_id; no filesystem I/O reachable with malicious input.
- **01-03 — Lock held entire get_connection body**: Prevents duplicate opens for same tenant under concurrent async load.
- **01-03 — create_tenant_db raises if file exists**: Idempotency is caller responsibility; no silent overwrite.
- [Phase 01-foundation]: monkeypatch both app.config.DATA_DIR and app.main.DATA_DIR in test fixture — lifespan captures the already-imported binding at module load time
- [Phase 01-foundation]: health router has no auth — will be explicitly exempted in Phase 3 auth middleware
- **02-01 — Priority-ordered entity extraction**: org > date > standalone location > location-in > person > topic; execution order prevents month names and org names from matching person pattern
- **02-01 — Starlette TestClient for deps tests**: httpx ASGITransport sends only http scopes, never lifespan — TestClient properly triggers startup/shutdown; portal.call() for async DB setup in sync test context
- **02-01 — /_test/tenant endpoint in main.py**: permanent test helper exercising Depends(get_tenant); returns only id/email/plan
- **02-02 — hnswlib RuntimeError on all-deleted search**: knn_query raises RuntimeError when all fetch_k candidates are deleted; caught and returns [] — correct behavior, no crash
- **02-02 — Rate limit key SHA-256 hashed**: Raw API key never stored in slowapi in-memory store; first 16 hex chars of SHA-256 used as key
- **02-02 — VECTOR_INDEX_DIR separate from DATA_DIR/tenants**: Per-tenant .idx + .ids.json files at data/indexes/ mirror the data/tenants/ pattern
- **02-02 — INITIAL_MAX_ELEMENTS=10,000 per tenant**: 10x headroom over free plan 1,000 limit; resize at 80% with 2x growth factor
- **02-03 — Shared app/limiter.py module**: limiter extracted from app.main to avoid circular import when routers import @limiter.limit decorator
- **02-03 — JSONResponse for duplicate 200**: endpoint declares status_code=201; explicit JSONResponse(status_code=200) required to override per-response
- **02-03 — Cosine dedup runs post-embedding in background**: soft-deletes new memory only if near-duplicate found (>=0.95 similarity), original preserved
- **02-04 — Entity retrieval via relations.memory_id not memory_entities join table**: actual schema links entities to memories through relations; no memory_entities table exists
- **02-04 — /entities route before /{id} route**: FastAPI matches in registration order; entities sub-path must be registered first
- **03-02 — exc.headers passthrough in http_exception_handler**: preserves WWW-Authenticate: Bearer on 401 responses without changes to deps.py raises
- **03-02 — update_key_last_used wrapped in try/except**: auth must never fail or slow due to usage tracking
- **03-02 — Error test fixture must call create_tenant_db**: GET memory endpoints 500 without tenant DB, regardless of system DB records existing
- **03-03 — deactivate_keys_for_tenant deactivates ALL keys**: no key accumulation after rotation; exactly one active key always
- **03-03 — signup calls create_tenant_db**: tenant DB initialised at signup so POST /v1/memory works immediately; without this, first memory POST returns 500
- **03-03 — rotation tests use signup API for setup**: full-flow integration tests rather than raw DB fixtures; caught the create_tenant_db bug in the process
- **04-01 — TestClient over httpx.ASGITransport for DX-04 tests**: plan suggested ASGITransport + AsyncClient but project decision 02-01 establishes TestClient as required pattern (ASGITransport doesn't trigger lifespan)
- **04-02 — model_config json_schema_extra for Pydantic v2 examples**: not deprecated singular example= parameter; json_schema_extra with examples list is the Pydantic v2 standard
- **04-02 — response_model= added to create_memory and search_memory**: was missing; without it FastAPI generates empty {} response schema in docs — critical for DX goal
- **04-02 — All endpoint docstrings rewritten to user-facing language**: implementation details removed; docstring becomes the endpoint summary in Swagger UI

### Pending Todos

None yet.

### Blockers/Concerns

- **Render persistent disk**: [RESOLVED 01-04] render.yaml configured with mountPath: /data, sizeGB: 1. Plan: starter. Verify in Render dashboard before first deploy.
- **Fireworks.ai rate limits**: Free tier is 10 RPM without payment method. Async queue is mandatory from Phase 2. Per-tenant pre-limit required before any Fireworks call.
- **FastAPI exact version**: PyPI page inaccessible during research. Run `pip index versions fastapi` before pinning in requirements.txt.
- **Q-learning activation threshold**: No validated heuristic for minimum retrieval log volume before Q-learning improves vs. degrades results. Research needed before Phase 5.

## Session Continuity

Last session: 2026-03-14
Stopped at: Completed 04-02-PLAN.md (OpenAPI enrichment — field descriptions, examples, tags, error responses, 189/189 tests)
Resume file: None
