# Phase 2: Core Memory API - Research

**Researched:** 2026-03-14
**Domain:** Memory CRUD, vector search, entity extraction, embedding pipelines
**Confidence:** HIGH

## Summary

Phase 2 ports ZimMemory's core engine into MemoraLabs' multi-tenant FastAPI architecture. The existing ZimMemory v15 codebase (~6,900 lines in server.py) provides a proven reference implementation with TF-IDF + HNSW dual-engine search, regex-based entity extraction, cosine dedup, temporal decay, and RRF hybrid ranking. The key challenge is adapting this single-tenant, synchronous, globally-scoped design into per-tenant async operations using the Phase 1 infrastructure (TenantDBManager, aiosqlite, system.db usage logging).

Phase 1 already built the foundation: per-tenant SQLite schema (memories, entities, relations, feedback tables with all needed columns), LRU connection pooling, WAL mode, API key auth resolution, and usage logging. The tenant schema includes `embedding BLOB`, `text_hash`, `metadata JSON`, and all indexes needed. This means Phase 2 is primarily about building the service layer and endpoints on top of existing schema.

**Primary recommendation:** Port ZimMemory functions as standalone async service modules (not monolithic classes). Each concern -- embedding, dedup, entity extraction, search, decay -- gets its own module under `app/services/`. Use `httpx.AsyncClient` for Fireworks.ai calls, `hnswlib` for per-tenant vector indexes (one index file per tenant, lazy-loaded), and FastAPI `BackgroundTasks` for async embedding + entity extraction after write responses.

## Standard Stack

### Core (already in requirements.txt)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | >=0.115.0 | API framework | Already chosen, Phase 1 |
| aiosqlite | >=0.21.0 | Async SQLite | Already chosen, Phase 1 |
| pydantic | >=2.0.0 | Request/response validation | Already chosen, Phase 1 |
| httpx | >=0.27.0 | Async HTTP client | Already in requirements, needed for Fireworks.ai |

### New Dependencies for Phase 2
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hnswlib | >=0.8.0 | HNSW vector index | ZimMemory uses it, proven at scale, C++ core |
| numpy | >=1.26.0 | Vector math, cosine similarity | Required by hnswlib, used for embedding math |
| slowapi | >=0.1.9 | Per-tenant rate limiting | Standard FastAPI rate limiter, supports custom key functions |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hnswlib | faiss | faiss is heavier, harder to install, overkill for per-tenant small indexes |
| slowapi | custom RateLimiter | ZimMemory has a simple custom one, but slowapi handles edge cases (Redis backend later) |
| httpx | aiohttp | httpx already in requirements, has sync/async dual API, OpenAI-compatible |

**Installation:**
```bash
pip install hnswlib numpy slowapi
```

## Architecture Patterns

### Recommended Project Structure
```
app/
├── config.py                  # Existing (add FIREWORKS_* settings)
├── main.py                    # Existing (add new routers)
├── db/
│   ├── system.py              # Existing (usage logging)
│   ├── tenant.py              # Existing (schema)
│   └── manager.py             # Existing (connection pool)
├── models/
│   ├── schemas.py             # Existing (extend with memory models)
│   └── memory.py              # NEW: Memory request/response models
├── services/
│   ├── embedding.py           # NEW: Fireworks.ai client, queue, circuit breaker
│   ├── vector_index.py        # NEW: Per-tenant hnswlib index manager
│   ├── entity_extraction.py   # NEW: Regex entity/relation extraction
│   ├── dedup.py               # NEW: text_hash + cosine dedup
│   ├── decay.py               # NEW: Temporal decay scoring
│   └── search.py              # NEW: Hybrid search (vector + metadata filter)
├── routers/
│   ├── health.py              # Existing
│   └── memory.py              # NEW: /v1/memory endpoints
└── deps.py                    # NEW: FastAPI dependencies (get_tenant, get_conn)
```

### Pattern 1: FastAPI Dependency for Tenant Resolution
**What:** A reusable `Depends()` that extracts tenant_id from the API key, gets the DB connection, and injects both into route handlers.
**When to use:** Every authenticated endpoint.
**Example:**
```python
# app/deps.py
from fastapi import Depends, Request, HTTPException
from app.db.system import get_tenant_by_key_hash
import hashlib

async def get_tenant(request: Request) -> dict:
    """Extract API key from header, resolve to tenant. Returns tenant dict."""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    system_db = request.app.state.system_db
    tenant = await get_tenant_by_key_hash(system_db, key_hash)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tenant

async def get_tenant_conn(request: Request, tenant: dict = Depends(get_tenant)):
    """Get the tenant's DB connection from the pool."""
    manager = request.app.state.tenant_manager
    return await manager.get_connection(tenant["id"])
```

### Pattern 2: Background Embedding + Entity Extraction
**What:** Return memory ID immediately, run embedding generation and entity extraction in background.
**When to use:** POST /v1/memory -- embedding should never block the write response (MEM-13).
**Example:**
```python
from fastapi import BackgroundTasks

@router.post("/v1/memory")
async def create_memory(
    body: MemoryCreate,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant),
    conn = Depends(get_tenant_conn),
):
    # 1. Dedup check (text_hash is sync, fast)
    # 2. Insert memory row (no embedding yet)
    # 3. Return memory ID immediately
    # 4. Queue background work
    background_tasks.add_task(generate_and_store_embedding, tenant["id"], memory_id, body.text)
    background_tasks.add_task(extract_and_store_entities, tenant["id"], memory_id, body.text)
    return {"id": memory_id, "status": "created"}
```

### Pattern 3: Per-Tenant Vector Index Manager
**What:** Lazy-load hnswlib indexes per tenant, cache in memory with LRU eviction (mirroring TenantDBManager pattern).
**When to use:** Any vector operation (search, add, dedup similarity check).
**Example:**
```python
class TenantIndexManager:
    """Per-tenant hnswlib index cache. Indexes are lazy-loaded from disk."""
    def __init__(self, data_dir: Path, dim: int = 1024, max_cached: int = 20):
        self._indexes: OrderedDict[str, hnswlib.Index] = OrderedDict()
        self._id_maps: dict[str, list[str]] = {}
        self.data_dir = data_dir
        self.dim = dim
        self.max_cached = max_cached
        self._lock = asyncio.Lock()

    async def get_index(self, tenant_id: str) -> tuple[hnswlib.Index, list[str]]:
        async with self._lock:
            if tenant_id in self._indexes:
                self._indexes.move_to_end(tenant_id)
                return self._indexes[tenant_id], self._id_maps[tenant_id]
            # Evict LRU if needed
            if len(self._indexes) >= self.max_cached:
                evicted_id, evicted_idx = self._indexes.popitem(last=False)
                self._save_index(evicted_id, evicted_idx, self._id_maps.pop(evicted_id))
            # Load or create
            index, id_map = self._load_or_create(tenant_id)
            self._indexes[tenant_id] = index
            self._id_maps[tenant_id] = id_map
            return index, id_map
```

### Pattern 4: Metadata Filtering Before Vector Scoring (RETR-05)
**What:** Apply SQL WHERE clause for metadata/scope filters FIRST, then intersect with vector results.
**When to use:** POST /v1/memory/search with filters.
**Why:** hnswlib returns global top-K; filtering after may remove all results. Filter candidate set first.
**Example:**
```python
async def search_memories(conn, index_manager, tenant_id, query, filters):
    # Step 1: Get candidate IDs from SQL with metadata filters
    sql_conditions = ["is_deleted = 0"]
    params = []
    if filters.user_id:
        sql_conditions.append("user_id = ?")
        params.append(filters.user_id)
    if filters.agent_id:
        sql_conditions.append("agent_id = ?")
        params.append(filters.agent_id)
    # ... more filters
    rows = await conn.execute_fetchall(
        f"SELECT id FROM memories WHERE {' AND '.join(sql_conditions)}", params
    )
    candidate_ids = {row["id"] for row in rows}

    # Step 2: Vector search with broader top-K
    index, id_map = await index_manager.get_index(tenant_id)
    # ... knn_query, filter to candidates, apply decay, return ranked
```

### Anti-Patterns to Avoid
- **Global hnswlib index for all tenants:** Each tenant MUST have an isolated index file. Mixing tenants in one index leaks data across tenants.
- **Blocking on embedding in write path:** MEM-13 explicitly requires async embedding. Never call Fireworks.ai synchronously in the POST handler.
- **Storing embeddings only in hnswlib:** Also store in the `embedding BLOB` column for persistence. hnswlib index is a cache that can be rebuilt from the BLOB column.
- **Using `conn.execute()` without row_factory:** Phase 1 already sets `conn.row_factory = aiosqlite.Row` in TenantDBManager -- use dict-like access consistently.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Rate limiting | Custom sliding window | slowapi with custom key_func | Handles edge cases, Redis-ready for scale |
| HTTP retries | Custom retry loop | httpx with tenacity or manual backoff | httpx has built-in timeout, but add exponential backoff for 429s |
| Vector search | Custom cosine similarity on all rows | hnswlib | O(log n) vs O(n), handles 100K+ vectors efficiently |
| Text hashing | Custom normalization | `hashlib.sha256(text.strip().lower().encode()).hexdigest()[:32]` | ZimMemory's proven approach, handles whitespace/case |
| UUID generation | Custom ID schemes | `uuid.uuid4()` for memory IDs | Phase 1 uses UUID for tenant IDs, stay consistent |

**Key insight:** ZimMemory already solved all these problems. Port the logic, don't reinvent. The only new challenge is making it async and multi-tenant.

## Common Pitfalls

### Pitfall 1: hnswlib Thread Safety
**What goes wrong:** hnswlib's `add_items` and `knn_query` are NOT thread-safe when called concurrently. Pickle serialization is also not thread-safe with concurrent adds.
**Why it happens:** hnswlib is C++ with Python bindings; no GIL protection for internal state.
**How to avoid:** Use an `asyncio.Lock` per index (already shown in TenantIndexManager pattern). All index mutations (add, mark_deleted, save) go through the lock. Reads (knn_query) can be concurrent IF no writes are happening -- but simplest to lock all ops.
**Warning signs:** Segfaults, corrupted search results, index save failures.

### Pitfall 2: hnswlib max_elements Must Be Pre-Allocated
**What goes wrong:** hnswlib requires `max_elements` at `init_index()` time. If you exceed it, `add_items` raises an error.
**Why it happens:** HNSW data structure pre-allocates internal arrays.
**How to avoid:** Start with a reasonable default (e.g., 10,000). When approaching capacity, use `resize_index(new_max)` to grow. ZimMemory uses `HNSW_MAX_ELEMENTS = 100000`. For multi-tenant, start smaller per tenant (10K) and grow.
**Warning signs:** RuntimeError on add_items after many inserts.

### Pitfall 3: Cosine Dedup Race Condition on Concurrent Writes
**What goes wrong:** Two concurrent POST /v1/memory requests with near-identical text both pass dedup check, both insert.
**Why it happens:** text_hash check and similarity check happen before insert; no row-level locking.
**How to avoid:** Use text_hash as a UNIQUE constraint (or check + insert in a single transaction). For cosine dedup, accept that it's best-effort -- text_hash catches exact dupes, cosine catches near-dupes with a small race window.
**Warning signs:** Duplicate memories appearing despite dedup being enabled.

### Pitfall 4: Fireworks.ai Rate Limits (600 RPM shared)
**What goes wrong:** Embedding requests get 429'd, no retry, memories stored without embeddings.
**Why it happens:** Fireworks.ai free tier is 600 RPM across ALL API calls (inference + embeddings), shared across API keys.
**How to avoid:** Per-tenant rate limiter BEFORE Fireworks calls (MEM-12). Implement circuit breaker pattern (ZimMemory has this: `_fireworks_trip()` with cooldown). Queue embeddings and process in batches to reduce request count. Store failed embedding requests for retry.
**Warning signs:** 429 responses, circuit breaker tripping frequently, memories without embeddings.

### Pitfall 5: aiosqlite Row Factory Access
**What goes wrong:** Trying to access `row["column"]` when row_factory is not set, getting tuple index access instead.
**Why it happens:** aiosqlite default is tuple rows.
**How to avoid:** Phase 1's TenantDBManager already sets `conn.row_factory = aiosqlite.Row`. Always use dict-style access. But be careful: `aiosqlite.Row` supports `row["col"]` but NOT `row.col` attribute access.
**Warning signs:** TypeError on row access, confusing tuple vs dict semantics.

### Pitfall 6: Background Task Failures Are Silent
**What goes wrong:** Entity extraction or embedding generation fails in BackgroundTasks, no error visible.
**Why it happens:** FastAPI BackgroundTasks swallows exceptions (no retry, no logging by default).
**How to avoid:** Wrap all background task functions in try/except with explicit logging. Consider storing a `status` field on memories: "pending_embedding", "embedded", "embedding_failed" for observability.
**Warning signs:** Memories with NULL embedding BLOBs that never get populated.

## Code Examples

### Memory Write with Dedup (ported from ZimMemory)
```python
# Source: ZimMemory server.py _add_single_memory() (line ~2855)
import hashlib
import time
import uuid

def text_hash(text: str) -> str:
    """Deterministic hash for exact dedup. Matches ZimMemory implementation."""
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()[:32]

async def create_memory(
    conn: aiosqlite.Connection,
    text: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> dict:
    th = text_hash(text)

    # Exact dedup via text_hash
    async with conn.execute(
        "SELECT id FROM memories WHERE text_hash = ? AND is_deleted = 0", (th,)
    ) as cur:
        existing = await cur.fetchone()
    if existing:
        return {"id": existing["id"], "status": "duplicate"}

    memory_id = str(uuid.uuid4())
    now = int(time.time())
    await conn.execute(
        """INSERT INTO memories
           (id, text, text_hash, user_id, agent_id, session_id,
            metadata, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, text, th, user_id, agent_id, session_id,
         json.dumps(metadata or {}), now, now),
    )
    await conn.commit()
    return {"id": memory_id, "status": "created"}
```

### Fireworks Embedding Client (async, with circuit breaker)
```python
# Source: ZimMemory zim_upgrade_v12.py _fireworks_embed() adapted to async httpx
import httpx
import asyncio
import time
import numpy as np

class EmbeddingClient:
    """Async Fireworks.ai embedding client with circuit breaker and batching."""

    def __init__(self, api_key: str, model: str = "mixedbread-ai/mxbai-embed-large-v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.fireworks.ai/inference/v1/embeddings"
        self._client = httpx.AsyncClient(timeout=30.0)
        self._last_failure = 0.0
        self._cooldown = 120  # seconds
        self._lock = asyncio.Lock()

    def _available(self) -> bool:
        if not self.api_key:
            return False
        if self._last_failure == 0.0:
            return True
        if time.time() - self._last_failure > self._cooldown:
            self._last_failure = 0.0
            return True
        return False

    async def embed(self, texts: list[str], batch_size: int = 20) -> np.ndarray | None:
        if not self._available():
            return None
        all_embeddings = []
        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                resp = await self._client.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch},
                )
                if resp.status_code == 429:
                    self._last_failure = time.time()
                    return None
                resp.raise_for_status()
                data = resp.json()
                embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(embeddings)
            return np.array(all_embeddings, dtype=np.float32)
        except (httpx.ConnectError, httpx.TimeoutException):
            self._last_failure = time.time()
            return None
```

### Temporal Decay (ported from ZimMemory)
```python
# Source: ZimMemory server.py apply_decay() (line 776) + v11 reinforced_decay
import time

DECAY_HALF_LIFE_DAYS = 30

def apply_decay(score: float, created_at: int) -> float:
    """Apply time-decay: recent memories get a boost that halves every 30 days.
    Blend: 80% base score + 20% recency bonus."""
    age_days = (time.time() - created_at) / 86400
    decay_factor = 0.5 ** (age_days / DECAY_HALF_LIFE_DAYS)
    return score * 0.8 + score * decay_factor * 0.2
```

### Entity Extraction (regex, ported from ZimMemory)
```python
# Source: ZimMemory server.py extract_entities() (line 817)
# The regex approach is a fallback; ZimMemory v9+ uses LLM extraction as primary.
# For v1 of MemoraLabs, regex is sufficient and avoids LLM cost per write.
import re

def normalize_entity_name(name: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', name.lower()).strip()

# Key patterns to port:
# - Capitalized multi-word names (Person detection)
# - Known entity patterns (org names, locations)
# - Relation patterns ("X works at Y", "X met Y")
# ZimMemory has ~20 entity patterns and ~10 relation patterns in ENTITY_PATTERNS/RELATIONSHIP_PATTERNS
```

### Per-Tenant Rate Limiting with slowapi
```python
# Source: slowapi docs + ZimMemory RateLimiter pattern
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

def get_tenant_key(request: Request) -> str:
    """Rate limit by tenant_id (resolved from API key in deps)."""
    # Tenant is resolved in the dependency; use API key prefix as fallback
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    return api_key[:8] if api_key else get_remote_address(request)

limiter = Limiter(key_func=get_tenant_key)
# Applied per-route: @limiter.limit("60/minute")
```

## State of the Art

| Old Approach (ZimMemory) | New Approach (MemoraLabs) | Why |
|--------------------------|--------------------------|-----|
| Global `get_db()` returns sqlite3.Connection | `TenantDBManager.get_connection(tenant_id)` returns aiosqlite.Connection | Multi-tenant isolation |
| Synchronous `requests.post()` for embeddings | `httpx.AsyncClient.post()` with circuit breaker | Non-blocking, fits FastAPI async model |
| Single global hnswlib index | Per-tenant index files with LRU cache | Tenant data isolation |
| Threading locks | asyncio.Lock | Matches async architecture |
| Embedding inline during write | FastAPI BackgroundTasks | MEM-13: never block write response |
| Global rate limiter instance | slowapi per-tenant key function | Multi-tenant fairness |

**Key difference from ZimMemory:** ZimMemory is synchronous Flask-style code running in threads. MemoraLabs is fully async. Every ZimMemory function that touches I/O (DB, HTTP, file) needs an async port.

## Porting Guide: ZimMemory to MemoraLabs

### What to Port (with adaptations)
| ZimMemory Function | Port to | Adaptation |
|-------------------|---------|------------|
| `_add_single_memory()` | `app/services/memory.py` | async, pass conn, use uuid4 not gen_id |
| `text_hash()` | `app/services/dedup.py` | Direct port, no changes needed |
| `VectorEngine` (class) | `app/services/vector_index.py` | Per-tenant, asyncio.Lock, lazy-load |
| `VectorEngine.embed()` | `app/services/embedding.py` | httpx.AsyncClient, circuit breaker |
| `extract_entities()` | `app/services/entity_extraction.py` | Direct port of regex patterns |
| `extract_relations()` | `app/services/entity_extraction.py` | Direct port of regex patterns |
| `find_or_create_entity()` | `app/services/entity_extraction.py` | async, pass conn |
| `process_graph()` | `app/services/entity_extraction.py` | async, pass conn, background task |
| `apply_decay()` | `app/services/decay.py` | Direct port, pure math |
| `hybrid_search()` | `app/services/search.py` | async, metadata-first filtering |
| `RateLimiter` | slowapi | Replace custom with library |

### What NOT to Port
- TF-IDF engine (vector-only for v1, simpler)
- Webhook system (out of scope for Phase 2)
- WebSocket layer (not needed)
- Task queue system (not needed)
- v13/v14/v15 advanced features (future phases)
- RRF merge (vector-only for v1; add TF-IDF hybrid later)
- RAG module (separate concern)

## hnswlib API Reference (from ZimMemory usage)

```python
import hnswlib
import numpy as np

# Create index
index = hnswlib.Index(space="cosine", dim=1024)
index.init_index(max_elements=10000, ef_construction=200, M=16)
index.set_ef(200)  # Search-time accuracy parameter

# Add items (positions are integer IDs, NOT memory UUIDs)
# Maintain a separate id_map: list[str] mapping position -> memory_id
vectors = np.array([...], dtype=np.float32)  # shape (n, 1024)
positions = np.arange(len(vectors))
index.add_items(vectors, positions)

# Search
query_vec = np.array([...], dtype=np.float32).reshape(1, -1)
positions, distances = index.knn_query(query_vec, k=10)
# distances are cosine distances (0 = identical), similarity = 1 - distance
# positions[0] and distances[0] are arrays for the first query

# Delete (marks as deleted, doesn't remove)
index.mark_deleted(position_int)

# Persist
index.save_index("path/to/index.bin")
# Load (MUST re-init with same dim/space, or just load directly)
index.load_index("path/to/index.bin", max_elements=10000)

# Resize (when approaching max_elements)
index.resize_index(new_max_elements)
```

**Key facts:**
- `space="cosine"` returns distances, not similarities. `similarity = 1.0 - distance`.
- `ef` parameter controls search accuracy vs speed. Higher = more accurate, slower. 200 is ZimMemory's choice.
- `M` parameter controls graph connectivity. 16 is standard. Higher = better recall, more memory.
- `ef_construction` controls build quality. 200 is ZimMemory's choice.
- Index must be saved explicitly; no auto-persist.
- `max_elements` must be set at init; use `resize_index()` to grow.

## Fireworks.ai API Reference

```
POST https://api.fireworks.ai/inference/v1/embeddings
Headers:
  Authorization: Bearer <API_KEY>
  Content-Type: application/json
Body:
  {"model": "mixedbread-ai/mxbai-embed-large-v1", "input": ["text1", "text2"]}
Response:
  {"data": [{"embedding": [0.1, 0.2, ...], "index": 0}, ...], "model": "...", "usage": {...}}

Dimensions: 1024 (mxbai-embed-large-v1)
Rate limit: 600 RPM shared across all API calls (free tier)
Batch size: Up to 20 texts per request (ZimMemory's proven batch size)
Timeout: (5s connect, 30s read) per ZimMemory settings
```

## Open Questions

1. **Cosine dedup timing relative to async embedding**
   - What we know: MEM-10 requires cosine > 0.95 blocks insert. MEM-13 requires embedding is async.
   - What's unclear: If embedding is async, cosine dedup can't check similarity at write time (embedding doesn't exist yet).
   - Recommendation: Use text_hash for immediate exact dedup (blocks write). Run cosine dedup as a background post-embedding check -- if near-duplicate found, soft-delete the new memory and log it. Alternative: do a quick synchronous embedding for dedup check only, then store result, but this contradicts MEM-13.

2. **hnswlib index growth strategy per tenant**
   - What we know: max_elements must be pre-set. ZimMemory uses 100K globally.
   - What's unclear: Optimal per-tenant starting size and growth factor.
   - Recommendation: Start at 10K per tenant, resize at 80% capacity (8K items) to 2x. Free plan has 1000 memory limit, so 10K is generous headroom.

3. **Entity extraction cost vs quality**
   - What we know: ZimMemory v9+ deprecated regex extraction in favor of LLM extraction. Regex is still the fallback.
   - What's unclear: Is regex extraction good enough for MemoraLabs v1?
   - Recommendation: Use regex for v1. It's free, fast, and good enough for detecting named entities in simple text. LLM extraction can be a premium feature later.

## Sources

### Primary (HIGH confidence)
- ZimMemory v15 server.py (6,893 lines) -- direct code inspection via SSH on Mac Mini 10.0.0.209
- ZimMemory zim_upgrade_v12.py -- Fireworks.ai embedding implementation
- MemoraLabs Phase 1 codebase -- app/db/tenant.py, app/db/manager.py, app/config.py, app/main.py
- [Fireworks.ai Embedding Docs](https://docs.fireworks.ai/guides/querying-embeddings-models) -- API format, model names

### Secondary (MEDIUM confidence)
- [hnswlib GitHub](https://github.com/nmslib/hnswlib) -- Python API, persistence, thread safety
- [slowapi GitHub](https://github.com/laurentS/slowapi) -- FastAPI rate limiting
- [FastAPI BackgroundTasks docs](https://fastapi.tiangolo.com/tutorial/background-tasks/) -- async task pattern

### Tertiary (LOW confidence)
- Fireworks.ai rate limits (600 RPM) -- from WebSearch, not from official rate limits page

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- ZimMemory provides proven reference, Phase 1 infrastructure is solid
- Architecture: HIGH -- Patterns directly derived from working ZimMemory code + Phase 1 design
- Pitfalls: HIGH -- Identified from real ZimMemory production experience (3,395 memories, months of operation)
- Fireworks rate limits: MEDIUM -- WebSearch sourced, consistent with observed behavior in ZimMemory

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (stable domain, unlikely to change)
