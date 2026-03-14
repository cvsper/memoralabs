# Requirements: MemoraLabs

**Defined:** 2026-03-14
**Core Value:** Self-improving memory retrieval — agents that get smarter over time, not just bigger

## v1 Requirements

Requirements for initial release. Each maps to exactly one roadmap phase.

### Infrastructure

- [ ] **INFRA-01**: System database schema exists with `tenants`, `api_keys`, and `usage_log` tables
- [ ] **INFRA-02**: Tenant database schema exists with `memories`, `entities`, and `relations` tables (ported from ZimMemory)
- [ ] **INFRA-03**: TenantDBManager provides per-tenant SQLite connection pool with LRU eviction and WAL mode
- [ ] **INFRA-04**: All tenant database files reside on Render persistent disk (not ephemeral `/tmp`)
- [ ] **INFRA-05**: Cross-tenant isolation is enforced structurally (SQLite-per-tenant, never shared DB with column filter)
- [ ] **INFRA-06**: `/health` endpoint returns 200 with service status
- [ ] **INFRA-07**: Keep-alive cron pings `/health` every 10 minutes to prevent cold starts

### Authentication

- [ ] **AUTH-01**: Developer can sign up via `POST /v1/auth/signup` and receive an API key
- [ ] **AUTH-02**: API key is shown exactly once at creation (SHA-256 hash stored, plaintext never persisted)
- [ ] **AUTH-03**: All API requests are authenticated via `Authorization: Bearer <key>` header
- [ ] **AUTH-04**: Auth middleware resolves `Bearer token → SHA-256 → tenant_id` before every protected request
- [ ] **AUTH-05**: Developer can rotate their API key without losing stored memories
- [ ] **AUTH-06**: Unauthenticated requests receive structured 401 error

### Memory

- [ ] **MEM-01**: Developer can store a memory via `POST /v1/memory` with text content
- [ ] **MEM-02**: Memories support `user_id`, `session_id`, and `agent_id` scoping as first-class parameters
- [ ] **MEM-03**: Memories support arbitrary metadata key-value pairs with AND/OR filter querying
- [ ] **MEM-04**: Developer can search memories semantically via `POST /v1/memory/search` with natural language query
- [ ] **MEM-05**: Developer can retrieve a specific memory by ID via `GET /v1/memory/{id}`
- [ ] **MEM-06**: Developer can update a memory via `PATCH /v1/memory/{id}`
- [ ] **MEM-07**: Developer can delete a memory by ID via `DELETE /v1/memory/{id}`
- [ ] **MEM-08**: Developer can list memories with pagination via `GET /v1/memory`
- [ ] **MEM-09**: All memories receive write timestamps and temporal decay weights at creation (non-retroactive)
- [ ] **MEM-10**: Near-duplicate memory detection runs on write (cosine similarity > 0.95 blocks duplicate insert)
- [ ] **MEM-11**: Every API call is recorded in `usage_log` with tenant_id, operation type, and token count
- [ ] **MEM-12**: Per-tenant rate limiting is enforced before any embedding call reaches Fireworks.ai
- [ ] **MEM-13**: Embedding generation runs asynchronously (never blocks the write response)

### Retrieval

- [ ] **RETR-01**: Semantic search uses Fireworks.ai `mxbai-embed-large-v1` (1024-dim) embeddings with hnswlib
- [ ] **RETR-02**: Entity extraction runs automatically on memory write (people, topics, dates, places)
- [ ] **RETR-03**: Entity graph is populated and queryable after memory ingestion
- [ ] **RETR-04**: Search results include memory content, score, and metadata
- [ ] **RETR-05**: Search supports metadata filters (AND/OR key-value) applied before vector scoring

### Self-Improving Memory

- [ ] **SELF-01**: Q-learning router activates against accumulated retrieval logs to update retrieval weights
- [ ] **SELF-02**: Retrieval feedback signal (hit/miss) is logged for every search operation
- [ ] **SELF-03**: Knowledge gap detection API surfaces entity patterns absent from memory but present in queries
- [ ] **SELF-04**: Confidence scores are exposed on memory search results

### Developer Experience

- [ ] **DX-01**: API documentation is publicly accessible online (auto-generated OpenAPI at `/docs`)
- [ ] **DX-02**: Landing page explains product value proposition and includes signup/waitlist CTA
- [ ] **DX-03**: Quickstart guide enables a developer to store and recall a first memory in under 10 minutes
- [ ] **DX-04**: All API errors return structured JSON: `{"error": "CODE", "message": "...", "details": {...}}`
- [ ] **DX-05**: Search responses include usage metadata: `{"memories_used": N, "memories_limit": N}`

### Deployment

- [ ] **DEPLOY-01**: Service is deployed to Render and accessible via public URL
- [ ] **DEPLOY-02**: Render persistent disk is mounted before any tenant data is written
- [ ] **DEPLOY-03**: Service survives Render restart with all tenant data intact

---

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Billing

- **BILL-01**: Developer can subscribe to a paid plan via Stripe checkout
- **BILL-02**: Free tier enforces hard limits (1K memories, 100 req/day) with structured 429 + upgrade URL
- **BILL-03**: Paid tier activates automatically on `checkout.session.completed` webhook
- **BILL-04**: Subscription cancellation degrades tier gracefully on `customer.subscription.deleted`

### SDKs

- **SDK-01**: Python SDK (`pip install memoralabs`) with typed client and async support
- **SDK-02**: JavaScript/TypeScript SDK (`npm install memoralabs`) with typed client

### Advanced Retrieval

- **ADV-01**: Full GraphRAG with entity relationship traversal queries
- **ADV-02**: RRF (Reciprocal Rank Fusion) combining vector + graph + keyword signals
- **ADV-03**: PageRank / influence scoring on the entity graph
- **ADV-04**: Memory consolidation engine clusters and archives stale memories on schedule

### Integrations

- **INT-01**: MCP server exposes `tools/memory_store` and `tools/memory_recall` for Cursor/Claude integration
- **INT-02**: Webhooks fire on `memory.added`, `memory.updated`, `memory.deleted` events

### Analytics

- **ANLY-01**: Memory evolution reporting shows how a tenant's memory profile changes over time
- **ANLY-02**: Cross-agent memory sharing with access-controlled shared namespaces

---

## Out of Scope

Explicitly excluded for v1. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Dashboard UI | API-first for v1 — developers interact via API and CLI, not GUI |
| Stripe billing | Ship faster, validate demand before billing complexity |
| Python + JS SDKs | REST API sufficient for v1; SDKs are v2 once API surface is stable |
| Mobile SDKs | REST API only for v1 |
| Self-hosting option | Cloud-only for v1; VPC deployment is a sales-motion enterprise SKU |
| Built-in LLM chat endpoint | Muddies positioning — this is a memory primitive, not an AI app |
| Custom embedding fine-tuning | High infra cost, niche value; offer model selection as v2+ |
| Real-time streaming writes | Memory atomicity matters more than streaming; no recall quality gain |
| Conversation storage/replay | Scope creep into chat platform territory |
| RBAC | Over-engineering before traction; namespace isolation sufficient for v1 |
| Automatic summarization as default | Summaries lose precision; consolidation engine is the correct pattern |
| Cross-agent memory sharing | Validate simpler `agent_id` scoping before shared namespaces |
| Memory observability dashboard | Enterprise feature; build after devs are paying for observability |

---

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 1 | Pending |
| INFRA-02 | Phase 1 | Pending |
| INFRA-03 | Phase 1 | Pending |
| INFRA-04 | Phase 1 | Pending |
| INFRA-05 | Phase 1 | Pending |
| INFRA-06 | Phase 1 | Pending |
| INFRA-07 | Phase 1 | Pending |
| MEM-01 | Phase 2 | Pending |
| MEM-02 | Phase 2 | Pending |
| MEM-03 | Phase 2 | Pending |
| MEM-04 | Phase 2 | Pending |
| MEM-05 | Phase 2 | Pending |
| MEM-06 | Phase 2 | Pending |
| MEM-07 | Phase 2 | Pending |
| MEM-08 | Phase 2 | Pending |
| MEM-09 | Phase 2 | Pending |
| MEM-10 | Phase 2 | Pending |
| MEM-11 | Phase 2 | Pending |
| MEM-12 | Phase 2 | Pending |
| MEM-13 | Phase 2 | Pending |
| RETR-01 | Phase 2 | Pending |
| RETR-02 | Phase 2 | Pending |
| RETR-03 | Phase 2 | Pending |
| RETR-04 | Phase 2 | Pending |
| RETR-05 | Phase 2 | Pending |
| AUTH-01 | Phase 3 | Pending |
| AUTH-02 | Phase 3 | Pending |
| AUTH-03 | Phase 3 | Pending |
| AUTH-04 | Phase 3 | Pending |
| AUTH-05 | Phase 3 | Pending |
| AUTH-06 | Phase 3 | Pending |
| DX-01 | Phase 4 | Pending |
| DX-02 | Phase 4 | Pending |
| DX-03 | Phase 4 | Pending |
| DX-04 | Phase 4 | Pending |
| DX-05 | Phase 4 | Pending |
| SELF-01 | Phase 5 | Pending |
| SELF-02 | Phase 5 | Pending |
| SELF-03 | Phase 5 | Pending |
| SELF-04 | Phase 5 | Pending |
| DEPLOY-01 | Phase 6 | Pending |
| DEPLOY-02 | Phase 6 | Pending |
| DEPLOY-03 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 43 total
- Mapped to phases: 43
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-14*
*Last updated: 2026-03-14 after initial definition*
