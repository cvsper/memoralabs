# Project Research Summary

**Project:** MemoraLabs — AI Memory-as-a-Service API
**Domain:** Multi-tenant AI memory API platform (productizing ZimMemory v15)
**Researched:** 2026-03-14
**Confidence:** MEDIUM-HIGH

## Executive Summary

MemoraLabs is a productization play, not a greenfield build. The core intelligence engine already exists in ZimMemory v15 — 2,530+ memories, GraphRAG, Q-learning router, temporal decay, RRF fusion, confidence scoring — and is production-proven. The engineering challenge is wrapping that single-tenant system in a multi-tenant API shell with auth, billing, per-tenant isolation, and a clean public API surface. This is a well-understood SaaS transformation pattern, and the stack is already partially decided by what ZimMemory uses: FastAPI + SQLite + hnswlib + Fireworks.ai embeddings.

The market is a narrow 12-18 month window. Mem0 is the category leader with 50K+ developers. MemoraLabs has a genuine moat in four features no competitor offers: Q-learning self-improving retrieval, usage-driven temporal decay, knowledge gap detection, and PageRank-ranked entity retrieval. The pitch is clear — "every other memory API is a better filing cabinet; MemoraLabs is one that learns where you keep things." Shipping table stakes (CRUD + vector search + entity extraction + multi-tenant isolation) must happen fast; the differentiators (Q-learning router, gap detection) are what justify staying.

The top risks are not technical — they are operational. Cross-tenant data leakage is the #1 class of production incident across memory API providers (the Supermemory incident in March 2026 is the most recent example). Fireworks.ai rate limits will cascade under any real load if uncached and unqueued. And Render cold starts will kill developer trust on first contact if not mitigated. Every one of these is addressable in Phase 1, before any external developer touches the API. None are excuses to slow down — they are checklist items that must be done right the first time.

---

## Key Findings

### Recommended Stack

ZimMemory already runs FastAPI + Uvicorn + SQLite + hnswlib + Fireworks.ai — the stack is decided. The productization layer adds: SQLAlchemy 2.0 for the system/admin DB (tenant registry, API keys, billing), PyJWT + cryptography for API key auth, slowapi for rate limiting, Stripe for billing, and Sentry for error tracking. The only meaningful stack decision is whether to stay FastAPI or migrate to Flask. Verdict: stay FastAPI. It is strictly better for an API product — native async, auto-generated OpenAPI docs at `/docs`, Pydantic v2 validation built in. Flask would require rewriting working ZimMemory code for no benefit.

The single paid infrastructure line item is Render's persistent disk ($7/mo) — SQLite tenant files cannot live in `/tmp` (wiped on restart). All other MVP infrastructure is free: Fireworks.ai free tier (10-600 RPM with payment method), Sentry free tier (5K errors/mo), Render free web service. Celery and PostgreSQL are Phase 2+ items triggered by paying customers, not by ambition.

**Core technologies:**
- **FastAPI 0.115.x**: API framework — already in ZimMemory, native async, auto-generates OpenAPI docs
- **SQLite per-tenant**: Data isolation — each tenant gets an isolated `.db` file, zero infrastructure cost
- **hnswlib 0.8.0**: In-process vector search — already in ZimMemory, microsecond latency vs. managed vector DB milliseconds
- **Fireworks.ai (mxbai-embed-large-v1, 1024-dim)**: Embeddings — already integrated, free tier sufficient for MVP with queue
- **Stripe 14.4.1**: Billing — industry standard for dev-tool SaaS, start with flat monthly subscriptions
- **slowapi**: Rate limiting for FastAPI — same interface as Flask-Limiter, keyed by tenant_id
- **Sentry 2.54.0**: Error tracking — free tier, single `sentry_sdk.init()` call for FastAPI

See `.planning/research/STACK.md` for full version matrix and alternatives considered.

### Expected Features

The market has crystallized around clear table stakes. Missing any of the P1 features signals an incomplete product to experienced AI developers. The differentiators are where MemoraLabs wins — not by matching Mem0, but by offering what no competitor has.

**Must have for launch (v1):**
- Memory CRUD (add/search/update/delete) — the core write/read operations
- User + session + agent scoping (`user_id`, `session_id`, `agent_id` as first-class params)
- Semantic vector search with natural language queries
- Entity extraction (automatic, not manual) — glaring absence if missing
- Temporal decay with write timestamps — painful to retrofit; must be from day one
- Deduplication on write — near-duplicate detection before insert
- Metadata filtering (AND/OR key-value) — Mem0 has rich filtering; this is expected
- Python + JavaScript SDKs — both required at launch, not sequential
- Multi-tenant isolation with API key auth
- Versioned REST API (`/v1/`) with structured error codes

**Should have after validation (v1.x):**
- Q-learning router — the core moat; activates once retrieval logs exist
- Knowledge gap detection — high value, needs entity graph + query logs in place
- Full GraphRAG with graph traversal queries
- RRF fusion retrieval with measurable benchmark improvement
- Webhooks for event-driven integrations
- MCP support for Cursor/Claude distribution channel
- Memory consolidation engine
- Confidence scores exposed via API

**Defer to v2+:**
- Memory evolution reporting (needs 3-6 months of user data)
- Cross-agent memory sharing (validate simpler `agent_id` scoping first)
- Memory observability dashboard (enterprise feature, build when devs pay for it)
- Cold-start seeding from documents (niche until core API is proven)
- RBAC (over-engineering before traction)
- On-premise/VPC deployment (sales-motion feature, not self-serve)

**Do not build:**
- Built-in LLM chat endpoint (muddies positioning — this is a memory primitive, not an AI app)
- Custom embedding model fine-tuning (high infra cost, niche value)
- Automatic summarization as default (loses precision; consolidation engine handles this better)

See `.planning/research/FEATURES.md` for competitor feature matrix and full dependency graph.

### Architecture Approach

The architecture is a 4-layer system: API gateway (auth + rate limiting middleware) → application (FastAPI blueprints for memory, auth, admin) → core engine (direct ports of ZimMemory retrieval, storage, entity extraction, decay) → tenant data (per-tenant SQLite files + shared system DB). The primary refactor work is eliminating ZimMemory's module-level global `conn` and replacing it with an explicit `conn` parameter passed through every function call. This is the entire porting task — the algorithms stay unchanged.

**Major components:**
1. **TenantDBManager** — LRU connection pool keyed by tenant_id; opens `tenant_{uuid}.db` on first access, evicts oldest when pool cap reached; must use WAL mode on every DB opened
2. **API Key Middleware** — `before_request` hook; resolves `Bearer token → SHA-256 hash → tenant_id`; sets `g.tenant_id` + `g.tenant_conn`; exempts only `/auth/signup` and `/health`
3. **Core Engine (ported from ZimMemory)** — `core/retrieval.py`, `core/storage.py`, `core/entities.py`, `core/decay.py`; all functions refactored to accept `conn` parameter instead of global
4. **System DB** — single `system.db`; owns `tenants`, `api_keys`, `usage_log` tables; the source of truth for auth resolution
5. **Usage Metering** — every API call logs `tenant_id`, operation type, memory count delta, embedding tokens consumed; table exists before billing exists

Build order is strictly dependency-ordered: system DB schema → tenant DB schema → TenantDBManager → auth middleware → core engine ports → memory API → auth API → rate limiting → embeddings client → app factory + WSGI.

See `.planning/research/ARCHITECTURE.md` for data flow diagrams and anti-patterns.

### Critical Pitfalls

1. **Cross-tenant data leakage** — the #1 production incident class in memory APIs. The fix is structural: SQLite-per-tenant (not shared DB with `tenant_id` column), pre-filter by tenant before any similarity search, automated cross-tenant isolation test in CI from day one. A missed `WHERE tenant_id = ?` in one query = data breach.

2. **Fireworks.ai rate limit cascade** — free tier is 10 RPM without payment, 600 RPM with. One developer running integration tests exhausts the account-wide quota and degrades all tenants simultaneously. Fix: async embedding queue from the start; per-tenant rate limits enforced before hitting Fireworks; exponential backoff on 429, never surface as 500 to caller.

3. **SQLite on ephemeral storage** — `/tmp` on Render is wiped on restart. All tenant data is lost. Fix: Render persistent disk ($7/mo), mounted before any writes. This is not optional.

4. **Render cold start kills developer trust** — 25-60 second hang on first request after 15 minutes of inactivity. Fix: UptimeRobot ping every 10 minutes to `/health`; document the behavior; upgrade to Render Starter ($7/mo) before public launch.

5. **No usage metering = no business model** — without an `api_usage` table from day one, you cannot enforce tiers, detect abuse, or generate invoices. One power user on free tier can exhaust Fireworks quota for all tenants. Log every API call before worrying about a billing UI.

See `.planning/research/PITFALLS.md` for full pitfall-to-phase mapping and recovery strategies.

---

## Implications for Roadmap

Based on combined research, the build order is dictated by three constraints: (1) security and isolation cannot be retrofitted — they must be Phase 1 infrastructure, (2) the ZimMemory core engine ports before the API layer builds on top, and (3) the moat features (Q-learning, gap detection) require prior phases to generate the usage data they learn from.

### Phase 1: Foundation and Infrastructure

**Rationale:** Multi-tenant isolation, auth, and persistent storage are not features — they are load-bearing infrastructure. Every subsequent phase builds on top of them. A data leakage bug discovered in Phase 3 means rebuilding Phase 1. Do it right the first time.

**Delivers:** A secure, isolated, deployable scaffold with zero business logic — tenants can sign up, get API keys, and the service stays up.

**Addresses:**
- System DB schema (tenants, api_keys, usage_log tables)
- Tenant DB schema (memories, entities, relations — direct port from ZimMemory)
- TenantDBManager with LRU pool + WAL mode on every DB
- API key auth middleware (hashed storage, show-once pattern, `before_request`)
- `/health` endpoint + Render persistent disk mount + keep-alive cron
- Cross-tenant isolation test in CI

**Avoids:**
- Cross-tenant leakage (structural SQLite-per-tenant isolation)
- SQLite on ephemeral storage (persistent disk from day one)
- Plaintext API key storage (SHA-256 hash only, show once)
- Cold start developer trust loss (keep-alive + health endpoint)

**Research flag:** Standard patterns — no additional research needed. Well-documented multi-tenant SQLite + API key auth patterns.

---

### Phase 2: Core API — Memory CRUD and Retrieval

**Rationale:** ZimMemory's engine is the product. Porting it to multi-tenant with conn-passing is the core engineering task. Everything else wraps around it. Table stakes features must be present before any developer evaluation.

**Delivers:** A working memory API — store, search, update, delete — with vector retrieval, entity extraction, temporal decay, and deduplication. The MVP that could charge money.

**Addresses:**
- Port `core/retrieval.py`, `core/storage.py`, `core/entities.py`, `core/decay.py` — eliminate global `conn`
- `POST /v1/memory` with async embedding queue (never synchronous inline)
- `POST /v1/memory/search` with semantic + BM25 retrieval
- User/session/agent scoping (`user_id`, `session_id`, `agent_id`)
- Metadata filtering (AND/OR key-value)
- Temporal decay write timestamps (non-negotiable — retroactive is painful)
- Deduplication on write (cosine similarity > 0.95 check before insert)
- Usage metering table populated on every API call
- Per-tenant rate limiting middleware (enforced before Fireworks call)

**Avoids:**
- Fireworks rate limit cascade (async queue + per-tenant pre-limit)
- Memory inflation/retrieval decay (timestamps + dedup from day one)
- No usage metering (instrument before billing exists)

**Research flag:** Standard patterns — core engine port is mechanical (global conn → passed conn). Async embedding queue is a well-documented FastAPI BackgroundTasks pattern.

---

### Phase 3: Auth API and Billing Foundation

**Rationale:** Can't charge money without tenant management and Stripe integration. This phase turns the working API into a product. Comes after the core API works so billing wraps something real.

**Delivers:** Tenant signup/login, API key management (create/rotate/revoke), plan tiers with hard enforcement, Stripe subscription checkout.

**Addresses:**
- `POST /v1/auth/signup` — create tenant, generate API key, initialize tenant DB
- `POST /v1/auth/keys` — key rotation without data loss
- Plan tiers: free (1K memories, 100 req/day) vs. paid — hard 429 with structured error + upgrade URL
- Stripe subscription integration — `checkout.session.completed` and `customer.subscription.deleted` webhooks gate key activation
- Admin API for internal ops

**Avoids:**
- No tier enforcement (hard limits from day one, not soft warnings)
- Unclear pricing (structured errors with `limit`, `current`, `upgrade_url`)

**Research flag:** Stripe integration is well-documented. Verify Stripe webhook signature verification pattern before implementation (`stripe.Webhook.construct_event`). May benefit from a quick `/gsd:research-phase` on Stripe usage-based billing if metered pricing is chosen over flat tiers.

---

### Phase 4: SDKs and Developer Experience

**Rationale:** An API without SDKs and docs is a product only engineers with tolerance for friction will adopt. This phase converts the working API into something a developer can be productive with in under 10 minutes. Comes after auth and billing are stable so SDK examples work end-to-end.

**Delivers:** Python SDK (pip installable), JavaScript/TypeScript SDK (npm), working quickstart docs with curl + SDK examples, structured error codes.

**Addresses:**
- `pip install memoralabs` — typed Python client
- `npm install memoralabs` — typed TypeScript client
- Quickstart: working first memory in under 10 minutes
- Code-first docs (not marketing)
- Structured error responses: `{"error": "QUOTA_EXCEEDED", "limit": 1000, "current": 1000, "upgrade_url": "..."}`
- Memory count in response metadata: `{"memories_used": 450, "memories_limit": 1000}`

**Avoids:**
- No SDK = low adoption (developers abandon without working examples)
- Opaque errors = debugging friction

**Research flag:** Python SDK design — use `openai` SDK v2 as reference (async client, streaming, typed responses). Standard patterns but worth reviewing OpenAI SDK internals for conventions. No additional research phase needed.

---

### Phase 5: Differentiation — Self-Improving Memory

**Rationale:** This is the moat. Q-learning router and knowledge gap detection require retrieval logs that don't exist until the API is live and in use. Building them in Phase 2 would be building without training data. Phase 4 of active usage generates the signal; Phase 5 activates the learning.

**Delivers:** Q-learning retrieval router (self-improving weights), knowledge gap detection API, full GraphRAG with graph traversal, RRF fusion with measurable benchmark improvement, PageRank/influence scoring, confidence scores on memories.

**Addresses:**
- Activate Q-learning router against retrieval logs accumulated in Phase 2-4
- Knowledge gap detection (join entity graph + query log)
- GraphRAG upgrade from basic entity extraction to graph traversal queries
- RRF fusion retrieval (vector + graph + keyword combined)
- Publish benchmark: MemoraLabs vs. Mem0 on retrieval accuracy
- Confidence scores exposed via API response

**Avoids:**
- Activating Q-learning before retrieval logs exist (no signal to train on)
- GraphRAG without entity extraction in place (dependency satisfied in Phase 2)

**Research flag:** Q-learning router activation thresholds need research — specifically, minimum log volume before the router improves rather than degrades retrieval. MemRL papers (HuggingFace blog) are starting points. Recommend `/gsd:research-phase` before implementing the activation logic.

---

### Phase 6: Growth and Enterprise Foundation

**Rationale:** Once the product charges money and has validated differentiation, growth surfaces become worth building. MCP support is a distribution channel into Cursor/Claude users. Webhooks enable production integrations. These come last because they require a stable API surface to build on.

**Delivers:** MCP server for Cursor/Claude integration, webhooks for event-driven use cases, memory consolidation engine for long-running tenants, memory evolution reporting for enterprise analytics buyers.

**Addresses:**
- MCP protocol support (`tools/memory_store`, `tools/memory_recall`)
- Webhooks (memory.added, memory.updated, memory.deleted events)
- Memory consolidation engine (cluster + archive on schedule)
- Memory evolution reporting (periodic snapshots)

**Research flag:** MCP protocol specifics need research — Anthropic spec has evolved. Recommend `/gsd:research-phase` before MCP implementation. Webhooks are standard patterns (no research needed).

---

### Phase Ordering Rationale

- **Security before features:** Cross-tenant leakage and API key security cannot be retrofitted. One missed query predicate after thousands of memories are stored = unrecoverable incident. Phase 1 is the security foundation that every other phase trusts.
- **Core engine before API surface:** The API layer is thin routing. The intelligence is the ported ZimMemory engine. Port first, wrap second — avoids writing HTTP handlers to stubs.
- **Billing before SDKs:** SDKs should demonstrate a real end-to-end product, including auth and tier limits. A free SDK that works but doesn't show billing behavior misleads developers about the production experience.
- **Moat features last:** Q-learning and gap detection are uniquely valuable but require prior phases to generate the data they learn from. Rushing them before retrieval logs exist produces noise, not learning.
- **Growth features after validation:** MCP and webhooks are multipliers on a working product. Building them before product-market fit is premature optimization.

### Research Flags

Phases needing deeper research during planning:
- **Phase 3 (Billing):** Stripe usage-based billing specifics if metered pricing is chosen over flat tiers. Flat tiers are well-documented; metered billing has nuances.
- **Phase 5 (Q-Learning Activation):** Minimum log volume thresholds before Q-learning improves vs. degrades retrieval. MemRL papers are starting points but activation heuristics need research.
- **Phase 6 (MCP):** Anthropic MCP spec has evolved rapidly. Verify current protocol before implementation.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Foundation):** Multi-tenant SQLite + API key auth are textbook patterns. Architecture research has full implementation examples.
- **Phase 2 (Core API):** ZimMemory engine port is mechanical. FastAPI BackgroundTasks for async embedding is standard.
- **Phase 4 (SDKs):** OpenAI SDK v2 is the reference implementation. Follow its conventions.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Most packages verified on PyPI. FastAPI version MEDIUM (PyPI page inaccessible during research — verify with `pip index versions fastapi` before pinning). Stack decision is firm regardless of exact version. |
| Features | MEDIUM-HIGH | Competitive landscape from official docs + research papers. Some competitor features (especially recent additions) may have changed. Core table stakes and MemoraLabs' differentiators are well-supported. |
| Architecture | MEDIUM-HIGH | Multi-tenant SQLite pattern is well-established. ZimMemory codebase inspected directly for component inventory. Render deployment constraints from training knowledge — verify Render docs before deploy phase. |
| Pitfalls | HIGH | Cross-tenant leakage patterns verified from multiple sources including real incident reports (Supermemory March 2026). Fireworks rate limits from official docs. Cold start from Render community. |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **FastAPI exact version:** PyPI page was inaccessible during research. Run `pip index versions fastapi` before pinning in requirements.txt.
- **Fireworks.ai tier limits at scale:** The 600 RPM ceiling (with payment method) needs validation against expected tenant write volume. If MemoraLabs exceeds this with legitimate usage, either a paid Fireworks plan or a local Ollama fallback on MBP-C becomes necessary infrastructure.
- **Render persistent disk specifics:** Mount path and volume sizing constraints should be verified in Render docs before Phase 1 deployment. The $7/mo disk is confirmed as necessary — the configuration details are not validated.
- **hnswlib maintenance status:** Last release December 2023. If maintenance becomes a concern, evaluate `usearch` as a drop-in alternative. Not blocking for v1.
- **Q-learning activation thresholds:** No validated heuristic for minimum retrieval log volume before Q-learning improves rather than degrades results. Needs targeted research before Phase 5.

---

## Sources

### Primary (HIGH confidence)
- PyPI package pages (verified): pydantic, sqlalchemy, alembic, hnswlib, gunicorn, uvicorn, redis, celery, stripe, sentry-sdk, fireworks-ai, openai, tenacity, numpy, requests, httpx, cryptography, flask and related packages
- Fireworks AI Rate Limits — Official Docs (docs.fireworks.ai)
- Render community: free tier sleep behavior (community.render.com)
- Mem0 research paper (arxiv 2504.19413)
- Zep Graphiti architecture paper (arxiv 2501.13956)
- Memory in the Age of AI Agents (arxiv 2512.13564)
- Supermemory incident report March 6, 2026 (blog.supermemory.ai) — real-world cross-tenant leakage incident
- Multi-tenancy in Vector Databases (pinecone.io)

### Secondary (MEDIUM confidence)
- Mem0 docs (mem0.ai) — feature set and pricing
- Zep docs and Graphiti (getzep.com, github.com/getzep/graphiti) — temporal knowledge graph patterns
- LangMem docs (langchain-ai.github.io/langmem) — LangGraph memory primitives
- Cognee (cognee.ai, github.com/topoteretes/cognee) — 6-stage pipeline
- Letta/MemGPT (letta.com) — agent-centric memory model
- DEV Community Mem0 vs Zep vs LangMem comparison (2026)
- Database-per-Tenant SQLite patterns (Medium, High Performance SQLite)
- MemRL reinforcement learning on memory (HuggingFace blog)
- Flask multi-tenancy patterns (Medium)
- SaaS free tier abuse and billing patterns (Medium)

### Tertiary (LOW confidence)
- FastAPI exact version — verify before pinning (PyPI page inaccessible during research)
- Render disk mount configuration specifics — verify in Render docs before deploy

---
*Research completed: 2026-03-14*
*Ready for roadmap: yes*
