"""
TenantDBManager — async connection pool with LRU eviction for per-tenant SQLite DBs.

Responsibilities:
- Open aiosqlite connections with WAL mode, NORMAL sync, foreign_keys ON, cache_size 2000
- Pool connections in an OrderedDict (LRU order) up to max_connections
- Evict LRU connection (close it) when pool is full
- Validate tenant_id is a lowercase UUID to prevent path traversal
- Create new tenant DB files and apply schema via init_tenant_db

The schema module (tenant.py) knows WHAT goes in a tenant DB.
This module knows WHERE files live and HOW connections are managed.
"""

import asyncio
import re
from collections import OrderedDict
from pathlib import Path

import aiosqlite

from app.db.tenant import init_tenant_db

# UUID v4 pattern — lowercase hex and dashes only
_UUID_RE = re.compile(
    r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
)


class TenantDBManager:
    """Async LRU connection pool for per-tenant SQLite databases.

    Each tenant gets an isolated .db file under {data_dir}/tenants/.
    Connections are cached up to max_connections; LRU entry is closed and
    evicted when the pool is full.

    Thread safety: all pool mutations are guarded by a single asyncio.Lock.
    """

    def __init__(self, data_dir: Path, max_connections: int = 50) -> None:
        self.data_dir = data_dir
        self.max_connections = max_connections
        self._pool: OrderedDict[str, aiosqlite.Connection] = OrderedDict()
        self._lock = asyncio.Lock()
        # Ensure the tenant subdirectory exists at construction time
        (data_dir / "tenants").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_tenant_id(self, tenant_id: str) -> None:
        """Raise ValueError if tenant_id is not a lowercase UUID.

        This is the primary path-traversal guard: only UUIDs are accepted,
        so values like '../../etc/passwd' are rejected before any file I/O.
        """
        if not _UUID_RE.match(tenant_id):
            raise ValueError("Invalid tenant_id format")

    def _tenant_db_path(self, tenant_id: str) -> Path:
        """Return the absolute .db path for a tenant, after validation."""
        self._validate_tenant_id(tenant_id)
        return self.data_dir / "tenants" / f"{tenant_id}.db"

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_connection(self, tenant_id: str) -> aiosqlite.Connection:
        """Return a cached connection for tenant_id, opening one if needed.

        LRU semantics: cache hit moves the entry to the end (most-recently-used).
        On cache miss, if the pool is full the least-recently-used entry is
        evicted (connection closed) before the new one is inserted.
        """
        async with self._lock:
            if tenant_id in self._pool:
                # Cache hit — promote to MRU position
                self._pool.move_to_end(tenant_id)
                return self._pool[tenant_id]

            # Cache miss — evict LRU if at capacity
            if len(self._pool) >= self.max_connections:
                _evicted_id, evicted_conn = self._pool.popitem(last=False)
                await evicted_conn.close()

            # Open a new connection with required PRAGMAs
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
        """Create a new tenant DB file, apply schema, and return the path.

        Raises ValueError if the DB file already exists (idempotency guard).
        """
        db_path = self._tenant_db_path(tenant_id)
        if db_path.exists():
            raise ValueError(f"Tenant DB already exists: {tenant_id}")

        conn = await self.get_connection(tenant_id)
        await init_tenant_db(conn)
        return db_path

    async def close_connection(self, tenant_id: str) -> None:
        """Close and remove the pooled connection for tenant_id, if present."""
        async with self._lock:
            if tenant_id in self._pool:
                await self._pool[tenant_id].close()
                del self._pool[tenant_id]

    async def close_all(self) -> None:
        """Close every pooled connection and clear the pool."""
        async with self._lock:
            for conn in self._pool.values():
                await conn.close()
            self._pool.clear()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def pool_size(self) -> int:
        """Current number of open connections in the pool."""
        return len(self._pool)
