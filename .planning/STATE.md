# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-14)

**Core value:** Self-improving memory retrieval — agents that get smarter over time, not just bigger
**Current focus:** Phase 2 — Core Memory API

## Current Position

Phase: 2 of 6 (Core Memory API)
Plan: 3 of 5 in current phase (02-01 done, 02-02 done, 02-03 done)
Status: In progress
Last activity: 2026-03-14 — 02-03 complete: POST /v1/memory, dedup, background tasks, rate limiting, 118/118 tests

Progress: [█████░░░░░] 30%

## Performance Metrics

**Velocity:**
- Total plans completed: 7 (01-01, 01-02, 01-03, 01-04, 02-01, 02-02, 02-03)
- Average duration: ~3 min/plan
- Total execution time: ~18 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 4 | ~10 min | ~2.5 min |
| 02-core-memory-api | 3 | ~8 min | ~2.7 min |

**Recent Trend:**
- Last 5 plans: 01-03 (~2 min), 01-04 (~4 min), 02-01 (~2 min), 02-02 (~5 min), 02-03 (~3 min)
- Trend: Consistent — ~3 min/plan average

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

### Pending Todos

None yet.

### Blockers/Concerns

- **Render persistent disk**: [RESOLVED 01-04] render.yaml configured with mountPath: /data, sizeGB: 1. Plan: starter. Verify in Render dashboard before first deploy.
- **Fireworks.ai rate limits**: Free tier is 10 RPM without payment method. Async queue is mandatory from Phase 2. Per-tenant pre-limit required before any Fireworks call.
- **FastAPI exact version**: PyPI page inaccessible during research. Run `pip index versions fastapi` before pinning in requirements.txt.
- **Q-learning activation threshold**: No validated heuristic for minimum retrieval log volume before Q-learning improves vs. degrades results. Research needed before Phase 5.

## Session Continuity

Last session: 2026-03-14
Stopped at: Completed 02-03-PLAN.md (POST /v1/memory endpoint, circular import fix via app/limiter.py, 118/118 tests)
Resume file: None
