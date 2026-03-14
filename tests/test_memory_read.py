"""
Integration tests for GET, PATCH, DELETE /v1/memory endpoints.

Tests cover:
- GET /v1/memory: empty list, returns data, pagination, scope filtering, deleted excluded, order
- GET /v1/memory/{id}: success, 404 not found, 404 deleted, access_count increment
- GET /v1/memory/{id}/entities (RETR-03): empty, with data, 404 not found, 404 deleted
- PATCH /v1/memory/{id}: update text, update metadata, 404 not found, partial update
- DELETE /v1/memory/{id}: success, 404 not found, idempotent (second delete returns 404), excluded from list
- Usage logging: list, get, and delete log correct operation names

All tests use Starlette TestClient + monkeypatch DATA_DIR pattern (same as test_memory_write.py).
"""

import hashlib
import time
import uuid

import pytest
from starlette.testclient import TestClient

from app.db.system import create_api_key, create_tenant
from app.main import app

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

TEST_API_KEY = "test-memory-read-key-abc456"
TEST_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
AUTH_HEADER = {"Authorization": f"Bearer {TEST_API_KEY}"}


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


def _patch_dirs(tmp_path, monkeypatch):
    """Patch DATA_DIR and VECTOR_INDEX_DIR to isolated tmp_path."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "VECTOR_INDEX_DIR", tmp_path / "indexes")
    import app.main as main_module

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "VECTOR_INDEX_DIR", tmp_path / "indexes")


def _make_client(tmp_path, monkeypatch):
    """Return a Starlette TestClient with a fully set-up tenant and API key."""
    _patch_dirs(tmp_path, monkeypatch)
    return TestClient(app, raise_server_exceptions=True)


def _setup_tenant(client) -> str:
    """Create a tenant + API key in the system DB and initialise the tenant DB.

    Returns the tenant_id.
    """
    system_db = app.state.system_db
    tenant_id = str(uuid.uuid4())

    async def _setup():
        await create_tenant(system_db, tenant_id, "Read Test Tenant", "test-read@example.com")
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=TEST_KEY_HASH,
            key_prefix="test",
            name="test-read-key",
        )
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id


def _insert_memory(
    client,
    tenant_id: str,
    text: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    is_deleted: int = 0,
    created_at: int | None = None,
) -> str:
    """Insert a memory directly into the tenant DB. Returns the memory_id."""
    memory_id = str(uuid.uuid4())
    now = created_at if created_at is not None else int(time.time())

    async def _insert():
        conn = await app.state.tenant_manager.get_connection(tenant_id)
        await conn.execute(
            """
            INSERT INTO memories
                (id, text, text_hash, user_id, agent_id, session_id,
                 metadata, created_at, updated_at, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, text, text, user_id, agent_id, session_id, "{}", now, now, is_deleted),
        )
        await conn.commit()

    client.portal.call(_insert)
    return memory_id


# ──────────────────────────────────────────────────────────────────────────────
# GET /v1/memory tests
# ──────────────────────────────────────────────────────────────────────────────


def test_list_memories_empty(tmp_path, monkeypatch):
    """No memories returns empty list with total=0."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.get("/v1/memory", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["memories"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 20


def test_list_memories_returns_data(tmp_path, monkeypatch):
    """Insert 3 memories, verify list returns all 3 with correct fields."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _insert_memory(client, tenant_id, "Memory one")
        _insert_memory(client, tenant_id, "Memory two")
        _insert_memory(client, tenant_id, "Memory three")
        resp = client.get("/v1/memory", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["memories"]) == 3
    texts = {m["text"] for m in data["memories"]}
    assert texts == {"Memory one", "Memory two", "Memory three"}


def test_list_memories_pagination(tmp_path, monkeypatch):
    """Insert 5 memories, page=1 page_size=2 returns 2 memories + total=5."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        for i in range(5):
            _insert_memory(client, tenant_id, f"Memory {i}")
        resp = client.get("/v1/memory?page=1&page_size=2", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["memories"]) == 2
    assert data["page"] == 1
    assert data["page_size"] == 2


def test_list_memories_page_2(tmp_path, monkeypatch):
    """Page 2 with page_size=2 returns the next 2 memories."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        # Insert with distinct created_at so ordering is deterministic
        for i in range(5):
            _insert_memory(client, tenant_id, f"Page memory {i}", created_at=1000000 + i)
        resp1 = client.get("/v1/memory?page=1&page_size=2", headers=AUTH_HEADER)
        resp2 = client.get("/v1/memory?page=2&page_size=2", headers=AUTH_HEADER)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    page1_ids = {m["id"] for m in resp1.json()["memories"]}
    page2_ids = {m["id"] for m in resp2.json()["memories"]}
    # No overlap between pages
    assert len(page1_ids & page2_ids) == 0
    # All page IDs differ
    assert len(page1_ids) == 2
    assert len(page2_ids) == 2


def test_list_memories_filter_user_id(tmp_path, monkeypatch):
    """Filter by user_id returns only matching memories."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _insert_memory(client, tenant_id, "User A memory", user_id="user-a")
        _insert_memory(client, tenant_id, "User A memory 2", user_id="user-a")
        _insert_memory(client, tenant_id, "User B memory", user_id="user-b")
        resp = client.get("/v1/memory?user_id=user-a", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(m["user_id"] == "user-a" for m in data["memories"])


def test_list_memories_excludes_deleted(tmp_path, monkeypatch):
    """Deleted memories (is_deleted=1) are not returned in the list."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _insert_memory(client, tenant_id, "Live memory")
        _insert_memory(client, tenant_id, "Deleted memory", is_deleted=1)
        resp = client.get("/v1/memory", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["memories"][0]["text"] == "Live memory"


def test_list_memories_order(tmp_path, monkeypatch):
    """Memories are returned in created_at DESC order (newest first)."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _insert_memory(client, tenant_id, "Oldest", created_at=1000000)
        _insert_memory(client, tenant_id, "Middle", created_at=2000000)
        _insert_memory(client, tenant_id, "Newest", created_at=3000000)
        resp = client.get("/v1/memory", headers=AUTH_HEADER)
    assert resp.status_code == 200
    texts = [m["text"] for m in resp.json()["memories"]]
    assert texts == ["Newest", "Middle", "Oldest"]


# ──────────────────────────────────────────────────────────────────────────────
# GET /v1/memory/{id} tests
# ──────────────────────────────────────────────────────────────────────────────


def test_get_memory_success(tmp_path, monkeypatch):
    """Insert memory, GET by id returns correct fields."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Get me by ID")
        resp = client.get(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == memory_id
    assert data["text"] == "Get me by ID"
    assert "created_at" in data


def test_get_memory_not_found(tmp_path, monkeypatch):
    """GET nonexistent memory ID returns 404."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.get(f"/v1/memory/{uuid.uuid4()}", headers=AUTH_HEADER)
    assert resp.status_code == 404


def test_get_memory_deleted(tmp_path, monkeypatch):
    """GET a deleted memory returns 404."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Soft-deleted memory", is_deleted=1)
        resp = client.get(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
    assert resp.status_code == 404


def test_get_memory_increments_access_count(tmp_path, monkeypatch):
    """GET the same memory twice increments access_count to 2."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Access count test")
        client.get(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
        client.get(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)

        async def _check_access_count():
            conn = await app.state.tenant_manager.get_connection(tenant_id)
            async with conn.execute(
                "SELECT access_count FROM memories WHERE id = ?", (memory_id,)
            ) as cur:
                row = await cur.fetchone()
            return row["access_count"] if row else None

        count = client.portal.call(_check_access_count)

    assert count == 2


# ──────────────────────────────────────────────────────────────────────────────
# GET /v1/memory/{id}/entities tests (RETR-03)
# ──────────────────────────────────────────────────────────────────────────────


def test_get_entities_empty(tmp_path, monkeypatch):
    """Memory with no entities/relations returns empty lists."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Plain text, no entities")
        resp = client.get(f"/v1/memory/{memory_id}/entities", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["memory_id"] == memory_id
    assert data["entities"] == []
    assert data["relations"] == []
    assert data["total_entities"] == 0
    assert data["total_relations"] == 0


def test_get_entities_with_data(tmp_path, monkeypatch):
    """Insert memory with entities+relations directly, verify they are returned."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Alice works at Acme Corp")

        # Insert entities and a relation directly into the tenant DB
        entity_id_alice = str(uuid.uuid4())
        entity_id_acme = str(uuid.uuid4())
        relation_id = str(uuid.uuid4())
        now = int(time.time())

        async def _insert_graph():
            conn = await app.state.tenant_manager.get_connection(tenant_id)
            await conn.execute(
                "INSERT INTO entities (id, name, name_normalized, entity_type, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_id_alice, "Alice", "alice", "person", now),
            )
            await conn.execute(
                "INSERT INTO entities (id, name, name_normalized, entity_type, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entity_id_acme, "Acme Corp", "acme corp", "organization", now),
            )
            await conn.execute(
                """
                INSERT INTO relations
                    (id, source_entity_id, source_name, source_type,
                     relationship, target_entity_id, target_name, target_type,
                     memory_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    entity_id_alice, "Alice", "person",
                    "works_at",
                    entity_id_acme, "Acme Corp", "organization",
                    memory_id,
                    now,
                ),
            )
            await conn.commit()

        client.portal.call(_insert_graph)

        resp = client.get(f"/v1/memory/{memory_id}/entities", headers=AUTH_HEADER)

    assert resp.status_code == 200
    data = resp.json()
    assert data["memory_id"] == memory_id
    assert data["total_entities"] == 2
    assert data["total_relations"] == 1

    entity_names = {e["name"] for e in data["entities"]}
    assert entity_names == {"Alice", "Acme Corp"}

    rel = data["relations"][0]
    assert rel["relationship"] == "works_at"
    assert rel["source_name"] == "Alice"
    assert rel["target_name"] == "Acme Corp"
    assert rel["source_type"] == "person"
    assert rel["target_type"] == "organization"


def test_get_entities_memory_not_found(tmp_path, monkeypatch):
    """GET /entities for nonexistent memory ID returns 404."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.get(f"/v1/memory/{uuid.uuid4()}/entities", headers=AUTH_HEADER)
    assert resp.status_code == 404


def test_get_entities_deleted_memory(tmp_path, monkeypatch):
    """GET /entities for a deleted memory returns 404."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Deleted, no entities", is_deleted=1)
        resp = client.get(f"/v1/memory/{memory_id}/entities", headers=AUTH_HEADER)
    assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# PATCH /v1/memory/{id} tests
# ──────────────────────────────────────────────────────────────────────────────


def test_update_memory_text(tmp_path, monkeypatch):
    """PATCH with new text updates text and updated_at."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Original text")
        resp = client.patch(
            f"/v1/memory/{memory_id}",
            json={"text": "Updated text"},
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Updated text"
    assert data["updated_at"] is not None


def test_update_memory_metadata(tmp_path, monkeypatch):
    """PATCH with new metadata updates the stored metadata."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Metadata test memory")
        resp = client.patch(
            f"/v1/memory/{memory_id}",
            json={"metadata": {"source": "patch-test", "priority": 9}},
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["metadata"] == {"source": "patch-test", "priority": 9}


def test_update_memory_not_found(tmp_path, monkeypatch):
    """PATCH nonexistent memory returns 404."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.patch(
            f"/v1/memory/{uuid.uuid4()}",
            json={"text": "Should not exist"},
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 404


def test_update_memory_partial(tmp_path, monkeypatch):
    """PATCH only user_id; text must remain unchanged."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Unchanged text")
        resp = client.patch(
            f"/v1/memory/{memory_id}",
            json={"user_id": "new-user"},
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Unchanged text"
    assert data["user_id"] == "new-user"


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /v1/memory/{id} tests
# ──────────────────────────────────────────────────────────────────────────────


def test_delete_memory_success(tmp_path, monkeypatch):
    """DELETE returns {"id": ..., "status": "deleted"}."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Delete this")
        resp = client.delete(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == memory_id
    assert data["status"] == "deleted"


def test_delete_memory_not_found(tmp_path, monkeypatch):
    """DELETE nonexistent memory returns 404."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.delete(f"/v1/memory/{uuid.uuid4()}", headers=AUTH_HEADER)
    assert resp.status_code == 404


def test_delete_memory_idempotent(tmp_path, monkeypatch):
    """Delete same memory twice — second DELETE returns 404 (already deleted)."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Delete twice test")
        r1 = client.delete(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
        r2 = client.delete(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
    assert r1.status_code == 200
    assert r2.status_code == 404


def test_delete_memory_excluded_from_list(tmp_path, monkeypatch):
    """After DELETE, memory does not appear in GET /v1/memory list."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Will be deleted")
        _insert_memory(client, tenant_id, "Will stay")
        client.delete(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)
        resp = client.get("/v1/memory", headers=AUTH_HEADER)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["memories"][0]["text"] == "Will stay"


# ──────────────────────────────────────────────────────────────────────────────
# Usage logging tests
# ──────────────────────────────────────────────────────────────────────────────


def test_list_usage_logged(tmp_path, monkeypatch):
    """GET /v1/memory logs operation='memory.list'."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        client.get("/v1/memory", headers=AUTH_HEADER)

        async def _check():
            system_db = app.state.system_db
            async with system_db.execute(
                "SELECT operation, endpoint, status_code FROM usage_log "
                "WHERE tenant_id = ? AND operation = 'memory.list' ORDER BY id DESC LIMIT 1",
                (tenant_id,),
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        result = client.portal.call(_check)

    assert result is not None
    assert result["operation"] == "memory.list"
    assert result["endpoint"] == "/v1/memory"
    assert result["status_code"] == 200


def test_get_usage_logged(tmp_path, monkeypatch):
    """GET /v1/memory/{id} logs operation='memory.get'."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Usage log get test")
        client.get(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)

        async def _check():
            system_db = app.state.system_db
            async with system_db.execute(
                "SELECT operation, endpoint, status_code FROM usage_log "
                "WHERE tenant_id = ? AND operation = 'memory.get' ORDER BY id DESC LIMIT 1",
                (tenant_id,),
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        result = client.portal.call(_check)

    assert result is not None
    assert result["operation"] == "memory.get"
    assert result["status_code"] == 200


def test_delete_usage_logged(tmp_path, monkeypatch):
    """DELETE /v1/memory/{id} logs operation='memory.delete'."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _insert_memory(client, tenant_id, "Usage log delete test")
        client.delete(f"/v1/memory/{memory_id}", headers=AUTH_HEADER)

        async def _check():
            system_db = app.state.system_db
            async with system_db.execute(
                "SELECT operation, endpoint, status_code FROM usage_log "
                "WHERE tenant_id = ? AND operation = 'memory.delete' ORDER BY id DESC LIMIT 1",
                (tenant_id,),
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        result = client.portal.call(_check)

    assert result is not None
    assert result["operation"] == "memory.delete"
    assert result["status_code"] == 200
