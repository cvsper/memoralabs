# Roadmap: MemoraLabs

## Overview

MemoraLabs is a productization of ZimMemory v15 — the core intelligence already exists and is production-proven. The path from here to launch moves in strict dependency order: security and isolation infrastructure first (cross-tenant leakage cannot be retrofitted), then the memory engine port, then developer-facing auth and signup, then docs and the landing page, then the self-improving retrieval differentiators that require accumulated usage data to work, and finally deployment hardening to production on Render. Each phase delivers a verifiable capability; nothing ships until the previous layer is provably solid.

## Phases

- [ ] **Phase 1: Foundation** - Secure multi-tenant infrastructure: system DB, tenant DB manager, isolation, health endpoint, persistent disk
- [ ] **Phase 2: Core Memory API** - Port ZimMemory engine to multi-tenant; full memory CRUD, semantic search, entity extraction, decay, deduplication
- [ ] **Phase 3: Auth API + Signup** - Tenant management, API key generation/rotation, auth middleware wired end-to-end
- [ ] **Phase 4: Developer Experience** - Public API docs, landing page, quickstart guide, structured error codes
- [ ] **Phase 5: Self-Improving Memory** - Q-learning router activation, retrieval feedback logging, knowledge gap detection, confidence scores
- [ ] **Phase 6: Deployment + Launch** - Render deploy, persistent disk mount, cold-start mitigation, production verification

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
**Plans**: TBD

Plans:
- [ ] 01-01: System DB schema — create `tenants`, `api_keys`, `usage_log` tables with migrations
- [ ] 01-02: Tenant DB schema — port ZimMemory `memories`, `entities`, `relations` schema to per-tenant SQLite
- [ ] 01-03: TenantDBManager — LRU connection pool, WAL mode, persistent disk path, isolation enforcement
- [ ] 01-04: Health endpoint + keep-alive cron setup

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
**Plans**: TBD

Plans:
- [ ] 02-01: Core engine port — refactor ZimMemory `retrieval.py`, `storage.py`, `entities.py`, `decay.py` to pass `conn` explicitly (eliminate global state)
- [ ] 02-02: Embedding client — async Fireworks.ai integration with queue, per-tenant rate limit, exponential backoff on 429
- [ ] 02-03: Memory write endpoint — `POST /v1/memory` with dedup check, entity extraction trigger, decay timestamp, usage log
- [ ] 02-04: Memory read endpoints — `GET /v1/memory`, `GET /v1/memory/{id}`, `PATCH /v1/memory/{id}`, `DELETE /v1/memory/{id}` with pagination
- [ ] 02-05: Memory search endpoint — `POST /v1/memory/search` with semantic scoring, metadata filters, scoped search

### Phase 3: Auth API + Signup
**Goal**: Developers can sign up, receive an API key, and authenticate all requests — the service is a real product, not a stub
**Depends on**: Phase 2
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06
**Success Criteria** (what must be TRUE):
  1. Developer hits `POST /v1/auth/signup`, receives a plaintext API key shown exactly once, and can immediately use it to call memory endpoints
  2. The plaintext key is never stored — only the SHA-256 hash exists in the database; a database breach does not expose usable keys
  3. Developer can rotate their API key and all previously stored memories are accessible with the new key
  4. Any request missing a valid Bearer token receives a structured 401 JSON error, not a 500 or HTML page
**Plans**: TBD

Plans:
- [ ] 03-01: Signup endpoint — `POST /v1/auth/signup`: create tenant record, generate key, hash+store, return plaintext once
- [ ] 03-02: Auth middleware — `before_request` hook resolving `Bearer → SHA-256 → tenant_id`; set `g.tenant_id` + `g.tenant_conn`; exempt `/health` and `/v1/auth/signup`
- [ ] 03-03: Key rotation endpoint — `POST /v1/auth/keys/rotate`: generate new key, invalidate old hash, preserve tenant data

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
**Plans**: TBD

Plans:
- [ ] 04-01: Structured error handling — global exception handler mapping all error classes to JSON error codes
- [ ] 04-02: OpenAPI docs — verify auto-generated `/docs` covers all endpoints with accurate schemas; add response examples
- [ ] 04-03: Landing page — static or server-rendered page at `/` explaining product, differentiators, and signup CTA
- [ ] 04-04: Quickstart guide — written walkthrough (curl + Python snippet) from signup to first stored+recalled memory

### Phase 5: Self-Improving Memory
**Goal**: Memory retrieval measurably improves over time without developer intervention — the core differentiator is active and demonstrable
**Depends on**: Phase 4 (retrieval logs must exist before Q-learning activates)
**Requirements**: SELF-01, SELF-02, SELF-03, SELF-04
**Success Criteria** (what must be TRUE):
  1. Every search operation records a retrieval feedback entry (query, result IDs, timestamp) — the training signal exists before the router trains
  2. After sufficient retrieval log accumulation, the Q-learning router's weights shift measurably from their initialized values
  3. `POST /v1/memory/gaps` returns entity patterns that appear in query logs but are absent from stored memories
  4. Search results include a `confidence` field (0.0–1.0) on each returned memory
**Plans**: TBD

Plans:
- [ ] 05-01: Retrieval feedback logging — instrument every search call to append `(query_id, result_ids, timestamp)` to retrieval log table
- [ ] 05-02: Q-learning router activation — port ZimMemory Q-learning router; wire against retrieval log; define activation threshold (minimum log volume before weights update)
- [ ] 05-03: Knowledge gap detection endpoint — `POST /v1/memory/gaps`: join entity graph + query log to surface missing knowledge
- [ ] 05-04: Confidence scores — compute and expose `confidence` on search results from co-occurrence + recency + relation type

### Phase 6: Deployment + Launch
**Goal**: MemoraLabs is live on Render, survives restarts, and is ready for external developers to sign up
**Depends on**: Phase 5
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03
**Success Criteria** (what must be TRUE):
  1. Service is accessible at a public Render URL and returns a valid response to unauthenticated `GET /health`
  2. After a simulated Render restart, all previously stored tenant memories are intact and queryable
  3. Cold-start mitigation is active — a request arriving after 15 minutes of inactivity does not result in a 25-60 second hang
**Plans**: TBD

Plans:
- [ ] 06-01: Render deployment — configure `render.yaml`, persistent disk mount, environment variables, startup command
- [ ] 06-02: Production hardening — verify disk mount path on boot, test restart recovery, confirm UptimeRobot keep-alive active
- [ ] 06-03: Launch verification — end-to-end smoke test: signup → store → search → gap detection from fresh external IP

---

## Progress

**Execution Order:** 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/4 | Not started | - |
| 2. Core Memory API | 0/5 | Not started | - |
| 3. Auth API + Signup | 0/3 | Not started | - |
| 4. Developer Experience | 0/4 | Not started | - |
| 5. Self-Improving Memory | 0/4 | Not started | - |
| 6. Deployment + Launch | 0/3 | Not started | - |
