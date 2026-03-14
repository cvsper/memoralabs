-- Migration: 002_tenant_tables
-- Per-tenant schema: memories, entities, relations, feedback, schema_version
-- Ported from ZimMemory v15 with embedding BLOB column added for Phase 2

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

-- Indexes for memories
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);
CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(text_hash);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_deleted ON memories(is_deleted);

-- Indexes for entities
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name_normalized);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);

-- Indexes for relations
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_memory ON relations(memory_id);

-- Seed schema version
INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, strftime('%s', 'now'), '002_tenant_tables');
