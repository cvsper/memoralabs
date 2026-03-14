"""
Unit tests for TenantDBManager.

Covers: connection caching, LRU eviction (with close), WAL/foreign-key
pragma enforcement, path traversal protection, tenant DB creation, and
clean shutdown.
"""

import pytest
import pytest_asyncio

from app.db.manager import TenantDBManager

VALID_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
VALID_UUID_2 = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
VALID_UUID_3 = "c3d4e5f6-a7b8-9012-cdef-012345678902"


@pytest_asyncio.fixture
async def manager(tmp_path):
    """Provide a fresh TenantDBManager backed by a temp directory."""
    mgr = TenantDBManager(data_dir=tmp_path)
    yield mgr
    await mgr.close_all()


# ------------------------------------------------------------------
# Tenant DB creation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tenant_db(manager, tmp_path):
    """create_tenant_db should create the .db file and return its path."""
    path = await manager.create_tenant_db(VALID_UUID)
    assert path.exists()
    assert str(path).endswith(f"tenants/{VALID_UUID}.db")


@pytest.mark.asyncio
async def test_create_tenant_db_duplicate(manager):
    """Creating the same tenant twice should raise ValueError."""
    await manager.create_tenant_db(VALID_UUID)
    with pytest.raises(ValueError):
        await manager.create_tenant_db(VALID_UUID)


# ------------------------------------------------------------------
# Connection reuse (LRU cache hit)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_connection_returns_same(manager):
    """Two calls for the same UUID should return the identical connection object."""
    conn_a = await manager.get_connection(VALID_UUID)
    conn_b = await manager.get_connection(VALID_UUID)
    assert conn_a is conn_b


# ------------------------------------------------------------------
# PRAGMA enforcement
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_connection_wal_mode(manager):
    """New connections must be in WAL journal mode."""
    conn = await manager.get_connection(VALID_UUID)
    async with conn.execute("PRAGMA journal_mode") as cur:
        row = await cur.fetchone()
    assert row[0] == "wal"


@pytest.mark.asyncio
async def test_get_connection_foreign_keys_on(manager):
    """New connections must have foreign_keys = ON (returns 1)."""
    conn = await manager.get_connection(VALID_UUID)
    async with conn.execute("PRAGMA foreign_keys") as cur:
        row = await cur.fetchone()
    assert row[0] == 1


# ------------------------------------------------------------------
# LRU eviction
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lru_eviction(tmp_path):
    """With max_connections=2, adding a 3rd tenant evicts the LRU entry."""
    mgr = TenantDBManager(data_dir=tmp_path, max_connections=2)
    try:
        conn_a = await mgr.get_connection(VALID_UUID)
        conn_b = await mgr.get_connection(VALID_UUID_2)
        assert mgr.pool_size == 2

        # Adding UUID_3 must evict UUID (the least-recently-used)
        await mgr.get_connection(VALID_UUID_3)
        assert mgr.pool_size == 2

        # Reconnecting UUID gives a NEW connection (evicted previously)
        conn_a_new = await mgr.get_connection(VALID_UUID)
        assert conn_a_new is not conn_a
        assert mgr.pool_size == 2  # pool stays bounded
    finally:
        await mgr.close_all()


@pytest.mark.asyncio
async def test_lru_eviction_closes_connection(tmp_path):
    """When a connection is evicted, it must be closed (no FD leak)."""
    mgr = TenantDBManager(data_dir=tmp_path, max_connections=1)
    try:
        conn_a = await mgr.get_connection(VALID_UUID)
        # Evict UUID by requesting UUID_2
        await mgr.get_connection(VALID_UUID_2)

        # conn_a was evicted; any execute on it should raise
        raised = False
        try:
            await conn_a.execute("SELECT 1")
        except Exception:
            raised = True
        assert raised, "Expected evicted connection to be closed/unusable"
    finally:
        await mgr.close_all()


# ------------------------------------------------------------------
# Close operations
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_all(manager):
    """close_all should drain the pool to zero."""
    await manager.get_connection(VALID_UUID)
    await manager.get_connection(VALID_UUID_2)
    await manager.get_connection(VALID_UUID_3)
    assert manager.pool_size == 3
    await manager.close_all()
    assert manager.pool_size == 0


# ------------------------------------------------------------------
# Path traversal protection
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_tenant_id_rejected(manager):
    """Path traversal strings must be rejected with ValueError."""
    with pytest.raises(ValueError):
        await manager.get_connection("../../etc/passwd")


@pytest.mark.asyncio
async def test_invalid_tenant_id_not_uuid(manager):
    """Non-UUID strings must be rejected with ValueError."""
    with pytest.raises(ValueError):
        await manager.get_connection("not-a-uuid")


@pytest.mark.asyncio
async def test_valid_uuid_accepted(manager):
    """A valid lowercase UUID must be accepted without error."""
    conn = await manager.get_connection(VALID_UUID)
    assert conn is not None
