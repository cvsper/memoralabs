"""Tests for global exception handlers — structured JSON error responses.

Tests cover:
- Missing Authorization header returns structured JSON 401 with error+message
- Invalid API key returns structured JSON 401 with error+message
- 401 responses include WWW-Authenticate: Bearer header
- POST with invalid body returns structured JSON 422 with error+message+details
- GET for nonexistent memory ID returns structured JSON 404
- All error responses have Content-Type: application/json
- last_used_at is updated on every successful authentication
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

TEST_API_KEY = "test-error-handler-key-abc123"
TEST_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
AUTH_HEADER = {"Authorization": f"Bearer {TEST_API_KEY}"}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
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


def _make_client(tmp_path, monkeypatch, raise_server_exceptions=False):
    """Return a Starlette TestClient context manager with patched directories."""
    _patch_dirs(tmp_path, monkeypatch)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _setup_tenant(client):
    """Create a tenant + API key in the system DB and initialise the tenant DB."""
    system_db = app.state.system_db
    tenant_id = str(uuid.uuid4())

    async def _setup():
        await create_tenant(system_db, tenant_id, "Error Handler Test", "errortest@example.com")
        await create_api_key(
            system_db,
            str(uuid.uuid4()),
            tenant_id,
            TEST_KEY_HASH,
            "test",
            "error-test-key",
        )
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id


# ──────────────────────────────────────────────────────────────────────────────
# Tests: 401 structured JSON
# ──────────────────────────────────────────────────────────────────────────────


def test_401_structured_json(tmp_path, monkeypatch):
    """Request without auth returns 401 with structured JSON body."""
    with _make_client(tmp_path, monkeypatch) as client:
        response = client.get("/v1/memory")

    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert "message" in data
    assert data["error"] == "UNAUTHORIZED"


def test_401_includes_www_authenticate_header(tmp_path, monkeypatch):
    """401 response includes WWW-Authenticate: Bearer header."""
    with _make_client(tmp_path, monkeypatch) as client:
        response = client.get("/v1/memory")

    assert response.status_code == 401
    assert "www-authenticate" in response.headers
    assert response.headers["www-authenticate"] == "Bearer"


def test_401_invalid_key_structured(tmp_path, monkeypatch):
    """Invalid API key returns structured JSON 401 with error and message."""
    with _make_client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/v1/memory",
            headers={"Authorization": "Bearer totally-invalid-key-xyz"},
        )

    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert "message" in data
    assert data["error"] == "UNAUTHORIZED"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: 422 structured JSON
# ──────────────────────────────────────────────────────────────────────────────


def test_422_validation_structured(tmp_path, monkeypatch):
    """POST with invalid body returns structured JSON 422 with details array."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        # Missing required 'text' field
        response = client.post(
            "/v1/memory",
            json={},
            headers=AUTH_HEADER,
        )

    assert response.status_code == 422
    data = response.json()
    assert data["error"] == "VALIDATION_ERROR"
    assert "message" in data
    assert "details" in data
    assert isinstance(data["details"], list)
    assert len(data["details"]) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Tests: 404 structured JSON
# ──────────────────────────────────────────────────────────────────────────────


def test_404_structured_json(tmp_path, monkeypatch):
    """GET on a nonexistent memory ID returns structured JSON 404."""
    nonexistent_id = str(uuid.uuid4())
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        response = client.get(
            f"/v1/memory/{nonexistent_id}",
            headers=AUTH_HEADER,
        )

    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "message" in data
    assert data["error"] == "NOT_FOUND"


# ──────────────────────────────────────────────────────────────────────────────
# Tests: Content-Type is application/json for all errors
# ──────────────────────────────────────────────────────────────────────────────


def test_error_responses_are_json_not_html(tmp_path, monkeypatch):
    """401 and 422 error responses must have Content-Type: application/json."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)

        # 401 — no auth
        r401 = client.get("/v1/memory")
        assert r401.status_code == 401
        assert r401.headers["content-type"].startswith("application/json")

        # 422 — bad body
        r422 = client.post("/v1/memory", json={}, headers=AUTH_HEADER)
        assert r422.status_code == 422
        assert r422.headers["content-type"].startswith("application/json")


# ──────────────────────────────────────────────────────────────────────────────
# Tests: last_used_at updated on successful auth
# ──────────────────────────────────────────────────────────────────────────────


def test_last_used_at_updated(tmp_path, monkeypatch):
    """Successful authenticated request writes last_used_at to api_keys table."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)

        # Confirm last_used_at is NULL before any authenticated request
        async def _get_last_used():
            db = app.state.system_db
            async with db.execute(
                "SELECT last_used_at FROM api_keys WHERE key_hash = ?",
                (TEST_KEY_HASH,),
            ) as cur:
                row = await cur.fetchone()
            return row["last_used_at"] if row else None

        last_used_before = client.portal.call(_get_last_used)
        assert last_used_before is None, "last_used_at should be NULL before first auth"

        # Make an authenticated request
        response = client.get("/v1/memory", headers=AUTH_HEADER)
        assert response.status_code == 200

        # Confirm last_used_at is now set
        last_used_after = client.portal.call(_get_last_used)
        assert last_used_after is not None, "last_used_at should be set after successful auth"
        assert isinstance(last_used_after, int)
        assert last_used_after > 0
