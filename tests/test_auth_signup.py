"""Tests for POST /v1/auth/signup endpoint."""
import hashlib

import pytest
from starlette.testclient import TestClient

from app.limiter import limiter
from app.main import app


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Reset the in-memory rate limiter between tests to avoid cross-test pollution."""
    limiter._storage.reset()
    yield
    limiter._storage.reset()


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


# ---------------------------------------------------------------------------
# Successful signup
# ---------------------------------------------------------------------------


def test_signup_success(tmp_path, monkeypatch):
    """POST with valid name+email returns 201 with API key and expected fields."""
    with _get_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/v1/auth/signup",
            json={"name": "Test Developer", "email": "dev@example.com"},
        )
    assert response.status_code == 201
    data = response.json()
    assert "api_key" in data
    assert data["api_key"].startswith("ml_")
    assert len(data["api_key"]) == 67  # ml_ + 64 hex chars
    assert "tenant_id" in data
    assert data["email"] == "dev@example.com"
    assert data["plan"] == "free"
    assert "key_prefix" in data
    assert data["key_prefix"] == data["api_key"][:7]
    assert "message" in data
    assert "not be shown again" in data["message"]


# ---------------------------------------------------------------------------
# Key works immediately after signup
# ---------------------------------------------------------------------------


def test_signup_key_works_immediately(tmp_path, monkeypatch):
    """API key returned by signup immediately authenticates against protected endpoints."""
    with _get_client(tmp_path, monkeypatch) as client:
        signup_resp = client.post(
            "/v1/auth/signup",
            json={"name": "Immediate User", "email": "immediate@example.com"},
        )
        assert signup_resp.status_code == 201
        api_key = signup_resp.json()["api_key"]
        tenant_id = signup_resp.json()["tenant_id"]

        auth_resp = client.get(
            "/_test/tenant",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    assert auth_resp.status_code == 200
    data = auth_resp.json()
    assert data["id"] == tenant_id
    assert data["email"] == "immediate@example.com"


# ---------------------------------------------------------------------------
# Plaintext key never stored — only SHA-256 hash
# ---------------------------------------------------------------------------


def test_signup_key_not_stored_plaintext(tmp_path, monkeypatch):
    """The plaintext API key is never persisted — only its SHA-256 hash is in the DB."""
    with _get_client(tmp_path, monkeypatch) as client:
        signup_resp = client.post(
            "/v1/auth/signup",
            json={"name": "Hash Check", "email": "hashcheck@example.com"},
        )
        assert signup_resp.status_code == 201
        api_key = signup_resp.json()["api_key"]

        async def _check_no_plaintext():
            db = app.state.system_db
            async with db.execute("SELECT key_hash FROM api_keys") as cur:
                rows = await cur.fetchall()
            # At least one key row exists
            assert len(rows) >= 1
            for row in rows:
                # Stored value is NOT the plaintext key
                assert row["key_hash"] != api_key
                # Stored value IS the SHA-256 of the plaintext key
                assert row["key_hash"] == hashlib.sha256(api_key.encode()).hexdigest()

        client.portal.call(_check_no_plaintext)


# ---------------------------------------------------------------------------
# Duplicate email → 409 Conflict
# ---------------------------------------------------------------------------


def test_signup_duplicate_email_409(tmp_path, monkeypatch):
    """Signing up twice with the same email returns 409 Conflict, not 500."""
    with _get_client(tmp_path, monkeypatch) as client:
        first = client.post(
            "/v1/auth/signup",
            json={"name": "First User", "email": "duplicate@example.com"},
        )
        assert first.status_code == 201

        second = client.post(
            "/v1/auth/signup",
            json={"name": "Second User", "email": "duplicate@example.com"},
        )
    assert second.status_code == 409
    body = second.json()
    # Exception handler wraps detail in {"error": ..., "message": ...}
    message = body.get("message") or body.get("detail", "")
    assert "email" in message.lower() or "account" in message.lower()


# ---------------------------------------------------------------------------
# Validation errors → 422
# ---------------------------------------------------------------------------


def test_signup_missing_email_422(tmp_path, monkeypatch):
    """POST without email field returns 422 Unprocessable Entity."""
    with _get_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/v1/auth/signup",
            json={"name": "No Email"},
        )
    assert response.status_code == 422


def test_signup_invalid_email_422(tmp_path, monkeypatch):
    """POST with malformed email returns 422 Unprocessable Entity."""
    with _get_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/v1/auth/signup",
            json={"name": "Bad Email", "email": "not-an-email"},
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Signup does NOT require Authorization header
# ---------------------------------------------------------------------------


def test_signup_no_auth_required(tmp_path, monkeypatch):
    """Signup endpoint is public — no Authorization header needed."""
    with _get_client(tmp_path, monkeypatch) as client:
        # POST without any Authorization header — must NOT return 401
        response = client.post(
            "/v1/auth/signup",
            json={"name": "Public Access", "email": "public@example.com"},
        )
    # Should succeed (201) without any auth header
    assert response.status_code != 401
    assert response.status_code == 201
