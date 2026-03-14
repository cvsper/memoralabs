"""
Tests for the confidence scoring service (app/services/confidence.py).

Covers:
Unit tests (compute_confidence directly):
- test_confidence_perfect_match: high sim, full entity overlap, high access, recent -> near 1.0
- test_confidence_worst_match: low sim, no entity overlap, zero access, old -> near 0.04
- test_confidence_similarity_component: vary only raw_cosine/max_cosine, verify 40% weight
- test_confidence_entity_overlap_component: vary only entity overlap, verify 30% weight
- test_confidence_engagement_component: vary access_count, verify logarithmic scaling
- test_confidence_freshness_component: vary created_at, verify freshness degrades over time
- test_confidence_bounds: always between 0.0 and 1.0 with extreme inputs
- test_confidence_no_query_entities: empty query_entities -> entity_overlap_ratio = 0.0

Integration tests (search endpoint via TestClient):
- test_search_results_include_confidence: POST /v1/memory/search returns confidence in every result
- test_search_fallback_confidence_zero: mock embedding returns None -> all results have confidence=0.0
"""

import hashlib
import json
import math
import time
import uuid
from unittest.mock import AsyncMock

import numpy as np
import pytest
from starlette.testclient import TestClient

from app.db.system import create_api_key, create_tenant
from app.main import app
from app.services.confidence import compute_confidence


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

EMBEDDING_DIM = 1024


def _recent_ts() -> int:
    """Return the current Unix timestamp (brand-new memory)."""
    return int(time.time())


def _old_ts(days: int = 365) -> int:
    """Return a Unix timestamp for a memory created `days` days ago."""
    return int(time.time()) - days * 86_400


def _entities_with(names: list[str]) -> list[dict]:
    """Build a minimal entity list with the given names (type=person)."""
    return [{"name": n, "type": "person"} for n in names]


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — compute_confidence
# ──────────────────────────────────────────────────────────────────────────────


def test_confidence_perfect_match():
    """Perfect inputs across all 4 components yield confidence near 1.0."""
    # sim_norm = 0.95/0.95 = 1.0 -> 0.40
    # entity_overlap: query has Alice, memory text has Alice -> overlap=1/1=1.0 -> 0.30
    # engagement: access_count=100 -> log(101)/log(101)=1.0 -> 0.20
    # freshness: brand-new memory -> ~1.0 -> 0.10
    conf = compute_confidence(
        raw_cosine=0.95,
        max_cosine_in_set=0.95,
        query_entities=_entities_with(["Alice"]),
        memory_text="Alice met Bob at the conference",
        access_count=100,
        created_at=_recent_ts(),
    )
    assert conf >= 0.95, f"Expected near 1.0, got {conf}"
    assert 0.0 <= conf <= 1.0


def test_confidence_worst_match():
    """Worst-case inputs yield a very low confidence (driven mainly by sim_norm=0.1/0.95)."""
    # sim_norm = 0.1/0.95 ~ 0.105 -> 0.40 * 0.105 = 0.042
    # entity_overlap: query has Alice, memory has Bob -> overlap=0/1=0.0 -> 0.0
    # engagement: access_count=0 -> log(1)/log(101)=0.0 -> 0.0
    # freshness: 365 days -> 0.5^(365/30) ~ 0.000047 -> 0.10 * ~0.000047 ~ 0.0
    conf = compute_confidence(
        raw_cosine=0.1,
        max_cosine_in_set=0.95,
        query_entities=_entities_with(["Alice"]),
        memory_text="Bob worked at the company",
        access_count=0,
        created_at=_old_ts(days=365),
    )
    assert conf < 0.1, f"Expected very low confidence, got {conf}"
    assert 0.0 <= conf <= 1.0


def test_confidence_similarity_component():
    """With only sim_norm varying, confidence scales at 40% weight."""
    # entity_overlap=0 (no query entities), engagement=0, freshness~0 (very old)
    # So confidence ~ 0.40 * (raw_cosine / max_cosine)
    old_ts = _old_ts(days=3650)  # ~10 years old -> freshness ~ 0

    conf_high = compute_confidence(
        raw_cosine=0.9,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=0,
        created_at=old_ts,
    )
    conf_low = compute_confidence(
        raw_cosine=0.45,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=0,
        created_at=old_ts,
    )
    # conf_high should be roughly double conf_low (sim_norm 1.0 vs 0.5)
    assert conf_high > conf_low * 1.8, (
        f"Expected conf_high ({conf_high}) to be ~2x conf_low ({conf_low})"
    )


def test_confidence_entity_overlap_component():
    """Entity overlap component scales at 30% weight when other components are minimal."""
    old_ts = _old_ts(days=3650)

    # Full overlap: query has Alice, memory also has Alice
    conf_full_overlap = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=_entities_with(["Alice"]),
        memory_text="Alice went to the store",
        access_count=0,
        created_at=old_ts,
    )
    # No overlap: query has Alice, memory has Bob
    conf_no_overlap = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=_entities_with(["Alice"]),
        memory_text="Bob went to the store",
        access_count=0,
        created_at=old_ts,
    )
    # Full overlap should be ~0.30 higher than no overlap
    diff = conf_full_overlap - conf_no_overlap
    assert diff >= 0.25, f"Expected ~0.30 difference from entity overlap, got {diff:.4f}"


def test_confidence_engagement_component():
    """Engagement component scales logarithmically at 20% weight."""
    old_ts = _old_ts(days=3650)

    # Zero access -> engagement = 0
    conf_zero = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=0,
        created_at=old_ts,
    )
    # 100 accesses -> engagement = log(101)/log(101) = 1.0 -> 0.20 contribution
    conf_hundred = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=100,
        created_at=old_ts,
    )
    # 10 accesses -> log(11)/log(101) ~ 0.524 -> 0.20 * 0.524 = 0.105 contribution
    conf_ten = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=10,
        created_at=old_ts,
    )
    # Logarithmic: 100 > 10 > 0
    assert conf_hundred > conf_ten > conf_zero, (
        f"Expected logarithmic ordering: {conf_hundred} > {conf_ten} > {conf_zero}"
    )
    # Full engagement difference should be ~0.20
    diff = conf_hundred - conf_zero
    assert 0.15 <= diff <= 0.25, f"Expected ~0.20 engagement difference, got {diff:.4f}"


def test_confidence_freshness_component():
    """Freshness decreases with memory age (10% weight component)."""
    # All other components are zero: raw_cosine=0, no entities, no access
    conf_new = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=0,
        created_at=_recent_ts(),
    )
    conf_month = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=0,
        created_at=_old_ts(days=30),
    )
    conf_quarter = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="some text",
        access_count=0,
        created_at=_old_ts(days=90),
    )
    # Freshness degrades over time
    assert conf_new > conf_month > conf_quarter, (
        f"Expected new ({conf_new}) > month ({conf_month}) > quarter ({conf_quarter})"
    )
    # Fresh memory freshness component is ~0.10 (decay_factor(now) ~ 1.0 -> 0.10 * 1.0 = 0.10)
    assert conf_new <= 0.12, f"Expected freshness-only contribution ~0.10, got {conf_new}"


def test_confidence_bounds():
    """Confidence is always in [0.0, 1.0] for extreme inputs."""
    # Way over 1.0 inputs
    conf_over = compute_confidence(
        raw_cosine=999.0,
        max_cosine_in_set=0.1,  # sim_norm = 9990 -> capped
        query_entities=_entities_with(["Alice", "Bob", "Charlie"]),
        memory_text="Alice Bob Charlie in some text",
        access_count=999999,
        created_at=_recent_ts(),
    )
    assert 0.0 <= conf_over <= 1.0, f"Confidence out of bounds: {conf_over}"

    # Zero everything
    conf_zero = compute_confidence(
        raw_cosine=0.0,
        max_cosine_in_set=0.0,  # max_cosine=0 -> sim_norm=0
        query_entities=[],
        memory_text="",
        access_count=0,
        created_at=_old_ts(days=36500),  # ~100 years old
    )
    assert 0.0 <= conf_zero <= 1.0, f"Confidence out of bounds: {conf_zero}"

    # Negative cosine (shouldn't happen in practice but defensive)
    conf_neg = compute_confidence(
        raw_cosine=-0.5,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="text",
        access_count=0,
        created_at=_old_ts(days=30),
    )
    assert 0.0 <= conf_neg <= 1.0, f"Confidence out of bounds: {conf_neg}"


def test_confidence_no_query_entities():
    """Empty query_entities list -> entity_overlap_ratio = 0.0 (no crash)."""
    conf = compute_confidence(
        raw_cosine=0.8,
        max_cosine_in_set=0.9,
        query_entities=[],
        memory_text="Alice works at Google in New York",
        access_count=5,
        created_at=_recent_ts(),
    )
    # Should succeed, no entity overlap contribution
    assert 0.0 <= conf <= 1.0
    # Similarity component: 0.40 * (0.8/0.9) = 0.356
    # Entity overlap: 0.0
    # Engagement: 0.20 * log(6)/log(101) ~ 0.20 * 0.380 = 0.076
    # Freshness: 0.10 * ~1.0 = ~0.10
    # Total: ~0.53 +/- some variation
    assert conf > 0.3, f"Expected reasonable confidence with good similarity, got {conf}"


# ──────────────────────────────────────────────────────────────────────────────
# Integration fixtures (follow test_memory_search.py pattern)
# ──────────────────────────────────────────────────────────────────────────────

TEST_API_KEY = "test-confidence-key-abc123"
TEST_KEY_HASH = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
AUTH_HEADER = {"Authorization": f"Bearer {TEST_API_KEY}"}


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
    """Return a Starlette TestClient with isolated dirs."""
    _patch_dirs(tmp_path, monkeypatch)
    return TestClient(app, raise_server_exceptions=True)


def _setup_tenant(client) -> str:
    """Create a tenant + API key in the system DB and init tenant DB. Returns tenant_id."""
    system_db = app.state.system_db
    tenant_id = str(uuid.uuid4())

    async def _setup():
        await create_tenant(system_db, tenant_id, "Confidence Test", f"conf-{tenant_id[:8]}@example.com")
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=TEST_KEY_HASH,
            key_prefix="test",
            name="test-confidence-key",
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
    """Return an embedding close to base with small random noise."""
    seed = int(abs(np.sum(base * 1000))) % (2**32)
    rng = np.random.RandomState(seed)
    noise = rng.randn(EMBEDDING_DIM).astype(np.float32) * noise_scale
    v = base + noise
    return v / np.linalg.norm(v)


def _seed_memory(client, tenant_id: str, text: str, embedding: np.ndarray) -> str:
    """Insert a memory with embedding into the tenant DB and vector index. Returns memory_id."""
    memory_id = str(uuid.uuid4())
    now = int(time.time())

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
                None,
                None,
                None,
                "{}",
                now,
                now,
                embedding.tobytes(),
                0,
            ),
        )
        await conn.commit()
        await app.state.index_manager.add_vector(tenant_id, memory_id, embedding)

    client.portal.call(_insert)
    return memory_id


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests
# ──────────────────────────────────────────────────────────────────────────────


def test_search_results_include_confidence(tmp_path, monkeypatch):
    """POST /v1/memory/search returns a confidence field (0.0-1.0) on every result."""
    base_emb = _random_embedding(42)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        _seed_memory(client, tenant_id, "Memory about machine learning", _noisy_embedding(base_emb))
        _seed_memory(client, tenant_id, "Memory about deep learning", _noisy_embedding(base_emb, 0.1))
        _seed_memory(client, tenant_id, "Memory about unrelated topic", _random_embedding(99))

        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "machine learning topics"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) > 0, "Expected at least one result"

    for result in results:
        assert "confidence" in result, f"Missing 'confidence' field in result: {result}"
        conf = result["confidence"]
        assert isinstance(conf, (int, float)), f"confidence must be numeric, got {type(conf)}"
        assert 0.0 <= conf <= 1.0, f"confidence out of [0.0, 1.0]: {conf}"


def test_search_fallback_confidence_zero(tmp_path, monkeypatch):
    """When embed_single returns None (circuit breaker), all results have confidence=0.0."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id = _setup_tenant(client)
        now = int(time.time())
        _seed_memory(client, tenant_id, "Fallback memory 1", _random_embedding(1))
        _seed_memory(client, tenant_id, "Fallback memory 2", _random_embedding(2))
        _seed_memory(client, tenant_id, "Fallback memory 3", _random_embedding(3))

        # Circuit breaker open -- embedding unavailable
        app.state.embedding_client.embed_single = AsyncMock(return_value=None)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "fallback confidence test"},
            headers=AUTH_HEADER,
        )

    assert resp.status_code == 200
    data = resp.json()
    results = data["results"]
    assert len(results) > 0, "Expected fallback results (recency sort)"

    for result in results:
        assert "confidence" in result, f"Missing 'confidence' field in fallback result: {result}"
        assert result["confidence"] == 0.0, (
            f"Fallback result should have confidence=0.0, got {result['confidence']}"
        )
