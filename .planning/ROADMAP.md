# Roadmap: MemoraLabs

## Overview

MemoraLabs is a productization of ZimMemory v15 — the core intelligence already exists and is production-proven. The path from here to launch moves in strict dependency order: security and isolation infrastructure first (cross-tenant leakage cannot be retrofitted), then the memory engine port, then developer-facing auth and signup, then docs and the landing page, then the self-improving retrieval differentiators that require accumulated usage data to work, and finally deployment hardening to production on Render. Each phase delivers a verifiable capability; nothing ships until the previous layer is provably solid.

## Phases

- [x] **Phase 1: Foundation** - Secure multi-tenant infrastructure: system DB, tenant DB manager, isolation, health endpoint, persistent disk *(completed 2026-03-14)*
- [x] **Phase 2: Core Memory API** - Port ZimMemory engine to multi-tenant; full memory CRUD, semantic search, entity extraction, decay, deduplication *(completed 2026-03-14)*
- [x] **Phase 3: Auth API + Signup** - Tenant management, API key generation/rotation, auth middleware wired end-to-end *(completed 2026-03-14)*
- [x] **Phase 4: Developer Experience** - Public API docs, landing page, quickstart guide, structured error codes *(completed 2026-03-14)*
- [x] **Phase 5: Self-Improving Memory** - Q-learning router activation, retrieval feedback logging, knowledge gap detection, confidence scores *(completed 2026-03-14)*
- [x] **Phase 6: Deployment + Launch** - Render deploy, persistent disk mount, cold-start mitigation, production verification *(completed 2026-03-14)*

---

## Phase Details

### Phase 1: Foundation
**Goal**: A secure, isolated, deployable scaffold exists — the infrastructure layer every subsequent phase builds on
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06, INFRA-07
**Success Criteria** (what must be TRUE):
  1. `/health` returns 200 and the service is running
  2. A tenant database file is created and isolated the moment a new tenant is registered — no shared tables, no shared connection
  3. Cross-tenant isolation test passes: querying tenant A's memories from tenant B's connection returns zero results
  4. All database files are written to the persistent disk mount path, not `/tmp`
  5. Keep-alive cron is configured and pings `/health` on schedule
**Plans:** 4 plans

Plans:
- [x] 01-01-PLAN.md — System DB schema + project scaffolding (config, requirements, Pydantic models)
- [x] 01-02-PLAN.md — Tenant DB schema (memories, entities, relations ported from ZimMemory v15)
- [x] 01-03-PLAN.md — TenantDBManager (LRU connection pool, WAL mode, isolation enforcement)
- [x] 01-04-PLAN.md — FastAPI app with lifespan, health endpoint, render.yaml, keep-alive docs

### Phase 2: Core Memory API
**Goal**: A working memory API — store, search, update, delete — with vector retrieval, entity extraction, temporal decay, and deduplication
**Depends on**: Phase 1
**Requirements**: MEM-01, MEM-02, MEM-03, MEM-04, MEM-05, MEM-06, MEM-07, MEM-08, MEM-09, MEM-10, MEM-11, MEM-12, MEM-13, RETR-01, RETR-02, RETR-03, RETR-04, RETR-05
**Success Criteria** (what must be TRUE):
  1. Developer can store a memory via `POST /v1/memory` and receive a memory ID in response
  2. Developer can retrieve memories semantically with `POST /v1/memory/search` — results are ranked by relevance, not insertion order
  3. Developer can scope memories to a specific `user_id`, `session_id`, or `agent_id` and search within that scope only
  4. Entity extraction runs automatically — after storing "Alice met Bob at Google," querying for "Alice" returns the memory
  5. Duplicate writes are silently blocked — submitting the same memory text twice results in one stored memory
  6. Every API call is recorded in `usage_log` before the response is returned
**Plans:** 5 plans in 3 waves

Plans:
- [ ] 02-01-PLAN.md — Core services (dedup, decay, entity extraction), deps, Pydantic models [Wave 1]
- [ ] 02-02-PLAN.md — Embedding client (Fireworks.ai) + vector index manager (hnswlib) [Wave 1]
- [ ] 02-03-PLAN.md — POST /v1/memory endpoint with dedup, background embedding/entities, usage log [Wave 2]
- [ ] 02-04-PLAN.md — GET/PATCH/DELETE /v1/memory endpoints with pagination [Wave 2]
- [ ] 02-05-PLAN.md — POST /v1/memory/search with semantic scoring, metadata filters, decay [Wave 3]

### Phase 3: Auth API + Signup
**Goal**: Developers can sign up, receive an API key, and authenticate all requests — the service is a real product, not a stub
**Depends on**: Phase 2
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06
**Success Criteria** (what must be TRUE):
  1. Developer hits `POST /v1/auth/signup`, receives a plaintext API key shown exactly once, and can immediately use it to call memory endpoints
  2. The plaintext key is never stored — only the SHA-256 hash exists in the database; a database breach does not expose usable keys
  3. Developer can rotate their API key and all previously stored memories are accessible with the new key
  4. Any request missing a valid Bearer token receives a structured 401 JSON error, not a 500 or HTML page
**Plans**: 3 plans in 2 waves

Plans:
- [x] 03-01: Signup endpoint — `POST /v1/auth/signup`: create tenant record, generate key, hash+store, return plaintext once [Wave 1]
- [x] 03-02: Global exception handlers + `last_used_at` tracking [Wave 1]
- [x] 03-03: Key rotation endpoint — `POST /v1/auth/keys/rotate`: generate new key, invalidate old hash, preserve tenant data [Wave 2]

### Phase 4: Developer Experience
**Goal**: A developer unfamiliar with MemoraLabs can read the docs, get an API key, and have a memory stored and recalled within 10 minutes
**Depends on**: Phase 3
**Requirements**: DX-01, DX-02, DX-03, DX-04, DX-05
**Success Criteria** (what must be TRUE):
  1. API documentation is live at a public URL — all endpoints, parameters, and response schemas are browsable without signing up
  2. Landing page exists at the root domain and explains what MemoraLabs does, who it's for, and how to start
  3. Quickstart guide shows working curl commands that produce a stored and recalled memory end-to-end
  4. Every error response follows `{"error": "CODE", "message": "...", "details": {...}}` — no raw tracebacks, no generic 500s reach the caller
  5. Search responses include `memories_used` and `memories_limit` so developers can monitor their quota
**Plans**: 4 plans in 2 waves

Plans:
- [x] 04-01-PLAN.md — Verify structured error responses (DX-04 already done in Phase 3) [Wave 1]
- [x] 04-02-PLAN.md — OpenAPI enrichment: field descriptions, examples, tag metadata, error response docs [Wave 1]
- [x] 04-03-PLAN.md — Landing page at `/` with product explanation and docs/quickstart CTAs [Wave 2]
- [x] 04-04-PLAN.md — Quickstart guide (QUICKSTART.md + /quickstart HTML route) [Wave 2]

### Phase 5: Self-Improving Memory
**Goal**: Memory retrieval measurably improves over time without developer intervention — the core differentiator is active and demonstrable
**Depends on**: Phase 4 (retrieval logs must exist before Q-learning activates)
**Requirements**: SELF-01, SELF-02, SELF-03, SELF-04
**Success Criteria** (what must be TRUE):
  1. Every search operation records a retrieval feedback entry (query, result IDs, timestamp) — the training signal exists before the router trains
  2. After sufficient retrieval log accumulation, the Q-learning router's weights shift measurably from their initialized values
  3. `POST /v1/memory/gaps` returns entity patterns that appear in query logs but are absent from stored memories
  4. Search results include a `confidence` field (0.0-1.0) on each returned memory
**Plans**: 4 plans in 2 waves

Plans:
- [x] 05-01-PLAN.md — Retrieval feedback logging: retrieval_log table DDL, log_retrieval service, wired into search pipeline [Wave 1]
- [x] 05-02-PLAN.md — Q-learning router: Q-table DDL, bandit with activation threshold, router stats endpoint [Wave 2]
- [x] 05-03-PLAN.md — Knowledge gap detection: entity gap analysis from query logs, POST /v1/memory/gaps [Wave 2]
- [x] 05-04-PLAN.md — Confidence scores: 4-signal confidence computation on search results [Wave 2]

### Phase 6: Deployment + Launch
**Goal**: MemoraLabs is live on Render, survives restarts, and is ready for external developers to sign up
**Depends on**: Phase 5
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03
**Success Criteria** (what must be TRUE):
  1. Service is accessible at a public Render URL and returns a valid response to unauthenticated `GET /health`
  2. After a simulated Render restart, all previously stored tenant memories are intact and queryable
  3. Cold-start mitigation is active — a request arriving after 15 minutes of inactivity does not result in a 25-60 second hang
**Plans**: 3 plans in 2 waves

Plans:
- [x] 06-01-PLAN.md — Render deployment config: render.yaml completion, Docker runtime, startup disk-mount verification [Wave 1]
- [x] 06-02-PLAN.md — Production hardening: enhanced health endpoint with infra status + post-deploy smoke-test script [Wave 1]
- [x] 06-03-PLAN.md — Launch verification: deploy to Render, run smoke test, verify data persistence [Wave 2]

---

## Progress

**Execution Order:** 1 -> 2 -> 3 -> 4 -> 5 -> 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 4/4 | Complete | 2026-03-14 |
| 2. Core Memory API | 5/5 | Complete | 2026-03-14 |
| 3. Auth API + Signup | 3/3 | Complete | 2026-03-14 |
| 4. Developer Experience | 4/4 | Complete | 2026-03-14 |
| 5. Self-Improving Memory | 4/4 | Complete | 2026-03-14 |
| 6. Deployment + Launch | 3/3 | Complete | 2026-03-14 |
