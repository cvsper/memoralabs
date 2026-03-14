# Phase 1: Foundation - Research

**Researched:** 2026-03-14
**Domain:** Multi-tenant SQLite infrastructure on FastAPI with Render deployment
**Confidence:** HIGH

## Summary

Phase 1 builds the infrastructure scaffold for MemoraLabs: a system database tracking tenants and API keys, per-tenant SQLite databases with schemas ported from ZimMemory v15, a connection pool manager with LRU eviction, and a health endpoint with keep-alive cron. The existing ZimMemory codebase is a single-tenant FastAPI application using SQLite with WAL mode -- the core schema is well-understood and the port is straightforward.

The critical architectural decision -- SQLite-per-tenant instead of shared DB with tenant_id columns -- is the correct choice for this product. It provides hard isolation (no query bugs can leak data), simple backup/restore per tenant, independent WAL journals, and easy deletion (rm the file). The tradeoff is connection management overhead, which the TenantDBManager with LRU eviction solves.

**Primary recommendation:** Build a clean FastAPI project with `aiosqlite` for async SQLite access, a custom `TenantDBManager` class using `OrderedDict` for LRU eviction of connection handles, and all data paths rooted at the Render persistent disk mount (`/data`).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.115+ | HTTP framework | Already used by ZimMemory; async-native, auto OpenAPI docs |
| uvicorn | 0.34+ | ASGI server | Standard FastAPI production server |
| aiosqlite | 0.21+ | Async SQLite access | Official asyncio bridge to sqlite3; thread-per-connection model |
| pydantic | 2.x | Request/response validation | Bundled with FastAPI; strict typing |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | 1.0+ | Environment variable loading | Local dev; Render uses native env vars |
| httpx | 0.27+ | Async HTTP client | Keep-alive cron, internal health checks |

### Not Needed Yet (Phase 1)
| Library | Phase | Why Deferred |
|---------|-------|-------------|
| hnswlib | Phase 2 | Vector index; no embeddings in Phase 1 |
| sentence-transformers | Phase 2 | Embedding model; no search in Phase 1 |
| fireworks-ai | Phase 2 | Cloud embeddings; no search in Phase 1 |

**Installation:**
```bash
pip install fastapi uvicorn[standard] aiosqlite pydantic python-dotenv httpx
```

## Architecture Patterns

### Recommended Project Structure
```
memoralabs/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, lifespan, health endpoint
│   ├── config.py             # Settings from env vars (DATA_DIR, etc.)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── system.py         # System DB schema + operations (tenants, api_keys, usage_log)
│   │   ├── tenant.py         # Tenant DB schema (memories, entities, relations)
│   │   └── manager.py        # TenantDBManager (LRU pool, WAL config, isolation)
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py        # Pydantic models for requests/responses
│   └── routers/
│       ├── __init__.py
│       └── health.py         # /health endpoint
├── tests/
│   ├── __init__.py
│   ├── test_system_db.py
│   ├── test_tenant_db.py
│   ├── test_manager.py
│   └── test_isolation.py
├── migrations/               # SQL migration files (numbered)
│   ├── 001_system_tables.sql
│   └── 002_tenant_tables.sql
├── render.yaml
├── requirements.txt
├── .env.example
└── README.md
```

### Pattern 1: TenantDBManager with LRU Connection Pool

**What:** A manager class that maintains a pool of open `aiosqlite` connections keyed by `tenant_id`, evicts least-recently-used connections when the pool exceeds a configurable max size, and ensures every connection has WAL mode and standard PRAGMAs set.

**When to use:** Every database operation that touches tenant data.

**Example:**
```python
# Source: Custom pattern based on aiosqlite docs + OrderedDict LRU
import aiosqlite
from collections import OrderedDict
from pathlib import Path

class TenantDBManager:
    def __init__(self, data_dir: Path, max_connections: int = 50):
        self.data_dir = data_dir
        self.max_connections = max_connections
        self._pool: OrderedDict[str, aiosqlite.Connection] = OrderedDict()
        self._lock = asyncio.Lock()

    def _tenant_db_path(self, tenant_id: str) -> Path:
        """Tenant DB files live at {data_dir}/tenants/{tenant_id}.db"""
        tenant_dir = self.data_dir / "tenants"
        tenant_dir.mkdir(parents=True, exist_ok=True)
        return tenant_dir / f"{tenant_id}.db"

    async def get_connection(self, tenant_id: str) -> aiosqlite.Connection:
        async with self._lock:
            if tenant_id in self._pool:
                # Move to end (most recently used)
                self._pool.move_to_end(tenant_id)
                return self._pool[tenant_id]

            # Evict LRU if at capacity
            if len(self._pool) >= self.max_connections:
                evict_id, evict_conn = self._pool.popitem(last=False)
                await evict_conn.close()

            # Open new connection with WAL mode
            db_path = self._tenant_db_path(tenant_id)
            conn = await aiosqlite.connect(str(db_path))
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=2000")
            await conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = aiosqlite.Row
            self._pool[tenant_id] = conn
            return conn

    async def create_tenant_db(self, tenant_id: str) -> Path:
        """Create a new tenant database with schema. Returns the DB path."""
        db_path = self._tenant_db_path(tenant_id)
        if db_path.exists():
            raise ValueError(f"Tenant DB already exists: {tenant_id}")
        conn = await self.get_connection(tenant_id)
        await self._init_tenant_schema(conn)
        return db_path

    async def close_all(self):
        async with self._lock:
            for conn in self._pool.values():
                await conn.close()
            self._pool.clear()
```

### Pattern 2: FastAPI Lifespan for Resource Management

**What:** Use FastAPI's `lifespan` context manager to initialize and tear down the system DB and TenantDBManager.

**Example:**
```python
# Source: FastAPI docs — lifespan events
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init system DB, create TenantDBManager
    app.state.system_db = await init_system_db(config.DATA_DIR)
    app.state.tenant_manager = TenantDBManager(
        data_dir=config.DATA_DIR,
        max_connections=config.MAX_TENANT_CONNECTIONS,
    )
    yield
    # Shutdown: close all connections
    await app.state.tenant_manager.close_all()
    await app.state.system_db.close()

app = FastAPI(title="MemoraLabs", lifespan=lifespan)
```

### Pattern 3: FastAPI Depends() for Tenant Context (Phase 3, but design for it now)

**What:** In Phase 3, auth middleware will resolve `Bearer token -> SHA-256 -> tenant_id` and inject the tenant's DB connection via `Depends()`. Phase 1 should structure code so this injection point is clean.

**Example (Phase 3 preview — design DB layer to accept tenant_id):**
```python
from fastapi import Depends, Request

async def get_tenant_context(request: Request) -> TenantContext:
    # Phase 3: resolve from Bearer token
    # Phase 1: not wired yet, but TenantDBManager.get_connection(tenant_id) is ready
    tenant_id = request.state.tenant_id  # set by auth middleware
    conn = await request.app.state.tenant_manager.get_connection(tenant_id)
    return TenantContext(tenant_id=tenant_id, conn=conn)
```

### Anti-Patterns to Avoid
- **Global DB connection:** ZimMemory uses `get_db()` returning a module-level connection. Multi-tenant requires per-tenant connections. Never use a global connection.
- **tenant_id column filtering:** Never put all tenants in one DB with WHERE clauses. A single bug leaks all data. SQLite-per-tenant is the correct isolation model.
- **Sync sqlite3 in async handlers:** Use `aiosqlite`, not `sqlite3` directly. Blocking the event loop kills throughput.
- **Storing DB files in `/tmp`:** Render's `/tmp` is ephemeral. All data must go under the persistent disk mount path.

## ZimMemory Schema Port

### Exact Schemas to Port (from ZimMemory v15 server.py)

**memories table** (core — port to every tenant DB):
```sql
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    user_id TEXT,
    agent_id TEXT,
    session_id TEXT,
    category TEXT,
    metadata TEXT DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER,
    access_count INTEGER DEFAULT 0,
    last_accessed INTEGER,
    is_deleted INTEGER DEFAULT 0,
    parent_id TEXT,
    expires_at INTEGER,
    is_pinned INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    shared_with TEXT DEFAULT '[]'
);
```

**entities table** (graph memory):
```sql
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER,
    description TEXT,
    aliases TEXT DEFAULT '[]',
    properties TEXT DEFAULT '{}',
    mention_count INTEGER DEFAULT 1,
    last_seen_at INTEGER
);
```

**relations table** (graph edges):
```sql
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    relationship TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    target_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    valid_from INTEGER,
    valid_until INTEGER,
    confidence REAL DEFAULT 1.0,
    document_id TEXT,
    properties TEXT DEFAULT '{}',
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);
```

**feedback table** (retrieval feedback — also per-tenant):
```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    feedback TEXT,
    reason TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);
```

### Columns to Strip (not needed for MemoraLabs v1)
The following ZimMemory tables are NOT ported in Phase 1 (agent-communication specific):
- `message_queue` — WebSocket messaging (internal ZimMemory feature)
- `ws_audit_log` — WebSocket audit (internal)
- `ws_metrics` — WebSocket metrics (internal)
- `ws_tasks` / `ws_task_deps` / `ws_task_history` — Task queue (internal)
- `agent_messages` — Agent messaging (internal)
- `documents` / `entity_mentions` / `extraction_queue` — RAG module (Phase 2+ if needed)

### System Database Schema (new — not from ZimMemory)

```sql
-- System DB: {data_dir}/system.db
-- Tracks tenants, API keys, and usage

CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,              -- UUID
    name TEXT NOT NULL,               -- display name / org name
    email TEXT NOT NULL UNIQUE,       -- signup email
    plan TEXT NOT NULL DEFAULT 'free', -- free, pro, enterprise
    status TEXT NOT NULL DEFAULT 'active', -- active, suspended, deleted
    memory_limit INTEGER NOT NULL DEFAULT 1000, -- max memories
    created_at INTEGER NOT NULL,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,              -- UUID
    tenant_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,    -- SHA-256 of the plaintext key
    key_prefix TEXT NOT NULL,         -- first 8 chars for identification (e.g. "ml_live_a1b2c3d4")
    name TEXT DEFAULT 'default',      -- human label
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    operation TEXT NOT NULL,          -- store, search, delete, etc.
    endpoint TEXT NOT NULL,           -- /v1/memory, /v1/memory/search, etc.
    status_code INTEGER NOT NULL,
    latency_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,   -- embedding tokens consumed
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_tenant ON usage_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log(created_at);
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async SQLite | Custom threading wrapper | `aiosqlite` | Battle-tested; handles thread safety, cursor management |
| Request validation | Manual dict parsing | Pydantic models via FastAPI | Auto-validation, error messages, OpenAPI schema generation |
| Health check format | Custom JSON builder | Simple dict return with FastAPI | No library needed; keep it minimal |
| Environment config | os.environ everywhere | `pydantic-settings` or simple config module | Centralized, typed, with defaults |
| Connection pool LRU | Custom doubly-linked list | `collections.OrderedDict` | Built-in Python; `move_to_end()` and `popitem(last=False)` give O(1) LRU |

**Key insight:** Phase 1 is infrastructure plumbing. No complex third-party libraries needed beyond FastAPI + aiosqlite. The value is in correct schema design and clean isolation, not library selection.

## Common Pitfalls

### Pitfall 1: WAL Mode Not Set on Every Connection Open
**What goes wrong:** WAL mode is a per-connection pragma in SQLite. If you open a connection without setting it, that connection uses the default rollback journal, causing contention with WAL-mode connections.
**Why it happens:** Developers set WAL once during DB creation and assume it persists.
**How to avoid:** Set `PRAGMA journal_mode=WAL` on EVERY new connection in `TenantDBManager.get_connection()`. WAL mode does persist on the file, but setting it explicitly ensures correctness even if the `-wal` file is deleted.
**Warning signs:** Random "database is locked" errors under concurrent access.

### Pitfall 2: Forgetting to Close Evicted Connections
**What goes wrong:** LRU eviction removes the connection from the pool dict but doesn't call `conn.close()`. Leaked file descriptors accumulate. SQLite has a default limit of ~1000 open files.
**Why it happens:** `OrderedDict.popitem()` returns the value but doesn't trigger cleanup.
**How to avoid:** Always `await conn.close()` on the evicted connection before discarding. Add a `close_all()` method called during shutdown.
**Warning signs:** "too many open files" OS errors after running for a while.

### Pitfall 3: Race Conditions in Async Connection Pool
**What goes wrong:** Two concurrent requests for the same tenant_id both see a cache miss, both open connections, one overwrites the other in the pool, and the overwritten connection leaks.
**Why it happens:** No lock around pool access.
**How to avoid:** Use `asyncio.Lock()` around the entire get-or-create logic in `get_connection()`.
**Warning signs:** Connection count slowly grows beyond max_connections.

### Pitfall 4: Render Persistent Disk Not Available During Build
**What goes wrong:** Build step tries to initialize the database, but the persistent disk isn't mounted during `pip install` / build phase.
**Why it happens:** Render only mounts persistent disks at runtime, not during build or pre-deploy commands.
**How to avoid:** All DB initialization must happen at runtime (in FastAPI lifespan), never in build scripts. The `startCommand` runs with the disk mounted.
**Warning signs:** Build succeeds but data disappears on deploy.

### Pitfall 5: Path Injection via Tenant ID
**What goes wrong:** A malicious tenant_id like `../../etc/passwd` causes the DB file to be created outside the data directory.
**Why it happens:** String concatenation of tenant_id into file paths without validation.
**How to avoid:** Validate tenant_id is a UUID (hex chars + dashes only). Use `Path.resolve()` and verify the resolved path is still under `data_dir`.
**Warning signs:** Files appearing in unexpected directories.

### Pitfall 6: aiosqlite Connection Not Committed
**What goes wrong:** Writes succeed but data disappears on connection close or next read.
**Why it happens:** aiosqlite does not auto-commit. You must call `await conn.commit()` after writes.
**How to avoid:** Use explicit `await conn.commit()` after write operations, or use `async with conn.execute() ... conn.commit()` patterns.
**Warning signs:** Writes return success but subsequent reads show stale data.

## Code Examples

### Health Endpoint
```python
# Source: FastAPI docs + Render health check pattern
from fastapi import FastAPI
from datetime import datetime, timezone

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
    }
```

### System DB Initialization
```python
# Source: Custom — system DB setup with aiosqlite
import aiosqlite
from pathlib import Path

async def init_system_db(data_dir: Path) -> aiosqlite.Connection:
    db_path = data_dir / "system.db"
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(db_path))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = aiosqlite.Row

    # Run migrations
    await conn.executescript(SYSTEM_SCHEMA_SQL)
    await conn.commit()
    return conn
```

### Tenant DB Schema Initialization
```python
# Source: Ported from ZimMemory v15 init_db()
TENANT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    user_id TEXT,
    agent_id TEXT,
    session_id TEXT,
    category TEXT,
    metadata TEXT DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER,
    access_count INTEGER DEFAULT 0,
    last_accessed INTEGER,
    is_deleted INTEGER DEFAULT 0,
    parent_id TEXT,
    expires_at INTEGER,
    is_pinned INTEGER DEFAULT 0,
    priority INTEGER DEFAULT 0,
    tags TEXT DEFAULT '[]',
    shared_with TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER,
    description TEXT,
    aliases TEXT DEFAULT '[]',
    properties TEXT DEFAULT '{}',
    mention_count INTEGER DEFAULT 1,
    last_seen_at INTEGER
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_entity_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    relationship TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    target_name TEXT NOT NULL,
    target_type TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    valid_from INTEGER,
    valid_until INTEGER,
    confidence REAL DEFAULT 1.0,
    document_id TEXT,
    properties TEXT DEFAULT '{}',
    FOREIGN KEY (source_entity_id) REFERENCES entities(id),
    FOREIGN KEY (target_entity_id) REFERENCES entities(id),
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    feedback TEXT,
    reason TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(text_hash);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_deleted ON memories(is_deleted);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name_normalized);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_memory ON relations(memory_id);
"""
```

### Keep-Alive Cron (external)
```bash
# UptimeRobot or cron-job.org — free tier, ping every 10 minutes
# URL: https://memoralabs.onrender.com/health
# Method: GET
# Interval: 10 minutes
#
# Alternative: render.yaml cron job (Render native)
# Note: Render cron jobs are a separate service type, billed separately.
# UptimeRobot free tier is simpler and free.
```

### render.yaml Configuration
```yaml
services:
  - type: web
    name: memoralabs-api
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    plan: starter  # $7/mo — required for persistent disk
    disk:
      name: memoralabs-data
      mountPath: /data
      sizeGB: 1
    envVars:
      - key: DATA_DIR
        value: /data
      - key: PYTHON_VERSION
        value: "3.11"
```

### Config Module
```python
# app/config.py
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
MAX_TENANT_CONNECTIONS = int(os.environ.get("MAX_TENANT_CONNECTIONS", "50"))
PORT = int(os.environ.get("PORT", "8000"))
```

## Render Deployment Details

### Persistent Disk
- **Mount path for Python runtime:** Must be a subdirectory, NOT `/opt/render/project/src` itself. Use `/data` or `/opt/render/project/src/data`.
- **Recommended mount:** `/data` (clean, short, not under source tree)
- **Size:** Start at 1 GB (can increase later, cannot decrease)
- **Limitation:** Single instance only -- cannot scale horizontally with persistent disk
- **Limitation:** Disk NOT available during build or pre-deploy commands
- **Snapshots:** Automatic daily, 7-day retention

### File Layout on Disk
```
/data/                          # Render persistent disk mount
├── system.db                   # System database (tenants, api_keys, usage_log)
└── tenants/                    # Per-tenant databases
    ├── {uuid1}.db              # Tenant 1
    ├── {uuid1}.db-wal          # WAL journal (auto-created by SQLite)
    ├── {uuid1}.db-shm          # Shared memory (auto-created by SQLite)
    ├── {uuid2}.db
    └── ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flask + sync sqlite3 | FastAPI + aiosqlite | 2023+ | Non-blocking DB access, native async |
| functools.lru_cache for pool | OrderedDict with async lock | Current | Async-safe, explicit eviction control |
| Single shared DB + tenant_id | SQLite-per-tenant | Architectural decision | Hard isolation, simple backup/delete |
| DELETE journal mode | WAL mode | SQLite 3.7+ (2010) | Concurrent reads during writes |
| Gunicorn + sync workers | Uvicorn + async | FastAPI standard | Single process handles many concurrent requests |

## Open Questions

1. **Embedding column in tenant DB?**
   - What we know: ZimMemory stores embeddings in an hnswlib index file, not in SQLite. MemoraLabs will use Fireworks.ai for embeddings.
   - What's unclear: Should Phase 1 add an `embedding BLOB` column to `memories` table, or defer to Phase 2?
   - Recommendation: Add the column now (`embedding BLOB DEFAULT NULL`) so Phase 2 doesn't need a migration. But don't populate it in Phase 1.

2. **Migration strategy**
   - What we know: Phase 1 schemas are the initial tables. Future phases will add columns/tables.
   - What's unclear: Use a migration library (alembic) or hand-rolled numbered SQL files?
   - Recommendation: Hand-rolled numbered SQL files. Alembic is overkill for SQLite; numbered `.sql` files with a `schema_version` table are simpler and sufficient.

3. **Keep-alive: UptimeRobot vs Render cron?**
   - What we know: Render cron jobs are a separate billable service. UptimeRobot free tier supports 50 monitors with 5-minute intervals.
   - What's unclear: Whether Render cron can ping the same service's health endpoint.
   - Recommendation: Use UptimeRobot (free, external, also gives uptime monitoring). Configure for 10-minute intervals as specified.

## Sources

### Primary (HIGH confidence)
- ZimMemory v15 `server.py` on Mac Mini (10.0.0.209) -- full init_db() schema, get_db() pattern, all table definitions read via SSH
- [Render Persistent Disks docs](https://render.com/docs/disks) -- mount paths, limitations, single-instance constraint
- [Render Blueprint YAML Reference](https://render.com/docs/blueprint-spec) -- render.yaml disk configuration syntax

### Secondary (MEDIUM confidence)
- [MergeBoard - Multitenancy with FastAPI](https://mergeboard.com/blog/6-multitenancy-fastapi-sqlalchemy-postgresql/) -- FastAPI multi-tenant patterns (PostgreSQL-focused but patterns apply)
- [Multi-Tenant Design with FastAPI (2026)](https://blog.greeden.me/en/2026/03/10/introduction-to-multi-tenant-design-with-fastapi-practical-patterns-for-tenant-isolation-authorization-database-strategy-and-audit-logs/) -- Depends() injection, tenant context patterns
- [aiosqlite GitHub](https://github.com/omnilib/aiosqlite) -- async SQLite bridge, thread-per-connection model
- [aiosqlitepool GitHub](https://github.com/slaily/aiosqlitepool) -- connection pooling patterns for async SQLite
- [FastAPI Health Check Patterns](https://www.index.dev/blog/how-to-implement-health-check-in-python) -- liveness/readiness separation

### Tertiary (LOW confidence)
- None -- all claims verified against primary or secondary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- FastAPI + aiosqlite is exactly what ZimMemory already uses; well-documented
- Architecture: HIGH -- SQLite-per-tenant is a locked decision; patterns verified against official docs
- Schema port: HIGH -- Read directly from production ZimMemory v15 server.py via SSH
- Render deployment: HIGH -- Verified against official Render docs (mount paths, limitations, YAML syntax)
- Pitfalls: HIGH -- Derived from documented SQLite/aiosqlite behaviors and Render constraints

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (stable domain -- SQLite, FastAPI, and Render don't change fast)
