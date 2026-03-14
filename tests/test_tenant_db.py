"""
Tests for tenant DB schema (app/db/tenant.py).

Covers:
- All 5 tables exist after init
- Column count and specific columns for memories (20), entities (11)
- Foreign key definitions on relations (3) and feedback (1)
- All 11 named indexes exist
- schema_version seeded with version=1
- Embedding column accepts NULL
- Foreign key enforcement is active (IntegrityError on bad FK)
"""

import pytest
import aiosqlite
import pytest_asyncio
from sqlite3 import IntegrityError

from app.db.tenant import init_tenant_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def tenant_conn(tmp_path):
    """Open a fresh aiosqlite connection to a temp DB, init schema, yield."""
    db_path = tmp_path / "test_tenant.db"
    conn = await aiosqlite.connect(str(db_path))
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await init_tenant_db(conn)
    yield conn
    await conn.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tables_created(tenant_conn):
    """All expected tables exist in sqlite_master."""
    async with tenant_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cursor:
        rows = await cursor.fetchall()

    table_names = {row[0] for row in rows}
    expected = {"memories", "entities", "relations", "feedback", "schema_version"}
    assert expected.issubset(table_names), (
        f"Missing tables: {expected - table_names}"
    )


@pytest.mark.asyncio
async def test_memories_columns(tenant_conn):
    """memories table has exactly 20 columns including embedding."""
    async with tenant_conn.execute("PRAGMA table_info(memories)") as cursor:
        rows = await cursor.fetchall()

    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    col_names = [row[1] for row in rows]
    col_map = {row[1]: row for row in rows}

    assert len(col_names) == 20, (
        f"Expected 20 columns, got {len(col_names)}: {col_names}"
    )

    # Spot-check required columns
    assert "embedding" in col_names, "embedding column missing from memories"
    assert "text" in col_names
    assert "id" in col_names

    # id should be primary key (pk=1)
    assert col_map["id"][5] == 1, "id column must be PRIMARY KEY"

    # text must be NOT NULL (notnull=1)
    assert col_map["text"][3] == 1, "text column must be NOT NULL"

    # embedding default must be NULL
    # SQLite PRAGMA table_info returns dflt_value as the string 'NULL' (not None)
    # when the column is declared DEFAULT NULL.
    embedding_default = col_map["embedding"][4]
    assert embedding_default is None or embedding_default == "NULL", (
        f"embedding DEFAULT should be NULL or 'NULL', got: {embedding_default!r}"
    )


@pytest.mark.asyncio
async def test_entities_columns(tenant_conn):
    """entities table has exactly 11 columns with NOT NULL constraints."""
    async with tenant_conn.execute("PRAGMA table_info(entities)") as cursor:
        rows = await cursor.fetchall()

    col_names = [row[1] for row in rows]
    col_map = {row[1]: row for row in rows}

    assert len(col_names) == 11, (
        f"Expected 11 columns, got {len(col_names)}: {col_names}"
    )

    # name NOT NULL
    assert col_map["name"][3] == 1, "entities.name must be NOT NULL"
    # entity_type NOT NULL
    assert col_map["entity_type"][3] == 1, "entities.entity_type must be NOT NULL"


@pytest.mark.asyncio
async def test_relations_foreign_keys(tenant_conn):
    """relations table has 3 foreign keys pointing to entities and memories."""
    async with tenant_conn.execute("PRAGMA foreign_key_list(relations)") as cursor:
        rows = await cursor.fetchall()

    # PRAGMA foreign_key_list: id, seq, table, from, to, on_update, on_delete, match
    fk_map = {row[3]: row[2] for row in rows}  # from_col -> to_table

    assert len(fk_map) == 3, (
        f"Expected 3 FKs on relations, got {len(fk_map)}: {fk_map}"
    )
    assert fk_map.get("source_entity_id") == "entities", (
        "source_entity_id must FK to entities"
    )
    assert fk_map.get("target_entity_id") == "entities", (
        "target_entity_id must FK to entities"
    )
    assert fk_map.get("memory_id") == "memories", (
        "memory_id must FK to memories"
    )


@pytest.mark.asyncio
async def test_feedback_foreign_key(tenant_conn):
    """feedback table has 1 foreign key to memories(id)."""
    async with tenant_conn.execute("PRAGMA foreign_key_list(feedback)") as cursor:
        rows = await cursor.fetchall()

    assert len(rows) == 1, f"Expected 1 FK on feedback, got {len(rows)}"
    # row: id, seq, table, from, to, ...
    assert rows[0][2] == "memories", "feedback FK must reference memories table"
    assert rows[0][3] == "memory_id", "feedback FK from-column must be memory_id"
    assert rows[0][4] == "id", "feedback FK to-column must be id"


@pytest.mark.asyncio
async def test_indexes_exist(tenant_conn):
    """All 11 named indexes exist across memories, entities, relations."""
    expected_indexes = {
        "idx_memories_user",
        "idx_memories_agent",
        "idx_memories_session",
        "idx_memories_hash",
        "idx_memories_created",
        "idx_memories_deleted",
        "idx_entities_name",
        "idx_entities_type",
        "idx_relations_source",
        "idx_relations_target",
        "idx_relations_memory",
    }

    async with tenant_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ) as cursor:
        rows = await cursor.fetchall()

    index_names = {row[0] for row in rows}
    missing = expected_indexes - index_names
    assert not missing, f"Missing indexes: {missing}"


@pytest.mark.asyncio
async def test_schema_version_populated(tenant_conn):
    """schema_version table has version=1 after init."""
    async with tenant_conn.execute(
        "SELECT version FROM schema_version WHERE version=1"
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None, "schema_version must contain version=1"
    assert row[0] == 1


@pytest.mark.asyncio
async def test_insert_memory_with_embedding_null(tenant_conn):
    """A memory row can be inserted with embedding=NULL and reads back as None."""
    import time

    await tenant_conn.execute(
        """
        INSERT INTO memories (id, text, text_hash, created_at, embedding)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("test-id-001", "hello world", "abc123", int(time.time()), None),
    )
    await tenant_conn.commit()

    async with tenant_conn.execute(
        "SELECT embedding FROM memories WHERE id=?", ("test-id-001",)
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None, "Inserted memory not found"
    assert row[0] is None, (
        f"embedding should read back as None, got: {row[0]!r}"
    )


@pytest.mark.asyncio
async def test_foreign_key_enforcement(tenant_conn):
    """Inserting a relation with a non-existent source_entity_id raises IntegrityError."""
    import time

    with pytest.raises(IntegrityError):
        await tenant_conn.execute(
            """
            INSERT INTO relations (
                id, source_entity_id, source_name, source_type,
                relationship, target_entity_id, target_name, target_type,
                memory_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rel-001",
                "nonexistent-entity-id",  # FK violation
                "Fake Source",
                "person",
                "knows",
                "nonexistent-target-id",
                "Fake Target",
                "person",
                "nonexistent-memory-id",
                int(time.time()),
            ),
        )
        await tenant_conn.commit()
