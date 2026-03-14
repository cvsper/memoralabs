"""Tests for app/deps.py — FastAPI dependency injection for tenant resolution.

Uses Starlette's TestClient which properly triggers the FastAPI lifespan
(unlike httpx ASGITransport which only handles http scopes).
"""
import hashlib
import uuid
import pytest
from starlette.testclient import TestClient
from app.db.system import create_api_key, create_tenant
from app.main import app


def _hash_key(raw_key):
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _get_client(tmp_path, monkeypatch):
    """Patch DATA_DIR and return a Starlette TestClient context manager."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "VECTOR_INDEX_DIR", tmp_path / "indexes")
    import app.main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "VECTOR_INDEX_DIR", tmp_path / "indexes")
    return TestClient(app, raise_server_exceptions=True)


def test_get_tenant_missing_header(tmp_path, monkeypatch):
    """Request without Authorization header returns HTTP 401."""
    with _get_client(tmp_path, monkeypatch) as client:
        response = client.get("/_test/tenant")
    assert response.status_code == 401


def test_get_tenant_invalid_key(tmp_path, monkeypatch):
    """Request with a bad API key returns HTTP 401."""
    with _get_client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/_test/tenant",
            headers={"Authorization": "Bearer invalid-key-xyz"},
        )
    assert response.status_code == 401


def test_get_tenant_malformed_header(tmp_path, monkeypatch):
    """Malformed Authorization header (no 'Bearer' prefix) returns HTTP 401."""
    with _get_client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/_test/tenant",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
    assert response.status_code == 401


def test_get_tenant_valid_key(tmp_path, monkeypatch):
    """Valid API key resolves to the correct tenant — returns 200 with tenant data."""
    raw_key = "test-api-key-abc123"
    with _get_client(tmp_path, monkeypatch) as client:
        # Access app.state after lifespan is triggered by TestClient
        system_db = app.state.system_db
        tenant_id = str(uuid.uuid4())
        # Use the portal to run async code in the sync TestClient context
        tenant = client.portal.call(
            create_tenant, system_db, tenant_id, "Test Tenant", "test@example.com"
        )
        client.portal.call(
            create_api_key,
            system_db,
            str(uuid.uuid4()),
            tenant_id,
            _hash_key(raw_key),
            "test",
            "test-key",
        )
        response = client.get(
            "/_test/tenant",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == tenant["id"]
    assert data["email"] == tenant["email"]


def test_get_tenant_inactive_key(tmp_path, monkeypatch):
    """Deactivated API key (is_active=0) returns HTTP 401."""
    raw_key = "inactive-key-secret"
    with _get_client(tmp_path, monkeypatch) as client:
        system_db = app.state.system_db
        tenant_id = str(uuid.uuid4())

        async def _setup():
            await create_tenant(system_db, tenant_id, "Inactive Tenant", "inactive@example.com")
            key_id = str(uuid.uuid4())
            await create_api_key(
                system_db, key_id=key_id, tenant_id=tenant_id,
                key_hash=_hash_key(raw_key), key_prefix="inac",
            )
            await system_db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
            await system_db.commit()

        client.portal.call(_setup)
        response = client.get(
            "/_test/tenant",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert response.status_code == 401


def test_get_tenant_suspended_tenant(tmp_path, monkeypatch):
    """Suspended tenant (status='suspended') returns HTTP 401."""
    raw_key = "suspended-key-secret"
    with _get_client(tmp_path, monkeypatch) as client:
        system_db = app.state.system_db
        tenant_id = str(uuid.uuid4())

        async def _setup():
            await create_tenant(system_db, tenant_id, "Suspended Tenant", "suspended@example.com")
            key_id = str(uuid.uuid4())
            await create_api_key(
                system_db, key_id=key_id, tenant_id=tenant_id,
                key_hash=_hash_key(raw_key), key_prefix="susp",
            )
            await system_db.execute("UPDATE tenants SET status = 'suspended' WHERE id = ?", (tenant_id,))
            await system_db.commit()

        client.portal.call(_setup)
        response = client.get(
            "/_test/tenant",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
    assert response.status_code == 401
