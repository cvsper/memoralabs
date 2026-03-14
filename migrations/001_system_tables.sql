-- System DB: {data_dir}/system.db
-- Migration 001: system tables (tenants, api_keys, usage_log, schema_version)

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

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_tenant ON usage_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_usage_log_created ON usage_log(created_at);

INSERT OR IGNORE INTO schema_version (version, applied_at, description)
VALUES (1, strftime('%s', 'now'), '001_system_tables');
