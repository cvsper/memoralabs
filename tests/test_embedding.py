"""
Tests for EmbeddingClient.

All tests mock httpx.AsyncClient.post so they never call Fireworks.ai.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.services.embedding import EmbeddingClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(embeddings: list[list[float]], status_code: int = 200) -> MagicMock:
    """Return a mock httpx Response with the given embedding data."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "data": [
            {"embedding": emb, "index": i}
            for i, emb in enumerate(embeddings)
        ],
        "model": "mixedbread-ai/mxbai-embed-large-v1",
    }
    return resp


def _random_embeddings(n: int, dim: int = 1024) -> list[list[float]]:
    rng = np.random.default_rng(42)
    return rng.random((n, dim)).tolist()


def _make_client(api_key: str = "test-key") -> EmbeddingClient:
    return EmbeddingClient(api_key=api_key, model="test-model", dim=1024)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embed_single_success():
    """embed_single returns ndarray of shape (1024,) on success."""
    client = _make_client()
    mock_resp = _make_mock_response(_random_embeddings(1))
    with patch.object(client._client, "post", new=AsyncMock(return_value=mock_resp)):
        result = await client.embed_single("hello world")

    assert result is not None
    assert isinstance(result, np.ndarray)
    assert result.shape == (1024,)
    assert result.dtype == np.float32


@pytest.mark.asyncio
async def test_embed_batch_success():
    """embed() with 3 texts returns shape (3, 1024)."""
    client = _make_client()
    mock_resp = _make_mock_response(_random_embeddings(3))
    with patch.object(client._client, "post", new=AsyncMock(return_value=mock_resp)):
        result = await client.embed(["a", "b", "c"])

    assert result is not None
    assert result.shape == (3, 1024)
    assert result.dtype == np.float32


@pytest.mark.asyncio
async def test_embed_no_api_key():
    """Client with empty api_key returns None immediately, no HTTP call made."""
    client = _make_client(api_key="")
    mock_post = AsyncMock()
    with patch.object(client._client, "post", new=mock_post):
        result = await client.embed(["text"])

    assert result is None
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_embed_429_trips_breaker():
    """429 response trips the circuit breaker and returns None."""
    client = _make_client()
    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch.object(client._client, "post", new=AsyncMock(return_value=mock_resp)):
        # Exhaust max_failures
        for _ in range(client._max_failures):
            result = await client.embed(["text"])
            assert result is None

    assert not client.is_available


@pytest.mark.asyncio
async def test_embed_breaker_recovery():
    """Circuit breaker resets after cooldown period elapses."""
    client = _make_client()
    # Trip the breaker by forcing failure count to max
    client._consecutive_failures = client._max_failures
    client._last_failure = time.time() - (client._cooldown + 1)

    # Breaker should self-recover on next _available() check
    assert client.is_available
    assert client._consecutive_failures == 0


@pytest.mark.asyncio
async def test_embed_timeout_trips_breaker():
    """httpx.TimeoutException trips the circuit breaker."""
    import httpx

    client = _make_client()
    with patch.object(
        client._client,
        "post",
        new=AsyncMock(side_effect=httpx.TimeoutException("timeout")),
    ):
        result = await client.embed(["text"])

    assert result is None
    assert client._consecutive_failures == 1
    assert client._last_failure > 0


@pytest.mark.asyncio
async def test_embed_connect_error_trips_breaker():
    """httpx.ConnectError trips the circuit breaker."""
    import httpx

    client = _make_client()
    with patch.object(
        client._client,
        "post",
        new=AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        ),
    ):
        result = await client.embed(["text"])

    assert result is None
    assert client._consecutive_failures == 1
    assert client._last_failure > 0


@pytest.mark.asyncio
async def test_embed_batching():
    """25 texts with batch_size=10 triggers 3 POST calls (10 + 10 + 5)."""
    client = _make_client()
    call_counts: list[int] = []

    async def mock_post(url, **kwargs):
        batch = kwargs.get("json", {}).get("input", [])
        call_counts.append(len(batch))
        return _make_mock_response(_random_embeddings(len(batch)))

    with patch.object(client._client, "post", new=mock_post):
        result = await client.embed([f"text {i}" for i in range(25)], batch_size=10)

    assert result is not None
    assert result.shape == (25, 1024)
    assert len(call_counts) == 3
    assert call_counts == [10, 10, 5]


@pytest.mark.asyncio
async def test_is_available_public_accessor():
    """is_available property reflects circuit breaker state."""
    client = _make_client()
    assert client.is_available

    # Trip breaker
    client._consecutive_failures = client._max_failures
    client._last_failure = time.time()
    assert not client.is_available


@pytest.mark.asyncio
async def test_close():
    """close() can be called without error."""
    client = _make_client()
    await client.close()  # should not raise
