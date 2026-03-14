"""Tests for app/db/system.py — system database init, schema, and CRUD helpers."""

import pytest
import pytest_asyncio
import aiosqlite
from sqlite3 import IntegrityError

from app.db.system import (
    init_system_db,
    create_tenant,
    create_api_key,
    get_tenant_by_key_hash,
    log_usage,
)


@pytest_asyncio.fixture
async def system_db(tmp_path):
    """Provide a freshly-initialized system DB connection for each test."""
    conn = await init_system_db(tmp_path)
    yield conn, tmp_path
    await conn.close()


@pytest.mark.asyncio
async def test_init_creates_db_file(tmp_path):
    """init_system_db should create system.db on disk."""
    conn = await init_system_db(tmp_path)
    await conn.close()
    assert (tmp_path / "system.db").exists()


@pytest.mark.asyncio
async def test_init_creates_all_tables(system_db):
    """All 4 required tables must exist after init."""
    conn, _ = system_db
    expected = {"tenants", "api_keys", "usage_log", "schema_version"}
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cur:
        rows = await cur.fetchall()
    found = {row["name"] for row in rows}
    assert expected.issubset(found)


@pytest.mark.asyncio
async def test_wal_mode(system_db):
    """System DB must operate in WAL journal mode."""
    conn, _ = system_db
    async with conn.execute("PRAGMA journal_mode") as cur:
        row = await cur.fetchone()
    assert row[0] == "wal"


@pytest.mark.asyncio
async def test_create_tenant_returns_correct_fields(system_db):
    """create_tenant should insert a row and return a dict with expected fields."""
    conn, _ = system_db
    tenant = await create_tenant(
        conn,
        tenant_id="t-001",
        name="Acme Corp",
        email="admin@acme.com",
        plan="pro",
        memory_limit=5000,
    )
    assert tenant["id"] == "t-001"
    assert tenant["name"] == "Acme Corp"
    assert tenant["email"] == "admin@acme.com"
    assert tenant["plan"] == "pro"
    assert tenant["status"] == "active"
    assert tenant["memory_limit"] == 5000
    assert isinstance(tenant["created_at"], int)
    assert tenant["created_at"] > 0


@pytest.mark.asyncio
async def test_create_tenant_duplicate_email_raises(system_db):
    """Inserting two tenants with the same email must raise IntegrityError."""
    conn, _ = system_db
    await create_tenant(conn, "t-dup-1", "Org One", "dup@example.com")
    with pytest.raises(IntegrityError):
        await create_tenant(conn, "t-dup-2", "Org Two", "dup@example.com")


@pytest.mark.asyncio
async def test_create_api_key_links_to_tenant(system_db):
    """create_api_key should insert a row linked to the correct tenant."""
    conn, _ = system_db
    await create_tenant(conn, "t-002", "Beta Inc", "beta@example.com")
    key = await create_api_key(
        conn,
        key_id="k-001",
        tenant_id="t-002",
        key_hash="abc123hash",
        key_prefix="ml_live_a",
        name="production",
    )
    assert key["id"] == "k-001"
    assert key["tenant_id"] == "t-002"
    assert key["key_hash"] == "abc123hash"
    assert key["key_prefix"] == "ml_live_a"
    assert key["name"] == "production"
    assert key["is_active"] == 1


@pytest.mark.asyncio
async def test_get_tenant_by_key_hash_returns_tenant(system_db):
    """get_tenant_by_key_hash should return the tenant dict for a valid active key."""
    conn, _ = system_db
    await create_tenant(conn, "t-003", "Gamma LLC", "gamma@example.com")
    await create_api_key(conn, "k-002", "t-003", "validhash", "ml_live_b")
    tenant = await get_tenant_by_key_hash(conn, "validhash")
    assert tenant is not None
    assert tenant["id"] == "t-003"
    assert tenant["email"] == "gamma@example.com"


@pytest.mark.asyncio
async def test_get_tenant_by_key_hash_returns_none_for_unknown(system_db):
    """get_tenant_by_key_hash should return None when the hash does not exist."""
    conn, _ = system_db
    result = await get_tenant_by_key_hash(conn, "nonexistenthash")
    assert result is None


@pytest.mark.asyncio
async def test_get_tenant_by_key_hash_returns_none_for_inactive_key(system_db):
    """get_tenant_by_key_hash should return None when is_active=0."""
    conn, _ = system_db
    await create_tenant(conn, "t-004", "Delta Co", "delta@example.com")
    await create_api_key(conn, "k-003", "t-004", "inactivehash", "ml_live_c")
    # Deactivate the key
    await conn.execute(
        "UPDATE api_keys SET is_active = 0 WHERE id = ?", ("k-003",)
    )
    await conn.commit()
    result = await get_tenant_by_key_hash(conn, "inactivehash")
    assert result is None


@pytest.mark.asyncio
async def test_log_usage_inserts_record(system_db):
    """log_usage should insert a row into usage_log."""
    conn, _ = system_db
    await create_tenant(conn, "t-005", "Epsilon", "eps@example.com")
    await log_usage(
        conn,
        tenant_id="t-005",
        operation="store",
        endpoint="/v1/memory",
        status_code=201,
        latency_ms=45,
        tokens_used=128,
    )
    async with conn.execute(
        "SELECT * FROM usage_log WHERE tenant_id = ?", ("t-005",)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["operation"] == "store"
    assert row["endpoint"] == "/v1/memory"
    assert row["status_code"] == 201
    assert row["latency_ms"] == 45
    assert row["tokens_used"] == 128
