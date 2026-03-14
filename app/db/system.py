import time
from pathlib import Path
from typing import Optional

import aiosqlite

SYSTEM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    plan TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active',
    memory_limit INTEGER NOT NULL DEFAULT 1000,
    created_at INTEGER NOT NULL,
    updated_at INTEGER
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    name TEXT DEFAULT 'default',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL,
    description TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_tenant ON usage_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log(created_at);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, strftime('%s', 'now'), '001_system_tables');
"""


async def init_system_db(data_dir: Path) -> aiosqlite.Connection:
    """Create data_dir if needed, open system.db, configure pragmas, run schema."""
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "system.db"
    conn = await aiosqlite.connect(str(db_path))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SYSTEM_SCHEMA_SQL)
    await conn.commit()
    return conn


async def create_tenant(
    conn: aiosqlite.Connection,
    tenant_id: str,
    name: str,
    email: str,
    plan: str = "free",
    memory_limit: int = 1000,
) -> dict:
    """Insert a new tenant and return the row as a dict."""
    now = int(time.time())
    await conn.execute(
        """
        INSERT INTO tenants (id, name, email, plan, status, memory_limit, created_at)
        VALUES (?, ?, ?, ?, 'active', ?, ?)
        """,
        (tenant_id, name, email, plan, memory_limit, now),
    )
    await conn.commit()
    async with conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)) as cur:
        row = await cur.fetchone()
    return dict(row)


async def create_api_key(
    conn: aiosqlite.Connection,
    key_id: str,
    tenant_id: str,
    key_hash: str,
    key_prefix: str,
    name: str = "default",
) -> dict:
    """Insert a new API key and return the row as a dict."""
    now = int(time.time())
    await conn.execute(
        """
        INSERT INTO api_keys (id, tenant_id, key_hash, key_prefix, name, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (key_id, tenant_id, key_hash, key_prefix, name, now),
    )
    await conn.commit()
    async with conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)) as cur:
        row = await cur.fetchone()
    return dict(row)


async def get_tenant_by_key_hash(
    conn: aiosqlite.Connection,
    key_hash: str,
) -> Optional[dict]:
    """
    Resolve an API key hash to its tenant.
    Returns the tenant row as a dict, or None if not found / inactive / suspended.
    """
    async with conn.execute(
        """
        SELECT t.*
        FROM api_keys k
        JOIN tenants t ON k.tenant_id = t.id
        WHERE k.key_hash = ?
          AND k.is_active = 1
          AND t.status = 'active'
        """,
        (key_hash,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return dict(row)


async def update_key_last_used(conn: aiosqlite.Connection, key_hash: str) -> None:
    """Update last_used_at timestamp for the API key. Fire-and-forget."""
    now = int(time.time())
    await conn.execute(
        "UPDATE api_keys SET last_used_at = ? WHERE key_hash = ? AND is_active = 1",
        (now, key_hash),
    )
    await conn.commit()


async def log_usage(
    conn: aiosqlite.Connection,
    tenant_id: str,
    operation: str,
    endpoint: str,
    status_code: int,
    latency_ms: Optional[int] = None,
    tokens_used: int = 0,
) -> None:
    """Insert a usage log entry."""
    now = int(time.time())
    await conn.execute(
        """
        INSERT INTO usage_log
            (tenant_id, operation, endpoint, status_code, latency_ms, tokens_used, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tenant_id, operation, endpoint, status_code, latency_ms, tokens_used, now),
    )
    await conn.commit()
