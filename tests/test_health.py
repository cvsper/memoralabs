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
async def test_root_returns_404_or_redirect(client):
    """GET / does not crash the app (404 or future landing page acceptable)."""
    response = await client.get("/")
    assert response.status_code != 500
