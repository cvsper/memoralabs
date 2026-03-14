"""
Integration tests for POST /v1/memory/search endpoint.

Tests cover:
- Basic search: returns results, empty DB, result fields, relevance order
- Scoped search: by user_id, agent_id, session_id (MEM-02, MEM-04)
- Metadata filtering: AND (default) and OR logic (RETR-05, MEM-03)
- Temporal decay: recent memories rank higher (MEM-09)
- Edge cases: deleted excluded, no-embedding excluded, limit, fallback
- Usage and response metadata: usage logged, memories_used/limit in response (DX-05)
- Entity-search e2e: entity extraction → entity retrieval → search pipeline

All tests use Starlette TestClient + monkeypatch DATA_DIR pattern.
Memories are seeded with pre-computed numpy embeddings (random, reproducible)
inserted directly into the tenant DB with embedding BLOBs AND added to the
vector index, simulating what the background task does in production.
"""

import hashlib
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.db.system import create_api_key, create_tenant
from app.main import app
from app.services.entity_extraction import process_entities_for_memory

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

TEST_API_KEY = "test-memory-search-key-xyz789"
TEST_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
AUTH_HEADER = {"Authorization": f"Bearer {TEST_API_KEY}"}

EMBEDDING_DIM = 1024


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures and helpers
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
        await create_tenant(system_db, tenant_id, "Search Test Tenant", f"search-{tenant_id[:8]}@example.com")
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=TEST_KEY_HASH,
            key_prefix="test",
            name="test-search-key",
        )
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id


def _random_embedding(seed: int) -> np.ndarray:
    """Return a reproducible random 1024-dim unit-normalized embedding."""
    rng = np.random.RandomState(seed)
    v = rng.randn(EMBEDDING_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _noisy_embedding(base: np.ndarray, noise_scale: float = 0.05) -> np.ndarray:
    """Return an embedding close to `base` with small random noise added."""
    # Compute a deterministic uint32 seed from base vector (abs + mod to stay in range)
    seed = int(abs(np.sum(base * 1000))) % (2**32)
    rng = np.random.RandomState(seed)
    noise = rng.randn(EMBEDDING_DIM).astype(np.float32) * noise_scale
    v = base + noise
    return v / np.linalg.norm(v)


def _seed_memory(
    client,
    tenant_id: str,
    text: str,
    embedding: np.ndarray,
    user_id: str | None = None,
    agent_id: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    created_at: int | None = None,
    is_deleted: int = 0,
) -> str:
    """Insert a memory row with embedding BLOB + add to vector index. Returns memory_id."""
    memory_id = str(uuid.uuid4())
    now = created_at if created_at is not None else int(time.time())

    async def _insert():
        conn = await app.state.tenant_manager.get_connection(tenant_id)
        await conn.execute(
            """
            INSERT INTO memories
                (id, text, text_hash, user_id, agent_id, session_id, metadata,
                 created_at, updated_at, embedding, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                text,
                hashlib.md5(text.lower().strip().encode()).hexdigest(),
                user_id,
                agent_id,
                session_id,
                json.dumps(metadata or {}),
                now,
                now,
                embedding.tobytes(),
                is_deleted,
            ),
        )
        await conn.commit()
        # Add to vector index so ANN search can find it
        await app.state.index_manager.add_vector(tenant_id, memory_id, embedding)

    client.portal.call(_insert)
    return memory_id


# ──────────────────────────────────────────────────────────────────────────────
# Basic search tests
# ──────────────────────────────────────────────────────────────────────────────


def test_search_returns_results(tmp_path, monkeypatch):
    """Seed memories with embeddings; mock embed_single; verify results returned with scores."""
    base_emb = _random_embedding(42)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid1 = _seed_memory(client, tenant_id, "Memory about dogs", _noisy_embedding(base_emb))
        _seed_memory(client, tenant_id, "Memory about cats", _random_embedding(99))
        _seed_memory(client, tenant_id, "Memory about fish", _random_embedding(77))

        # Mock embedding client to return a vector close to the first memory
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "tell me about dogs"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert len(data["results"]) > 0
    # The dog memory should be in results
    result_ids = [r["id"] for r in data["results"]]
    assert mid1 in result_ids


def test_search_empty_db(tmp_path, monkeypatch):
    """Search with no memories returns empty results (not an error)."""
    base_emb = _random_embedding(1)

    with _make_client(tmp_path, monkeypatch) as client:
        _setup_tenant(client)
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "anything"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert data["total"] == 0


def test_search_result_fields(tmp_path, monkeypatch):
    """Each search result has all required fields: id, text, score, metadata, user_id, agent_id, session_id, created_at."""
    base_emb = _random_embedding(10)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _seed_memory(
            client,
            tenant_id,
            "Structured test memory",
            _noisy_embedding(base_emb),
            user_id="user-1",
            agent_id="agent-1",
            session_id="session-1",
            metadata={"source": "test"},
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "structured test"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 1
    result = data["results"][0]
    for field in ("id", "text", "score", "metadata", "user_id", "agent_id", "session_id", "created_at"):
        assert field in result, f"Missing field: {field}"
    assert isinstance(result["score"], float)
    assert result["user_id"] == "user-1"
    assert result["agent_id"] == "agent-1"
    assert result["session_id"] == "session-1"
    assert result["metadata"] == {"source": "test"}


def test_search_relevance_order(tmp_path, monkeypatch):
    """Results are sorted by score descending — most similar memory first."""
    # Create a base query vector and three memories at different distances
    query_emb = _random_embedding(55)

    # Make memory embeddings at varying similarity to query
    # Close: large noise_scale = 0 (identical), medium: 0.3, far: completely different
    close_emb = _noisy_embedding(query_emb, noise_scale=0.01)
    medium_emb = _noisy_embedding(query_emb, noise_scale=0.5)
    far_emb = _random_embedding(200)  # Unrelated seed

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_close = _seed_memory(client, tenant_id, "Very similar memory", close_emb)
        mid_medium = _seed_memory(client, tenant_id, "Somewhat similar memory", medium_emb)
        mid_far = _seed_memory(client, tenant_id, "Unrelated memory", far_emb)
        app.state.embedding_client.embed_single = AsyncMock(return_value=query_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "test relevance order", "limit": 3},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) >= 2
    # Verify scores are in descending order
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True), f"Scores not descending: {scores}"
    # The close memory should rank highest
    assert results[0]["id"] == mid_close


# ──────────────────────────────────────────────────────────────────────────────
# Scoped search tests (MEM-02, MEM-04)
# ──────────────────────────────────────────────────────────────────────────────


def test_search_scoped_by_user_id(tmp_path, monkeypatch):
    """Search with user_id scope returns only that user's memories."""
    base_emb = _random_embedding(11)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_a = _seed_memory(client, tenant_id, "User A memory", _noisy_embedding(base_emb), user_id="user-a")
        mid_b = _seed_memory(client, tenant_id, "User B memory", _noisy_embedding(base_emb, 0.1), user_id="user-b")
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "memory", "user_id": "user-a"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["id"] for r in data["results"]]
    assert mid_a in result_ids
    assert mid_b not in result_ids


def test_search_scoped_by_agent_id(tmp_path, monkeypatch):
    """Search with agent_id scope returns only that agent's memories."""
    base_emb = _random_embedding(22)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_a = _seed_memory(client, tenant_id, "Agent Alpha memory", _noisy_embedding(base_emb), agent_id="agent-alpha")
        mid_b = _seed_memory(client, tenant_id, "Agent Beta memory", _noisy_embedding(base_emb, 0.1), agent_id="agent-beta")
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "memory", "agent_id": "agent-alpha"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["id"] for r in data["results"]]
    assert mid_a in result_ids
    assert mid_b not in result_ids


def test_search_scoped_by_session_id(tmp_path, monkeypatch):
    """Search with session_id scope returns only that session's memories."""
    base_emb = _random_embedding(33)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_s1 = _seed_memory(client, tenant_id, "Session 1 memory", _noisy_embedding(base_emb), session_id="session-1")
        mid_s2 = _seed_memory(client, tenant_id, "Session 2 memory", _noisy_embedding(base_emb, 0.1), session_id="session-2")
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "memory", "session_id": "session-1"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["id"] for r in data["results"]]
    assert mid_s1 in result_ids
    assert mid_s2 not in result_ids


# ──────────────────────────────────────────────────────────────────────────────
# Metadata filtering tests (RETR-05, MEM-03)
# ──────────────────────────────────────────────────────────────────────────────


def test_search_metadata_filter_and(tmp_path, monkeypatch):
    """metadata_filter with operator=and (default): only memories matching ALL conditions."""
    base_emb = _random_embedding(44)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        # Both conditions match
        mid_both = _seed_memory(
            client, tenant_id, "Matching memory",
            _noisy_embedding(base_emb),
            metadata={"source": "email", "priority": "high"},
        )
        # Only one condition matches
        mid_one = _seed_memory(
            client, tenant_id, "Partial match memory",
            _noisy_embedding(base_emb, 0.1),
            metadata={"source": "email", "priority": "low"},
        )
        # Neither condition matches
        mid_none = _seed_memory(
            client, tenant_id, "No match memory",
            _noisy_embedding(base_emb, 0.2),
            metadata={"source": "slack"},
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={
                "query": "memory",
                "metadata_filter": {"source": "email", "priority": "high"},
                "metadata_filter_operator": "and",
            },
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["id"] for r in data["results"]]
    assert mid_both in result_ids
    assert mid_one not in result_ids
    assert mid_none not in result_ids


def test_search_metadata_filter_or(tmp_path, monkeypatch):
    """metadata_filter with operator=or: memories matching AT LEAST ONE condition."""
    base_emb = _random_embedding(66)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_a = _seed_memory(
            client, tenant_id, "Email memory",
            _noisy_embedding(base_emb),
            metadata={"source": "email"},
        )
        mid_b = _seed_memory(
            client, tenant_id, "High priority memory",
            _noisy_embedding(base_emb, 0.1),
            metadata={"priority": "high"},
        )
        mid_c = _seed_memory(
            client, tenant_id, "Neither condition memory",
            _noisy_embedding(base_emb, 0.2),
            metadata={"source": "slack", "priority": "low"},
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={
                "query": "memory",
                "metadata_filter": {"source": "email", "priority": "high"},
                "metadata_filter_operator": "or",
            },
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    result_ids = [r["id"] for r in data["results"]]
    assert mid_a in result_ids
    assert mid_b in result_ids
    assert mid_c not in result_ids


def test_search_metadata_filter_no_match(tmp_path, monkeypatch):
    """Metadata filter with no matching memories returns empty results."""
    base_emb = _random_embedding(88)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _seed_memory(
            client, tenant_id, "Some memory",
            _noisy_embedding(base_emb),
            metadata={"source": "api"},
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={
                "query": "test",
                "metadata_filter": {"source": "nonexistent-source"},
            },
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    assert resp.json()["results"] == []
    assert resp.json()["total"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Temporal decay tests (MEM-09)
# ──────────────────────────────────────────────────────────────────────────────


def test_search_decay_boosts_recent(tmp_path, monkeypatch):
    """Two memories with identical vector similarity: newer one has higher final score."""
    query_emb = _random_embedding(101)
    # Both memories have very similar embeddings (same seed-based slight noise)
    similar_emb = _noisy_embedding(query_emb, noise_scale=0.01)

    now = int(time.time())
    old_time = now - (90 * 24 * 3600)  # 90 days ago

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_new = _seed_memory(
            client, tenant_id, "New memory", similar_emb, created_at=now
        )
        mid_old = _seed_memory(
            client, tenant_id, "Old memory", similar_emb, created_at=old_time
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=query_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "test decay", "limit": 2},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) == 2

    # Find scores for each memory
    score_map = {r["id"]: r["score"] for r in results}
    assert mid_new in score_map
    assert mid_old in score_map
    # Newer memory should have higher score (decay boosts recent)
    assert score_map[mid_new] > score_map[mid_old], (
        f"Expected new ({score_map[mid_new]:.4f}) > old ({score_map[mid_old]:.4f})"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Edge case tests
# ──────────────────────────────────────────────────────────────────────────────


def test_search_excludes_deleted(tmp_path, monkeypatch):
    """Deleted memory (is_deleted=1) is not returned even if vector matches."""
    base_emb = _random_embedding(111)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        mid_deleted = _seed_memory(
            client, tenant_id, "Deleted memory",
            _noisy_embedding(base_emb),
            is_deleted=1,
        )
        mid_alive = _seed_memory(
            client, tenant_id, "Alive memory",
            _noisy_embedding(base_emb, 0.1),
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "test deleted"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    result_ids = [r["id"] for r in resp.json()["results"]]
    assert mid_deleted not in result_ids
    assert mid_alive in result_ids


def test_search_excludes_no_embedding(tmp_path, monkeypatch):
    """Memory without an embedding BLOB is excluded from search candidates."""
    base_emb = _random_embedding(222)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        # Seed one memory without embedding (insert directly, skip index)
        mid_no_emb = str(uuid.uuid4())
        now = int(time.time())

        async def _insert_no_emb():
            conn = await app.state.tenant_manager.get_connection(tenant_id)
            await conn.execute(
                """
                INSERT INTO memories
                    (id, text, text_hash, user_id, agent_id, session_id, metadata,
                     created_at, updated_at, is_deleted)
                VALUES (?, ?, ?, NULL, NULL, NULL, '{}', ?, ?, 0)
                """,
                (mid_no_emb, "No embedding memory", "hash-noemb", now, now),
            )
            await conn.commit()

        client.portal.call(_insert_no_emb)

        mid_with_emb = _seed_memory(
            client, tenant_id, "Has embedding memory", _noisy_embedding(base_emb)
        )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "test no embedding"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    result_ids = [r["id"] for r in resp.json()["results"]]
    assert mid_no_emb not in result_ids
    assert mid_with_emb in result_ids


def test_search_limit(tmp_path, monkeypatch):
    """Search with limit=3 returns at most 3 results even when more memories exist."""
    base_emb = _random_embedding(333)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        for i in range(10):
            _seed_memory(
                client, tenant_id,
                f"Memory number {i}",
                _noisy_embedding(base_emb, noise_scale=0.01 * (i + 1)),
            )
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "memory", "limit": 3},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["results"]) == 3
    assert data["total"] == 3


def test_search_embedding_unavailable_fallback(tmp_path, monkeypatch):
    """When embed_single returns None, search falls back to recency sort (not empty)."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        now = int(time.time())
        # Seed 3 memories at different ages
        _seed_memory(client, tenant_id, "Oldest memory", _random_embedding(1), created_at=now - 300)
        _seed_memory(client, tenant_id, "Middle memory", _random_embedding(2), created_at=now - 200)
        mid_newest = _seed_memory(client, tenant_id, "Newest memory", _random_embedding(3), created_at=now - 100)

        # Circuit breaker is open — embed_single returns None
        app.state.embedding_client.embed_single = AsyncMock(return_value=None)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "fallback test"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    # Should return memories (not empty) — fallback to recency sort
    assert len(data["results"]) > 0
    # First result should be the newest memory (created_at DESC)
    assert data["results"][0]["id"] == mid_newest


# ──────────────────────────────────────────────────────────────────────────────
# Usage and response metadata tests (DX-05, MEM-11)
# ──────────────────────────────────────────────────────────────────────────────


def test_search_usage_logged(tmp_path, monkeypatch):
    """Search logs operation=memory.search with status_code=200 in usage_log."""
    base_emb = _random_embedding(444)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _seed_memory(client, tenant_id, "Usage test memory", _noisy_embedding(base_emb))
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        client.post(
            "/v1/memory/search",
            json={"query": "usage log test"},
            headers=AUTH_HEADER,
        )

        async def _check_usage():
            system_db = app.state.system_db
            async with system_db.execute(
                "SELECT operation, endpoint, status_code FROM usage_log "
                "WHERE tenant_id = ? AND operation = 'memory.search' "
                "ORDER BY id DESC LIMIT 1",
                (tenant_id,),
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        result = client.portal.call(_check_usage)

    assert result is not None
    assert result["operation"] == "memory.search"
    assert result["endpoint"] == "/v1/memory/search"
    assert result["status_code"] == 200


def test_search_response_includes_quota(tmp_path, monkeypatch):
    """Search response includes memories_used and memories_limit fields (DX-05)."""
    base_emb = _random_embedding(555)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _seed_memory(client, tenant_id, "Quota test memory", _noisy_embedding(base_emb))
        _seed_memory(client, tenant_id, "Quota test memory 2", _noisy_embedding(base_emb, 0.1))
        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "quota"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "memories_used" in data, "Missing memories_used in response"
    assert "memories_limit" in data, "Missing memories_limit in response"
    assert isinstance(data["memories_used"], int)
    assert isinstance(data["memories_limit"], int)
    assert data["memories_used"] == 2  # 2 non-deleted memories seeded
    assert data["memories_limit"] == 1000  # default free plan limit


# ──────────────────────────────────────────────────────────────────────────────
# Entity-search end-to-end test
# ──────────────────────────────────────────────────────────────────────────────


def test_entity_extraction_then_search_e2e(tmp_path, monkeypatch):
    """Full e2e: seed memory -> extract entities -> entity retrieval -> search.

    Pipeline:
      1. Seed memory "Alice works at Google in New York" with embedding
      2. Call process_entities_for_memory directly (simulates background task)
      3. Verify entities written to DB (entities table has rows)
      4. Verify relations written (relations table has rows for this memory)
      5. Call GET /v1/memory/{memory_id}/entities and verify entities returned
      6. Search for "Google employee" with mock embedding; verify memory in results
    """
    text = "Alice works at Google in New York"
    memory_emb = _random_embedding(666)
    query_emb = _noisy_embedding(memory_emb, noise_scale=0.05)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        memory_id = _seed_memory(client, tenant_id, text, memory_emb)

        # Step 2: Run entity extraction (simulating what background task does)
        async def _extract():
            conn = await app.state.tenant_manager.get_connection(tenant_id)
            result = await process_entities_for_memory(conn, memory_id, text)
            return result

        extraction_result = client.portal.call(_extract)

        # Step 3: Verify entities were written
        assert extraction_result["entities_found"] > 0, "No entities extracted from test text"
        assert extraction_result["relations_found"] > 0, "No relations extracted from test text"

        # Step 4: Verify at least one relation links to our memory
        async def _verify_db():
            conn = await app.state.tenant_manager.get_connection(tenant_id)
            async with conn.execute(
                "SELECT COUNT(*) FROM relations WHERE memory_id = ?",
                (memory_id,),
            ) as cur:
                row = await cur.fetchone()
            relation_count = row[0]

            async with conn.execute(
                "SELECT COUNT(*) FROM entities",
            ) as cur:
                row = await cur.fetchone()
            entity_count = row[0]
            return entity_count, relation_count

        entity_count, relation_count = client.portal.call(_verify_db)
        assert entity_count > 0, "No entities in DB after extraction"
        assert relation_count > 0, "No relations in DB for this memory"

        # Step 5: GET /v1/memory/{memory_id}/entities and verify entities returned
        entities_resp = client.get(
            f"/v1/memory/{memory_id}/entities",
            headers=AUTH_HEADER,
        )
        assert entities_resp.status_code == 200
        entities_data = entities_resp.json()
        assert entities_data["total_entities"] > 0, "No entities returned via API"
        assert entities_data["total_relations"] > 0, "No relations returned via API"

        # Verify expected entities: Alice (person), Google (org/person), New York (location)
        entity_names = [e["name"] for e in entities_data["entities"]]
        assert any("Alice" in n for n in entity_names), f"Alice not in entities: {entity_names}"

        # Step 6: Search and verify memory is in results
        app.state.embedding_client.embed_single = AsyncMock(return_value=query_emb)

        search_resp = client.post(
            "/v1/memory/search",
            json={"query": "Google employee"},
            headers=AUTH_HEADER,
        )
        assert search_resp.status_code == 200
        search_data = search_resp.json()
        search_ids = [r["id"] for r in search_data["results"]]
        assert memory_id in search_ids, (
            f"Memory {memory_id} not found in search results. Got: {search_ids}"
        )
