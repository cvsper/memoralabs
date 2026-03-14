"""
Integration tests for POST /v1/memory endpoint.

Tests cover:
- Successful memory creation (201, UUID id, status=created)
- Response field completeness (text, user_id, agent_id, session_id, metadata, created_at)
- Scoping fields (user_id, agent_id, session_id) round-trip
- Metadata round-trip
- Exact-match dedup: second POST with same text returns 200 + status=duplicate + same ID
- Case-insensitive dedup ("Hello World" == "hello world")
- Whitespace-normalized dedup ("hello" == " hello ")
- Empty text validation (422)
- Missing text validation (422)
- Missing Authorization header (401)
- Invalid API key (401)
- Usage log records memory.create entries
- Usage log records memory.create.duplicate entries

All tests use Starlette TestClient + monkeypatch DATA_DIR pattern (same as test_deps.py).
The test fixture creates a tenant + API key in the system DB and creates the tenant DB
using TenantDBManager.create_tenant_db so the memories table is present before requests.
"""

import hashlib
import uuid

import pytest
from starlette.testclient import TestClient

from app.db.system import create_api_key, create_tenant
from app.main import app

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

TEST_API_KEY = "test-memory-write-key-abc123"
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
        await create_tenant(system_db, tenant_id, "Test Tenant", "test-memory@example.com")
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=TEST_KEY_HASH,
            key_prefix="test",
            name="test-key",
        )
        # Initialise the tenant DB so the memories table exists
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────


def test_create_memory_success(tmp_path, monkeypatch):
    """POST with valid text returns 201 + id (UUID) + status=created."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json={"text": "Alice met Bob"}, headers=AUTH_HEADER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "created"
    # Validate UUID format
    parsed = uuid.UUID(data["id"])
    assert str(parsed) == data["id"]


def test_create_memory_returns_fields(tmp_path, monkeypatch):
    """Response includes all expected fields: text, user_id, agent_id, session_id, metadata, created_at."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json={"text": "Test memory"}, headers=AUTH_HEADER)
    assert resp.status_code == 201
    data = resp.json()
    for field in ("id", "text", "user_id", "agent_id", "session_id", "metadata", "created_at"):
        assert field in data, f"Missing field: {field}"
    assert data["text"] == "Test memory"
    assert isinstance(data["created_at"], int)
    assert data["created_at"] > 0


def test_create_memory_with_scoping(tmp_path, monkeypatch):
    """user_id, agent_id, session_id are stored and returned in the response."""
    payload = {
        "text": "Scoped memory",
        "user_id": "user-abc",
        "agent_id": "agent-xyz",
        "session_id": "session-123",
    }
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json=payload, headers=AUTH_HEADER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == "user-abc"
    assert data["agent_id"] == "agent-xyz"
    assert data["session_id"] == "session-123"


def test_create_memory_with_metadata(tmp_path, monkeypatch):
    """metadata dict is stored and returned in the response."""
    payload = {"text": "Memory with metadata", "metadata": {"source": "test", "priority": 5}}
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json=payload, headers=AUTH_HEADER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["metadata"] == {"source": "test", "priority": 5}


def test_create_memory_dedup_exact(tmp_path, monkeypatch):
    """Same text posted twice: first returns 201/created, second returns 200/duplicate with same ID."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        r1 = client.post("/v1/memory", json={"text": "Unique text for dedup test"}, headers=AUTH_HEADER)
        r2 = client.post("/v1/memory", json={"text": "Unique text for dedup test"}, headers=AUTH_HEADER)

    assert r1.status_code == 201
    assert r2.status_code == 200
    d1 = r1.json()
    d2 = r2.json()
    assert d1["status"] == "created"
    assert d2["status"] == "duplicate"
    assert d1["id"] == d2["id"]


def test_create_memory_dedup_case_insensitive(tmp_path, monkeypatch):
    """'Hello World' and 'hello world' are treated as duplicates."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        r1 = client.post("/v1/memory", json={"text": "Hello World"}, headers=AUTH_HEADER)
        r2 = client.post("/v1/memory", json={"text": "hello world"}, headers=AUTH_HEADER)

    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["status"] == "created"
    assert r2.json()["status"] == "duplicate"
    assert r1.json()["id"] == r2.json()["id"]


def test_create_memory_dedup_whitespace(tmp_path, monkeypatch):
    """'hello' and ' hello ' (leading/trailing whitespace) are treated as duplicates."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        r1 = client.post("/v1/memory", json={"text": "hello"}, headers=AUTH_HEADER)
        r2 = client.post("/v1/memory", json={"text": " hello "}, headers=AUTH_HEADER)

    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r1.json()["status"] == "created"
    assert r2.json()["status"] == "duplicate"
    assert r1.json()["id"] == r2.json()["id"]


def test_create_memory_empty_text(tmp_path, monkeypatch):
    """POST with empty string text returns 422 validation error."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json={"text": ""}, headers=AUTH_HEADER)
    assert resp.status_code == 422


def test_create_memory_missing_text(tmp_path, monkeypatch):
    """POST with no text field returns 422 validation error."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json={}, headers=AUTH_HEADER)
    assert resp.status_code == 422


def test_create_memory_no_auth(tmp_path, monkeypatch):
    """POST without Authorization header returns 401."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post("/v1/memory", json={"text": "No auth test"})
    assert resp.status_code == 401


def test_create_memory_invalid_auth(tmp_path, monkeypatch):
    """POST with invalid API key returns 401."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        resp = client.post(
            "/v1/memory",
            json={"text": "Invalid auth test"},
            headers={"Authorization": "Bearer completely-invalid-key-xyz"},
        )
    assert resp.status_code == 401


def test_create_memory_usage_logged(tmp_path, monkeypatch):
    """POST a memory, then verify usage_log has entry with operation=memory.create."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        client.post("/v1/memory", json={"text": "Usage log test memory"}, headers=AUTH_HEADER)

        async def _check_usage():
            system_db = app.state.system_db
            async with system_db.execute(
                "SELECT operation, endpoint, status_code FROM usage_log WHERE tenant_id = ? ORDER BY id DESC LIMIT 1",
                (tenant_id,),
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        result = client.portal.call(_check_usage)

    assert result is not None
    assert result["operation"] == "memory.create"
    assert result["endpoint"] == "/v1/memory"
    assert result["status_code"] == 201


def test_create_memory_duplicate_usage_logged(tmp_path, monkeypatch):
    """POST duplicate memory, verify usage_log has memory.create.duplicate entry."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        client.post("/v1/memory", json={"text": "Duplicate usage log test"}, headers=AUTH_HEADER)
        client.post("/v1/memory", json={"text": "Duplicate usage log test"}, headers=AUTH_HEADER)

        async def _check_usage():
            system_db = app.state.system_db
            async with system_db.execute(
                "SELECT operation, endpoint, status_code FROM usage_log "
                "WHERE tenant_id = ? AND operation = 'memory.create.duplicate' "
                "ORDER BY id DESC LIMIT 1",
                (tenant_id,),
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        result = client.portal.call(_check_usage)

    assert result is not None
    assert result["operation"] == "memory.create.duplicate"
    assert result["endpoint"] == "/v1/memory"
    assert result["status_code"] == 200
