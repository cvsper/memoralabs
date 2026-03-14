"""
EmbeddingClient — Async Fireworks.ai embedding client with circuit breaker.

Responsibilities:
- POST batched text to Fireworks.ai embeddings endpoint asynchronously
- Trip circuit breaker on 429 or connection/timeout errors
- Auto-recover after cooldown period
- Return np.ndarray of shape (n, dim) or None when unavailable

Circuit breaker state:
- Closed (operating normally): _consecutive_failures < _max_failures
- Open (tripped): _consecutive_failures >= _max_failures, within cooldown
- Half-open (auto-recovery): cooldown elapsed, next call resets counter and retries
"""

import time

import httpx
import numpy as np


class EmbeddingClient:
    """Async Fireworks.ai embedding client with circuit breaker and batching."""

    def __init__(self, api_key: str, model: str, dim: int = 1024) -> None:
        self.api_key = api_key
        self.model = model
        self.dim = dim
        self._client = httpx.AsyncClient(timeout=30.0)

        # Circuit breaker state
        self._last_failure: float = 0.0
        self._cooldown: int = 120  # seconds before auto-recovery
        self._consecutive_failures: int = 0
        self._max_failures: int = 3

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def _available(self) -> bool:
        """Return True if the client is ready to make requests.

        - No api_key → never available.
        - Failures < max → available.
        - Failures >= max and cooldown elapsed → reset and become available.
        - Failures >= max and within cooldown → unavailable.
        """
        if not self.api_key:
            return False
        if self._consecutive_failures >= self._max_failures:
            if time.time() - self._last_failure > self._cooldown:
                # Cooldown elapsed — reset and allow next attempt
                self._consecutive_failures = 0
                self._last_failure = 0.0
                return True
            return False
        return True

    @property
    def is_available(self) -> bool:
        """Public accessor for circuit breaker status."""
        return self._available()

    def _trip(self) -> None:
        """Record a failure and potentially trip the circuit breaker."""
        self._last_failure = time.time()
        self._consecutive_failures += 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed(
        self, texts: list[str], batch_size: int = 20
    ) -> np.ndarray | None:
        """Embed a list of texts, returning shape (len(texts), dim) or None.

        Batches requests to avoid exceeding Fireworks.ai payload limits.
        Returns None if circuit breaker is open or any request fails.
        """
        if not self._available():
            return None

        all_embeddings: list[list[float]] = []
        try:
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                resp = await self._client.post(
                    "https://api.fireworks.ai/inference/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": self.model, "input": batch},
                )
                if resp.status_code == 429:
                    self._trip()
                    return None
                resp.raise_for_status()
                data = resp.json()
                embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(embeddings)
        except (httpx.ConnectError, httpx.TimeoutException):
            self._trip()
            return None

        # Reset consecutive failures on a fully successful call
        self._consecutive_failures = 0
        return np.array(all_embeddings, dtype=np.float32)

    async def embed_single(self, text: str) -> np.ndarray | None:
        """Convenience wrapper — embed a single text and return the row vector.

        Returns shape (1024,) or None.
        """
        result = await self.embed([text])
        if result is None:
            return None
        return result[0]

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._client.aclose()
