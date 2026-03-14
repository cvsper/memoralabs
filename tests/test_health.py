"""Tests for GET /health endpoint via FastAPI lifespan + ASGITransport."""

from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Provide an AsyncClient wired to the app, with DATA_DIR set to tmp_path."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    # Also patch the imported reference in main.py so lifespan uses tmp_path
    import app.main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    # Patch FIREWORKS_API_KEY in health router so embedding_configured=True in tests
    import app.routers.health as health_module
    monkeypatch.setattr(health_module, "FIREWORKS_API_KEY", "test-key")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.mark.anyio
async def test_health_returns_200(client):
    """GET /health returns HTTP 200."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_health_response_fields(client):
    """GET /health returns status, timestamp, and version fields."""
    response = await client.get("/health")
    data = response.json()
    assert data["status"] == "healthy"
    assert isinstance(data["timestamp"], str)
    assert data["version"] == "0.1.0"


@pytest.mark.anyio
async def test_health_timestamp_is_utc_iso(client):
    """GET /health timestamp can be parsed as ISO 8601 datetime."""
    response = await client.get("/health")
    ts = response.json()["timestamp"]
    # Should not raise
    parsed = datetime.fromisoformat(ts)
    assert parsed is not None


@pytest.mark.anyio
async def test_health_checks_fields(client):
    """GET /health returns checks sub-object with expected keys."""
    response = await client.get("/health")
    data = response.json()
    checks = data["checks"]
    assert "disk_mounted" in checks
    assert "disk_path" in checks
    assert "embedding_configured" in checks
    # disk_mounted is None locally (RENDER env not set)
    assert checks["disk_mounted"] is None
    # embedding_configured is True because fixture patches FIREWORKS_API_KEY
    assert checks["embedding_configured"] is True


@pytest.mark.anyio
async def test_health_degraded_when_no_embedding_key(tmp_path, monkeypatch):
    """GET /health returns degraded when FIREWORKS_API_KEY is not set."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import app.config as config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    import app.main as main_module
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    # Ensure FIREWORKS_API_KEY is empty
    import app.routers.health as health_module
    monkeypatch.setattr(health_module, "FIREWORKS_API_KEY", "")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        response = await ac.get("/health")
        assert response.status_code == 200  # always 200
        assert response.json()["status"] == "degraded"


@pytest.mark.anyio
async def test_root_returns_404_or_redirect(client):
    """GET / does not crash the app (404 or future landing page acceptable)."""
    response = await client.get("/")
    assert response.status_code != 500
