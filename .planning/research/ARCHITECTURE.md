# Architecture Research

**Domain:** AI memory-as-a-service API (multi-tenant SaaS, productizing single-tenant Flask app)
**Researched:** 2026-03-14
**Confidence:** MEDIUM-HIGH (training knowledge + ZimMemory codebase inspection; web fetch unavailable this session)

---

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Gateway Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │  Auth/API    │  │  Rate Limit  │  │  Request Router      │   │
│  │  Key Verify  │  │  Middleware  │  │  (tenant resolve)    │   │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘   │
└─────────┴─────────────────┴──────────────────────┴───────────────┘
          │                                        │
┌─────────▼────────────────────────────────────────▼───────────────┐
│                       Application Layer                           │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐    │
│  │  Memory API    │  │  Auth API      │  │  Admin API       │    │
│  │  /memory/*     │  │  /auth/*       │  │  /admin/*        │    │
│  └───────┬────────┘  └───────┬────────┘  └────────┬─────────┘    │
└──────────┴────────────────────┴────────────────────┴──────────────┘
           │
┌──────────▼────────────────────────────────────────────────────────┐
│                       Core Engine Layer                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐  │
│  │  Retrieval │  │  Storage   │  │  Entity    │  │  Decay /   │  │
│  │  Engine    │  │  Engine    │  │  Extractor │  │  RL Router │  │
│  │ (RRF/BM25/ │  │ (embed +   │  │ (graph     │  │ (Q-learn + │  │
│  │  semantic) │  │  persist)  │  │  build)    │  │  temporal) │  │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘  │
└───────────────────────────────────────────────────────────────────┘
           │
┌──────────▼────────────────────────────────────────────────────────┐
│                       Tenant Data Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │  Tenant DB   │  │  Tenant DB   │  │  Shared System DB    │    │
│  │  (SQLite,    │  │  (SQLite,    │  │  (tenants, API keys, │    │
│  │  tenant_A)   │  │  tenant_B)   │  │  billing, usage)     │    │
│  └──────────────┘  └──────────────┘  └──────────────────────┘    │
└───────────────────────────────────────────────────────────────────┘
           │
┌──────────▼────────────────────────────────────────────────────────┐
│                      External Services Layer                       │
│  ┌──────────────────┐  ┌──────────────────────────────────────┐   │
│  │  Fireworks.ai    │  │  (Future: Stripe billing,            │   │
│  │  Embeddings      │  │   SendGrid email, S3 backups)        │   │
│  └──────────────────┘  └──────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| API Key Auth | Validate `Bearer` token, resolve tenant_id from key | Flask `before_request` decorator, SHA-256 key hashing, system DB lookup |
| Rate Limiter | Per-tenant request throttling (RPM/RPD), plan-gated | In-process counter dict (MVP) or Redis (scale); keyed by tenant_id |
| Request Router | Extract tenant_id from auth context, set thread-local DB connection | Flask `g` object with per-request `tenant_conn` |
| Tenant DB Manager | Open/create per-tenant SQLite file, connection pooling per file | Dict of `{tenant_id: Connection}` with LRU eviction |
| Memory API | REST endpoints for store, recall, search, delete, stats | Flask Blueprint: `POST /memory`, `POST /memory/recall`, `GET /memory/{id}` |
| Auth API | Signup, key generation, key rotation, tenant metadata | Flask Blueprint: `POST /auth/signup`, `POST /auth/keys` |
| Retrieval Engine | RRF fusion of BM25 + semantic vector search, temporal decay scoring | Direct port from ZimMemory (already production-grade) |
| Storage Engine | Embed text → store vector + metadata, deduplicate | Direct port from ZimMemory; swapped to per-tenant DB |
| Entity Extractor | NER → graph edges (relations table), entity resolution | Direct port from ZimMemory upgrade modules |
| Decay/RL Router | Temporal decay weighting, Q-learning retrieval optimization | Direct port from ZimMemory |
| System DB | Global state: tenants table, api_keys table, usage_log table | Single `system.db` SQLite (or Postgres at scale) |
| Tenant DB | Per-tenant: memories, entities, relations, routing state | Per-tenant `tenant_{id}.db` SQLite file |

---

## Recommended Project Structure

```
memoralabs/
├── api/
│   ├── __init__.py          # Flask app factory (create_app())
│   ├── auth.py              # Blueprint: /auth/* — signup, key CRUD
│   ├── memory.py            # Blueprint: /memory/* — core memory ops
│   └── admin.py             # Blueprint: /admin/* — internal ops
├── core/
│   ├── __init__.py
│   ├── tenant.py            # Tenant DB resolver, connection manager
│   ├── retrieval.py         # RRF engine (ported from ZimMemory)
│   ├── storage.py           # Embed + persist (ported from ZimMemory)
│   ├── entities.py          # Entity extraction + graph (ported from ZimMemory)
│   ├── decay.py             # Temporal decay + RL router (ported from ZimMemory)
│   └── embeddings.py        # Fireworks.ai client wrapper
├── db/
│   ├── system.py            # System DB init, schema, migrations
│   ├── tenant.py            # Tenant DB init, per-tenant schema
│   └── migrations/          # Schema migration scripts
├── middleware/
│   ├── auth.py              # API key validation before_request hook
│   └── ratelimit.py         # Per-tenant rate limiting
├── models/
│   └── schemas.py           # Request/response dataclasses or marshmallow schemas
├── config.py                # Env-var based config (dev/prod)
├── wsgi.py                  # Gunicorn entry point
├── data/
│   ├── system.db            # System-level database
│   └── tenants/             # Per-tenant SQLite files
│       ├── tenant_abc123.db
│       └── tenant_def456.db
└── tests/
    ├── test_auth.py
    ├── test_memory.py
    └── test_multitenancy.py
```

### Structure Rationale

- **api/**: Thin HTTP layer only — Blueprints handle routing, delegate to `core/`. No business logic here.
- **core/**: All ZimMemory intelligence lives here. These are direct ports, isolated from HTTP concerns.
- **db/**: Schema ownership. `system.py` owns the global tables; `tenant.py` owns per-tenant schema. Migrations stay separate from business logic.
- **middleware/**: Cross-cutting concerns that wrap every request. Keeping auth and rate limiting here means they're never skipped.
- **data/tenants/**: SQLite files named by tenant UUID. Simple, debuggable, no connection string hell.

---

## Architectural Patterns

### Pattern 1: Tenant Context via Flask `g`

**What:** Auth middleware resolves `api_key → tenant_id` in `before_request`, stores on `flask.g`. All downstream code reads `g.tenant_id` and `g.tenant_conn` — never touches auth itself.

**When to use:** Always. This is the foundational isolation mechanism.

**Trade-offs:** Simple, zero overhead. Breaks if any endpoint skips the middleware — so auth must be a blanket `before_request` with explicit `exempt_routes` for `/auth/signup` and health checks.

**Example:**
```python
# middleware/auth.py
@app.before_request
def require_api_key():
    exempt = ['/auth/signup', '/health']
    if request.path in exempt:
        return
    key = request.headers.get('Authorization', '').removeprefix('Bearer ')
    tenant = system_db.get_tenant_by_key(hash_key(key))
    if not tenant:
        return jsonify({'error': 'invalid_api_key'}), 401
    g.tenant_id = tenant['id']
    g.tenant_conn = tenant_db_manager.get_conn(tenant['id'])
```

### Pattern 2: SQLite-per-Tenant (Shard-by-File)

**What:** Each tenant gets `data/tenants/tenant_{uuid}.db`. The `TenantDBManager` maintains an LRU connection pool keyed by tenant_id.

**When to use:** This is the right pattern for v1. Complete data isolation, zero cross-tenant leakage risk, simple backup (copy the file), straightforward debugging.

**Trade-offs:** Doesn't scale to 10K+ tenants on a single node without connection pool exhaustion. Migration path to PostgreSQL row-level security is well-understood. For v1 (<500 tenants), this is not a concern.

**Example:**
```python
# core/tenant.py
class TenantDBManager:
    def __init__(self, data_dir: str, max_open: int = 50):
        self._data_dir = Path(data_dir)
        self._pool: OrderedDict[str, sqlite3.Connection] = OrderedDict()
        self._max_open = max_open

    def get_conn(self, tenant_id: str) -> sqlite3.Connection:
        if tenant_id in self._pool:
            self._pool.move_to_end(tenant_id)
            return self._pool[tenant_id]
        if len(self._pool) >= self._max_open:
            _, old_conn = self._pool.popitem(last=False)
            old_conn.close()
        db_path = self._data_dir / f"tenant_{tenant_id}.db"
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        init_tenant_schema(conn)
        self._pool[tenant_id] = conn
        return conn
```

### Pattern 3: ZimMemory Engine as a Library

**What:** The existing ZimMemory logic (retrieval, storage, entity extraction, decay) is refactored into `core/` as stateless functions that accept a `conn` parameter. The API layer passes `g.tenant_conn` to these functions.

**When to use:** Always. This is what makes the port fast.

**Trade-offs:** The existing ZimMemory `server.py` (2500 lines) uses a module-level global `conn`. That global must be eliminated. Every function needs to accept `conn` explicitly. This is the primary refactor task.

**Example:**
```python
# Before (ZimMemory single-tenant)
def store_memory(text, metadata):
    conn.execute("INSERT INTO memories ...")  # global conn

# After (MemoraLabs multi-tenant)
def store_memory(conn, text, metadata):       # conn passed in
    conn.execute("INSERT INTO memories ...")
```

### Pattern 4: Plan-Gated Rate Limiting

**What:** Each tenant has a `plan` field (free/pro/enterprise). Rate limiter reads `g.tenant_id → plan → limits`. Limits are enforced in middleware before the request hits business logic.

**When to use:** From day one. Adding it later means retrofitting across all endpoints.

**Trade-offs:** In-process counters (dict + timestamp) work for single-Render-instance MVP. Need Redis or Postgres-backed counters if running multiple instances. For Render free tier (single instance), in-process is fine.

---

## Data Flow

### Memory Store Request

```
POST /memory  {"content": "...", "metadata": {...}}
    │
    ▼ [middleware/auth.py]
API Key extracted from Authorization header
    → system.db lookup: api_keys → tenant_id
    → g.tenant_id set
    → g.tenant_conn = TenantDBManager.get_conn(tenant_id)
    → rate_limit check (per-tenant RPM counter)
    │
    ▼ [api/memory.py: store_memory endpoint]
Request validated (content required, metadata optional)
    │
    ▼ [core/storage.py: store()]
1. Dedup check: hash(content) → query memories table
2. Embed: POST https://api.fireworks.ai/... → 1024-dim vector
3. INSERT INTO memories (id, content, embedding, metadata, timestamp, decay_score)
4. Async (or sync): entity extraction → UPDATE entities + relations tables
    │
    ▼ [api/memory.py]
Return {"id": "...", "status": "stored"}
```

### Memory Recall Request

```
POST /memory/recall  {"query": "...", "top_k": 10}
    │
    ▼ [middleware: auth + rate limit]  (same as above)
    │
    ▼ [api/memory.py: recall endpoint]
    │
    ▼ [core/retrieval.py: recall()]
1. Embed query → 1024-dim vector
2. BM25 search: TF-IDF over memories.content (keyword candidates)
3. Semantic search: cosine_similarity(query_vec, memory_vec) (vector candidates)
4. RRF fusion: merge + re-rank BM25 + semantic results
5. Temporal decay: multiply score by decay_factor(memory.timestamp)
6. Graph boost: PageRank(entity) → bonus score for graph-dense memories
7. RL router: Q-learning updates retrieval weights based on feedback
    │
    ▼ [api/memory.py]
Return {"memories": [...], "graph_context": {...}}
```

### Tenant Signup Flow

```
POST /auth/signup  {"email": "...", "name": "..."}
    │
    ▼ [api/auth.py: signup]
1. Validate email uniqueness → system.db tenants table
2. Generate tenant_id: uuid4()
3. Generate api_key: secrets.token_hex(32)
4. Hash api_key: SHA-256
5. INSERT INTO tenants (id, email, name, plan='free', created_at)
6. INSERT INTO api_keys (key_hash, tenant_id, created_at)
7. TenantDBManager.get_conn(tenant_id) → creates + initializes tenant DB
    │
    ▼
Return {"api_key": "raw_key_shown_once", "tenant_id": "..."}
```

### Key Data Flows Summary

1. **Auth resolve:** Every request → system.db (single read) → tenant context set for entire request lifetime.
2. **Tenant isolation:** All memory operations go through `g.tenant_conn` — cross-tenant queries are structurally impossible (different SQLite files).
3. **Embedding:** Every store + recall hits Fireworks.ai. Rate-limit awareness needed (60 req/min free tier). Embedding cache on content hash mitigates repeated identical stores.
4. **Entity extraction:** Can be async (background thread or deferred) to keep store latency low. ZimMemory currently does this synchronously.

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 0-100 tenants | Single Render instance, SQLite-per-tenant, in-process rate limiting, synchronous entity extraction |
| 100-1K tenants | Add embedding cache (Redis or SQLite LRU), async entity extraction (Celery or simple thread pool), LRU connection pool cap raised |
| 1K-10K tenants | PostgreSQL row-level security migration, Redis for rate limiting + caching, Render background workers for async extraction |
| 10K+ tenants | Connection pooling via PgBouncer, vector DB (pgvector or Qdrant), horizontal Render instances behind load balancer |

### Scaling Priorities

1. **First bottleneck:** Fireworks.ai rate limit (60 req/min free tier). Fix: embedding cache keyed on content hash. Paid Fireworks plan (5K req/min) is cheap and defers this indefinitely.
2. **Second bottleneck:** SQLite write contention under concurrent writes to same tenant. Fix: WAL mode (`PRAGMA journal_mode=WAL`) + connection serialization per tenant. Already needed at medium traffic.
3. **Third bottleneck:** Connection pool exhaustion across many concurrent tenants. Fix: LRU eviction in TenantDBManager (already described in Pattern 2).

---

## Anti-Patterns

### Anti-Pattern 1: Global DB Connection (ZimMemory Single-Tenant Pattern)

**What people do:** Keep the module-level `conn = sqlite3.connect(DB_PATH)` from the original ZimMemory and add a `tenant_id` column to every table.

**Why it's wrong:** Shared SQLite file with tenant_id columns is not real isolation. A bug in a query predicate leaks data across tenants. WAL mode helps write throughput but a single bad JOIN exposes all tenants. Adds a `WHERE tenant_id = ?` requirement to every single query — one missed clause = data breach.

**Do this instead:** SQLite-per-tenant. The `TenantDBManager` pattern gives structural isolation. Cross-tenant leaks become structurally impossible, not just query-predicate-dependent.

### Anti-Pattern 2: Putting Auth Logic in Every Endpoint

**What people do:** Add `api_key = request.headers.get(...)` + DB lookup at the top of every Blueprint route function.

**Why it's wrong:** Guarantees that a new endpoint will ship without auth. Creates code duplication. Makes it impossible to see "what endpoints are protected" at a glance.

**Do this instead:** Single `before_request` middleware for the entire app. Maintain an explicit `EXEMPT_ROUTES` set. New routes are protected by default.

### Anti-Pattern 3: In-Memory Rate Limiting Across Multiple Processes

**What people do:** Deploy two Render instances and use a `dict` in-process rate limiter.

**Why it's wrong:** Each process has its own counter — a tenant can hit 2x (or Nx) the rate limit by distributing requests across instances.

**Do this instead:** For single Render instance (free/starter tier), in-process is fine and correct. Only switch to Redis-backed counters when intentionally scaling to multiple instances. Don't add Redis complexity prematurely.

### Anti-Pattern 4: Exposing Raw API Keys

**What people do:** Store the user's actual API key string in the database so it can be "shown again" if they forget it.

**Why it's wrong:** Database breach = all tenant keys compromised. Keys are credentials, not data.

**Do this instead:** Store `SHA-256(key)` only. Show the raw key exactly once at creation (like GitHub PATs). If lost, user rotates key. This is the standard for all API key systems (Stripe, OpenAI, etc.).

### Anti-Pattern 5: Synchronous Embedding in the Critical Path for Entity Extraction

**What people do:** Port ZimMemory's synchronous flow — store memory → extract entities → build graph edges — as a single blocking request.

**Why it's wrong:** Entity extraction (LLM call + graph ops) can add 2-5 seconds. That latency hits the user's store request.

**Do this instead:** Return immediately after embedding + memory insert. Run entity extraction in a background thread or enqueue it. The graph doesn't need to be updated before the store response.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Fireworks.ai embeddings | HTTPS REST, synchronous, per-request | 60 req/min free tier. Add content-hash cache in SQLite to avoid re-embedding identical text. Rate limit errors (429) should retry with exponential backoff, not fail the user request. |
| Fireworks.ai LLM (entity extraction) | HTTPS REST, async (background) | Used for entity NER. Can be deferred post-store. Ollama fallback preserved from ZimMemory config. |
| Render (hosting) | Single web service, `gunicorn wsgi:app` | Free tier: single instance, 512MB RAM, cold starts. `PYTHONUNBUFFERED=1`, bind `0.0.0.0:$PORT`. Health endpoint needed for uptime monitoring. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| api/ ↔ core/ | Direct function calls, passing `g.tenant_conn` | No HTTP between layers. Keeps latency zero and deployment simple. |
| middleware ↔ api/ | Flask request context (`g` object) | Auth middleware writes to `g`; endpoints read from `g`. Never pass tenant_id as a function argument through the app — it's always on `g`. |
| core/ ↔ db/ | `sqlite3.Connection` passed explicitly | `db/tenant.py` owns schema; `core/` owns queries. No schema DDL in `core/`. |
| TenantDBManager ↔ Tenant files | File system (`data/tenants/*.db`) | On Render: use persistent disk mount for this directory, or all tenant data is lost on redeploy. This is the single most critical infrastructure note. |

---

## Build Order (Dependency Graph)

The components have hard dependencies. Build in this order to avoid rework:

```
1. System DB schema (db/system.py)
         ↓
2. Tenant DB schema (db/tenant.py)  ← direct port of ZimMemory table definitions
         ↓
3. TenantDBManager (core/tenant.py)  ← needs schema to init on open
         ↓
4. API key auth middleware (middleware/auth.py)  ← needs system DB + TenantDBManager
         ↓
5. Core engine port (core/retrieval.py, core/storage.py, core/entities.py, core/decay.py)
   ← Direct port from ZimMemory, replacing global conn with passed conn parameter
         ↓
6. Memory API Blueprint (api/memory.py)  ← needs auth middleware + core engines
         ↓
7. Auth API Blueprint (api/auth.py)  ← needs system DB schema
         ↓
8. Rate limiting middleware (middleware/ratelimit.py)  ← layered on top of auth
         ↓
9. Embeddings client (core/embeddings.py)  ← needed by storage + retrieval
         ↓
10. App factory + WSGI entry (api/__init__.py, wsgi.py)
```

**Why this order matters:**
- Schema before manager: `TenantDBManager.get_conn()` calls `init_tenant_schema()` on first open — schema must exist before manager.
- Auth before endpoints: Endpoints registered without auth middleware = data exposure during development.
- Core engine port before API: Don't write HTTP handlers to a stub — port first, then wire up.
- Rate limiting after auth: Rate limiter reads `g.tenant_id` set by auth. Must be registered after auth middleware, or it has nothing to key on.

---

## Sources

- ZimMemory upgrade modules (v13, v14) — inspected directly, component inventory drawn from actual code
- Industry patterns from Mem0, Zep, LangMem architectures (training knowledge, MEDIUM confidence — web fetch unavailable this session)
- Flask multi-tenant SQLite-per-tenant pattern (training knowledge, MEDIUM confidence — well-established pattern, widely documented)
- API key security standards: SHA-256 hash, show-once pattern (training knowledge, HIGH confidence — industry standard, used by Stripe/OpenAI/GitHub)
- Render deployment constraints: persistent disk for SQLite, single-instance free tier (training knowledge, MEDIUM confidence — verify Render docs before deploy phase)

---
*Architecture research for: MemoraLabs — AI memory-as-a-service API*
*Researched: 2026-03-14*
