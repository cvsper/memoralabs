"""
Tenant DB schema module.

Defines the per-tenant SQLite schema (memories, entities, relations, feedback,
schema_version) ported from ZimMemory v15, with an embedding BLOB column added
to memories for Phase 2 readiness.

This module is responsible for WHAT goes into a tenant DB.
The TenantDBManager (manager.py) is responsible for WHERE and HOW connections
are opened and pooled. Separation is intentional.

Usage:
    conn = await aiosqlite.connect(db_path)
    await init_tenant_db(conn)
"""

import aiosqlite

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
    shared_with TEXT DEFAULT '[]',
    embedding BLOB DEFAULT NULL
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

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER,
    description TEXT
);

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

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, strftime('%s', 'now'), '002_tenant_tables');
"""


async def init_tenant_db(conn: aiosqlite.Connection) -> None:
    """Apply the tenant schema to an already-open aiosqlite connection.

    Does NOT open the connection — caller (TenantDBManager) owns connection
    lifecycle. Applies all DDL idempotently via CREATE TABLE IF NOT EXISTS.

    Args:
        conn: An open aiosqlite.Connection with WAL mode and foreign_keys
              already configured by the caller.
    """
    await conn.executescript(TENANT_SCHEMA_SQL)
    await conn.commit()
