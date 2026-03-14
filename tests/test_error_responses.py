"""DX-04 verification tests — structured error responses.

Proves that every error path returns {"error": "CODE", "message": "..."} JSON,
never HTML. Tests use Starlette TestClient (which triggers FastAPI lifespan)
following the established project pattern.

Scenarios covered:
1. 401 Unauthorized - no Authorization header
2. 401 Unauthorized - invalid API key
3. 404 Not Found - nonexistent memory ID
4. 422 Validation Error - empty body, includes details list
5. 409 Conflict - duplicate signup email
6. Content-Type: application/json on all error responses
"""
import hashlib
import uuid

from starlette.testclient import TestClient

from app.db.system import create_api_key, create_tenant
from app.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_API_KEY = "test-error-responses-key-abc123"
TEST_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
AUTH_HEADER = {"Authorization": f"Bearer {TEST_API_KEY}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(tmp_path, monkeypatch):
    """Patch dirs and return a Starlette TestClient context manager."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "VECTOR_INDEX_DIR", tmp_path / "indexes")
    import app.main as main_module

    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "VECTOR_INDEX_DIR", tmp_path / "indexes")
    return TestClient(app, raise_server_exceptions=False)


def _setup_tenant(client):
    """Create a tenant + API key and initialise the tenant DB."""
    system_db = app.state.system_db
    tenant_id = str(uuid.uuid4())

    async def _setup():
        await create_tenant(system_db, tenant_id, "DX Test", "dxtest@example.com")
        await create_api_key(
            system_db,
            str(uuid.uuid4()),
            tenant_id,
            TEST_KEY_HASH,
            "test",
            "dx-test-key",
        )
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id


# ---------------------------------------------------------------------------
# 1. 401 Unauthorized — no Authorization header
# ---------------------------------------------------------------------------


def test_401_no_auth_returns_structured_json(tmp_path, monkeypatch):
    """POST /v1/memory with no Authorization header returns structured JSON 401."""
    with _make_client(tmp_path, monkeypatch) as client:
        response = client.post("/v1/memory", json={"text": "hello"})

    assert response.status_code == 401
    data = response.json()
    assert "error" in data, "Response must have 'error' key"
    assert "message" in data, "Response must have 'message' key"
    assert isinstance(data["error"], str)
    assert isinstance(data["message"], str)
    assert data["error"] == "UNAUTHORIZED"
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 2. 401 Unauthorized — invalid API key
# ---------------------------------------------------------------------------


def test_401_invalid_key_returns_structured_json(tmp_path, monkeypatch):
    """POST /v1/memory with invalid API key returns structured JSON 401."""
    with _make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/v1/memory",
            json={"text": "hello"},
            headers={"Authorization": "Bearer ml_invalid_key_does_not_exist"},
        )

    assert response.status_code == 401
    data = response.json()
    assert "error" in data
    assert "message" in data
    assert isinstance(data["error"], str)
    assert isinstance(data["message"], str)
    assert data["error"] == "UNAUTHORIZED"
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 3. 404 Not Found — nonexistent memory ID
# ---------------------------------------------------------------------------


def test_404_nonexistent_id_returns_structured_json(tmp_path, monkeypatch):
    """GET /v1/memory/{id} for nonexistent ID returns structured JSON 404."""
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
    assert isinstance(data["error"], str)
    assert isinstance(data["message"], str)
    assert data["error"] == "NOT_FOUND"
    assert data["message"] == "Memory not found"
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 4. 422 Validation Error — empty body, includes details list
# ---------------------------------------------------------------------------


def test_422_empty_body_returns_structured_json_with_details(tmp_path, monkeypatch):
    """POST /v1/memory with empty body returns structured JSON 422 with details list."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        response = client.post(
            "/v1/memory",
            json={},
            headers=AUTH_HEADER,
        )

    assert response.status_code == 422
    data = response.json()
    assert "error" in data
    assert "message" in data
    assert "details" in data, "422 must include 'details' key"
    assert isinstance(data["error"], str)
    assert isinstance(data["message"], str)
    assert isinstance(data["details"], list), "'details' must be a list"
    assert len(data["details"]) > 0, "'details' must be non-empty"
    assert data["error"] == "VALIDATION_ERROR"
    assert data["message"] == "Request validation failed"
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 5. 409 Conflict — duplicate signup email returns structured JSON
# ---------------------------------------------------------------------------


def test_409_duplicate_signup_returns_structured_json(tmp_path, monkeypatch):
    """POST /v1/auth/signup with duplicate email returns structured JSON 409."""
    with _make_client(tmp_path, monkeypatch) as client:
        first = client.post(
            "/v1/auth/signup",
            json={"name": "First User", "email": "conflict@example.com"},
        )
        assert first.status_code == 201

        second = client.post(
            "/v1/auth/signup",
            json={"name": "Second User", "email": "conflict@example.com"},
        )

    assert second.status_code == 409
    data = second.json()
    assert "error" in data
    assert "message" in data
    assert isinstance(data["error"], str)
    assert isinstance(data["message"], str)
    assert data["error"] == "CONFLICT"
    assert second.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 6. Content-Type: application/json on all error codes
# ---------------------------------------------------------------------------


def test_all_error_responses_are_json_not_html(tmp_path, monkeypatch):
    """All error responses (401, 404, 409, 422) have Content-Type: application/json."""
    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)

        # 401 — no auth
        r401 = client.get("/v1/memory")
        assert r401.status_code == 401
        assert r401.headers["content-type"].startswith("application/json"), (
            f"Expected application/json, got {r401.headers['content-type']}"
        )

        # 404 — nonexistent memory
        r404 = client.get(f"/v1/memory/{uuid.uuid4()}", headers=AUTH_HEADER)
        assert r404.status_code == 404
        assert r404.headers["content-type"].startswith("application/json"), (
            f"Expected application/json, got {r404.headers['content-type']}"
        )

        # 422 — bad body
        r422 = client.post("/v1/memory", json={}, headers=AUTH_HEADER)
        assert r422.status_code == 422
        assert r422.headers["content-type"].startswith("application/json"), (
            f"Expected application/json, got {r422.headers['content-type']}"
        )

        # 409 — duplicate signup
        client.post("/v1/auth/signup", json={"name": "A", "email": "ct409@example.com"})
        r409 = client.post("/v1/auth/signup", json={"name": "B", "email": "ct409@example.com"})
        assert r409.status_code == 409
        assert r409.headers["content-type"].startswith("application/json"), (
            f"Expected application/json, got {r409.headers['content-type']}"
        )
