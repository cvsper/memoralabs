# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-14)

**Core value:** Self-improving memory retrieval — agents that get smarter over time, not just bigger
**Current focus:** Phase 1 — Foundation

## Current Position

Phase: 1 of 6 (Foundation)
Plan: 3 of 4 in current phase (01-01 done, 01-02 done, 01-03 done)
Status: In progress
Last activity: 2026-03-14 — 01-03 complete: TenantDBManager LRU pool + 14 passing tests

Progress: [███░░░░░░░] 12%

## Performance Metrics

**Velocity:**
- Total plans completed: 3 (01-01, 01-02, 01-03)
- Average duration: ~2 min/plan
- Total execution time: ~6 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 3 | ~6 min | ~2 min |

**Recent Trend:**
- Last 5 plans: 01-01 (~2 min), 01-02 (~2 min), 01-03 (~2 min)
- Trend: Fast — foundation layer work

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

### Pending Todos

None yet.

### Blockers/Concerns

- **Render persistent disk**: Mount path and volume sizing must be verified in Render docs before Phase 1 deployment. $7/mo disk is confirmed necessary.
- **Fireworks.ai rate limits**: Free tier is 10 RPM without payment method. Async queue is mandatory from Phase 2. Per-tenant pre-limit required before any Fireworks call.
- **FastAPI exact version**: PyPI page inaccessible during research. Run `pip index versions fastapi` before pinning in requirements.txt.
- **Q-learning activation threshold**: No validated heuristic for minimum retrieval log volume before Q-learning improves vs. degrades results. Research needed before Phase 5.

## Session Continuity

Last session: 2026-03-14
Stopped at: Completed 01-03-PLAN.md (TenantDBManager LRU pool, 14 passing tests, cross-tenant isolation proven)
Resume file: None
