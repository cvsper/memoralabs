"""
Cross-tenant isolation tests for TenantDBManager.

Proves that each tenant gets a separate .db file and that one tenant's
connection cannot access another tenant's data.
"""

import pytest
import pytest_asyncio

from app.db.manager import TenantDBManager

UUID_A = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
UUID_B = "b2c3d4e5-f6a7-8901-bcde-f12345678901"


@pytest_asyncio.fixture
async def manager(tmp_path):
    """Provide a fresh TenantDBManager backed by a temp directory."""
    mgr = TenantDBManager(data_dir=tmp_path)
    yield mgr
    await mgr.close_all()


@pytest.mark.asyncio
async def test_cross_tenant_isolation(manager):
    """Tenant A's connection must not see Tenant B's data, and vice-versa."""
    # Create both tenant DBs (applies schema)
    await manager.create_tenant_db(UUID_A)
    await manager.create_tenant_db(UUID_B)

    conn_a = await manager.get_connection(UUID_A)
    conn_b = await manager.get_connection(UUID_B)

    # Insert a memory row into Tenant A's DB
    await conn_a.execute(
        "INSERT INTO memories (id, text, text_hash, created_at) VALUES (?, ?, ?, ?)",
        ("mem-1", "secret-A", "hash-a", 1000),
    )
    await conn_a.commit()

    # Insert a memory row into Tenant B's DB
    await conn_b.execute(
        "INSERT INTO memories (id, text, text_hash, created_at) VALUES (?, ?, ?, ?)",
        ("mem-2", "secret-B", "hash-b", 1000),
    )
    await conn_b.commit()

    # Tenant A sees only its own memory
    async with conn_a.execute("SELECT text FROM memories") as cur:
        rows_a = [r[0] for r in await cur.fetchall()]
    assert rows_a == ["secret-A"]

    # Tenant B sees only its own memory
    async with conn_b.execute("SELECT text FROM memories") as cur:
        rows_b = [r[0] for r in await cur.fetchall()]
    assert rows_b == ["secret-B"]

    # Tenant A cannot find Tenant B's secret
    async with conn_a.execute(
        "SELECT text FROM memories WHERE text = ?", ("secret-B",)
    ) as cur:
        cross = await cur.fetchall()
    assert len(cross) == 0, "Tenant A should not see Tenant B's data"


@pytest.mark.asyncio
async def test_tenant_db_files_separate(manager, tmp_path):
    """Each tenant must have its own .db file at a distinct path."""
    path_a = await manager.create_tenant_db(UUID_A)
    path_b = await manager.create_tenant_db(UUID_B)

    assert path_a.exists()
    assert path_b.exists()
    assert path_a != path_b


@pytest.mark.asyncio
async def test_tenant_db_on_persistent_path(manager, tmp_path):
    """Tenant DB must be stored under {data_dir}/tenants/."""
    path = await manager.create_tenant_db(UUID_A)
    expected_parent = tmp_path / "tenants"
    assert path.parent == expected_parent
    assert str(path).startswith(str(tmp_path))
