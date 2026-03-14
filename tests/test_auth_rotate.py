"""Tests for POST /v1/auth/keys/rotate endpoint."""
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


def _signup(client, email="rotate@example.com", name="Rotate Tester"):
    """Sign up and return (api_key, tenant_id)."""
    resp = client.post("/v1/auth/signup", json={"name": name, "email": email})
    assert resp.status_code == 201, f"Signup failed: {resp.text}"
    data = resp.json()
    return data["api_key"], data["tenant_id"]


# ---------------------------------------------------------------------------
# Rotation returns a new key
# ---------------------------------------------------------------------------


def test_rotate_returns_new_key(tmp_path, monkeypatch):
    """Rotate returns 200 with new api_key, key_prefix, and message. New key differs from original."""
    with _get_client(tmp_path, monkeypatch) as client:
        old_key, _ = _signup(client)

        resp = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": f"Bearer {old_key}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "api_key" in data
    assert data["api_key"].startswith("ml_")
    assert len(data["api_key"]) == 67  # ml_ + 64 hex chars
    assert "key_prefix" in data
    assert data["key_prefix"] == data["api_key"][:7]
    assert "message" in data
    assert data["api_key"] != old_key


# ---------------------------------------------------------------------------
# Old key stops working after rotation
# ---------------------------------------------------------------------------


def test_rotate_old_key_stops_working(tmp_path, monkeypatch):
    """After rotation, the old key returns 401 on protected endpoints."""
    with _get_client(tmp_path, monkeypatch) as client:
        old_key, _ = _signup(client, email="oldkey@example.com")

        rotate_resp = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert rotate_resp.status_code == 200

        # Old key must now be rejected
        check_resp = client.get(
            "/_test/tenant",
            headers={"Authorization": f"Bearer {old_key}"},
        )

    assert check_resp.status_code == 401


# ---------------------------------------------------------------------------
# New key works immediately after rotation
# ---------------------------------------------------------------------------


def test_rotate_new_key_works(tmp_path, monkeypatch):
    """New key returned by rotation immediately authenticates and tenant_id matches original."""
    with _get_client(tmp_path, monkeypatch) as client:
        old_key, original_tenant_id = _signup(client, email="newkey@example.com")

        rotate_resp = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert rotate_resp.status_code == 200
        new_key = rotate_resp.json()["api_key"]

        # New key must work and return the same tenant_id
        check_resp = client.get(
            "/_test/tenant",
            headers={"Authorization": f"Bearer {new_key}"},
        )

    assert check_resp.status_code == 200
    assert check_resp.json()["id"] == original_tenant_id


# ---------------------------------------------------------------------------
# Memories survive rotation (core AUTH-05 requirement)
# ---------------------------------------------------------------------------


def test_rotate_preserves_memories(tmp_path, monkeypatch):
    """Memories created with old key are accessible with new key — tenant_id unchanged."""
    with _get_client(tmp_path, monkeypatch) as client:
        old_key, _ = _signup(client, email="memories@example.com")

        # Create a memory with the old key
        create_resp = client.post(
            "/v1/memory",
            headers={"Authorization": f"Bearer {old_key}"},
            json={"text": "important memory that must survive rotation"},
        )
        assert create_resp.status_code == 201, f"Memory creation failed: {create_resp.text}"
        memory_id = create_resp.json()["id"]

        # Rotate
        rotate_resp = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": f"Bearer {old_key}"},
        )
        assert rotate_resp.status_code == 200
        new_key = rotate_resp.json()["api_key"]

        # Access the memory with the new key
        get_resp = client.get(
            f"/v1/memory/{memory_id}",
            headers={"Authorization": f"Bearer {new_key}"},
        )

    assert get_resp.status_code == 200
    assert get_resp.json()["text"] == "important memory that must survive rotation"


# ---------------------------------------------------------------------------
# Rotation requires authentication
# ---------------------------------------------------------------------------


def test_rotate_requires_auth(tmp_path, monkeypatch):
    """POST /v1/auth/keys/rotate without Authorization header returns 401."""
    with _get_client(tmp_path, monkeypatch) as client:
        resp = client.post("/v1/auth/keys/rotate")

    assert resp.status_code == 401


def test_rotate_invalid_key_401(tmp_path, monkeypatch):
    """POST /v1/auth/keys/rotate with invalid key returns 401."""
    with _get_client(tmp_path, monkeypatch) as client:
        resp = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": "Bearer invalid-key-that-does-not-exist"},
        )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Double rotation — each new key replaces the previous
# ---------------------------------------------------------------------------


def test_double_rotate(tmp_path, monkeypatch):
    """After two rotations: key A and key B return 401; key C works."""
    with _get_client(tmp_path, monkeypatch) as client:
        key_a, _ = _signup(client, email="doublerotate@example.com")

        # First rotation: A → B
        resp1 = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": f"Bearer {key_a}"},
        )
        assert resp1.status_code == 200
        key_b = resp1.json()["api_key"]

        # Second rotation: B → C
        resp2 = client.post(
            "/v1/auth/keys/rotate",
            headers={"Authorization": f"Bearer {key_b}"},
        )
        assert resp2.status_code == 200
        key_c = resp2.json()["api_key"]

        # Key A must be dead
        check_a = client.get("/_test/tenant", headers={"Authorization": f"Bearer {key_a}"})
        # Key B must be dead
        check_b = client.get("/_test/tenant", headers={"Authorization": f"Bearer {key_b}"})
        # Key C must work
        check_c = client.get("/_test/tenant", headers={"Authorization": f"Bearer {key_c}"})

    assert check_a.status_code == 401
    assert check_b.status_code == 401
    assert check_c.status_code == 200
