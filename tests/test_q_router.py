"""
Tests for the Q-learning bandit router (app/services/q_router.py).

Covers:
- compute_reward produces correct values for full, zero, and partial results
- update_q_value applies the Q-update formula correctly on first visit
- update_q_value converges toward a stable reward over many updates
- update_q_value reports activated=False below threshold, True at/above
- select_strategy returns "default" when Q-table is below activation threshold
- select_strategy exploits the highest-Q strategy above threshold
- get_router_stats returns correct data for empty and populated Q-table
- GET /v1/intelligence/router/stats returns RouterStats JSON with auth
- POST /v1/memory/search calls select_strategy and passes result to update_q_value

All async tests use pytest-asyncio with the aiosqlite-direct fixture pattern.
The endpoint tests use Starlette TestClient per project decision 02-01.
"""

import hashlib
import json
import time
import uuid
from unittest.mock import AsyncMock, patch

import aiosqlite
import numpy as np
import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app.db.tenant import init_tenant_db
from app.main import app
from app.services.q_router import (
    ACTIVATION_THRESHOLD,
    DEFAULT_Q,
    compute_reward,
    get_router_stats,
    select_strategy,
    update_q_value,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant_conn(tmp_path):
    """Open a fresh aiosqlite tenant DB with schema applied (includes q-table)."""
    db_path = tmp_path / "test_q_router.db"
    conn = await aiosqlite.connect(str(db_path))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await init_tenant_db(conn)
    yield conn
    await conn.close()


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


def _setup_tenant(client) -> tuple[str, str]:
    """Create a tenant + API key. Returns (tenant_id, api_key)."""
    from app.db.system import create_api_key, create_tenant

    system_db = app.state.system_db
    tenant_id = str(uuid.uuid4())
    api_key = f"test-qrouter-key-{tenant_id[:8]}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    async def _setup():
        await create_tenant(
            system_db, tenant_id, "Q-Router Test", f"qr-{tenant_id[:8]}@example.com"
        )
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix="test",
            name="test-qrouter-key",
        )
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id, api_key


def _seed_memory(client, tenant_id: str, text: str, embedding: np.ndarray) -> str:
    """Insert a memory with embedding into the tenant DB and vector index."""
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
# Unit tests — compute_reward
# ──────────────────────────────────────────────────────────────────────────────


def test_compute_reward_full_results():
    """10 results with avg_score 0.8 -> reward = 0.4 * 1.0 + 0.6 * 0.8 = 0.88."""
    reward = compute_reward(result_count=10, avg_score=0.8, max_possible=10)
    assert reward == pytest.approx(0.88)


def test_compute_reward_no_results():
    """0 results with avg_score 0.0 -> reward = 0.0."""
    reward = compute_reward(result_count=0, avg_score=0.0, max_possible=10)
    assert reward == pytest.approx(0.0)


def test_compute_reward_partial():
    """3 results out of 10, avg_score 0.5 -> reward = 0.4 * 0.3 + 0.6 * 0.5 = 0.42."""
    reward = compute_reward(result_count=3, avg_score=0.5, max_possible=10)
    assert reward == pytest.approx(0.42)


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — update_q_value
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_q_value_first_visit(tenant_conn):
    """New entry starts at DEFAULT_Q (0.5), reward=0.8 -> new_q = 0.5 + 0.2*(0.8-0.5) = 0.56."""
    result = await update_q_value(tenant_conn, "precision", "top_k_high", 0.8)

    assert result["strategy"] == "precision"
    assert result["config_key"] == "top_k_high"
    assert result["old_q"] == pytest.approx(DEFAULT_Q)
    assert result["new_q"] == pytest.approx(0.56, abs=1e-4)
    assert result["visits"] == 1
    assert result["activated"] is False  # 1 < ACTIVATION_THRESHOLD (30)


@pytest.mark.asyncio
async def test_update_q_value_converges(tenant_conn):
    """After 50 updates with reward=0.9, Q-value should approach 0.9."""
    strategy, config_key = "temporal", "top_k_high"
    for _ in range(50):
        result = await update_q_value(tenant_conn, strategy, config_key, 0.9)

    # After many updates with constant reward=0.9, Q should be close to 0.9
    # Analytical limit: 0.5 * (1 - ALPHA)^50 + 0.9 * (1 - (1-ALPHA)^50)
    # With ALPHA=0.2 and 50 steps, deviation from 0.9 should be < 0.01
    assert result["new_q"] == pytest.approx(0.9, abs=0.01)
    assert result["visits"] == 50


@pytest.mark.asyncio
async def test_update_q_value_returns_activated_flag(tenant_conn):
    """activated=False for visits < 30, activated=True for visits >= 30."""
    strategy, config_key = "relational", "min_score_strict"

    # Insert 29 updates — should not be activated yet
    for i in range(29):
        result = await update_q_value(tenant_conn, strategy, config_key, 0.7)

    assert result["visits"] == 29
    assert result["activated"] is False

    # 30th update — should now be activated
    result = await update_q_value(tenant_conn, strategy, config_key, 0.7)
    assert result["visits"] == ACTIVATION_THRESHOLD
    assert result["activated"] is True


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — select_strategy
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_select_strategy_returns_default_below_threshold(tenant_conn):
    """With < 30 visits per pair, select_strategy returns 'default'."""
    # Insert a few rows with low visit counts
    for strategy in ["precision", "temporal"]:
        await tenant_conn.execute(
            """
            INSERT INTO retrieval_q_table (strategy, config_key, q_value, visit_count, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            (strategy, "top_k_high", 0.7, 15, int(time.time())),
        )
    await tenant_conn.commit()

    result = await select_strategy(tenant_conn)
    assert result == "default", f"Expected 'default', got '{result}'"


@pytest.mark.asyncio
async def test_select_strategy_uses_q_values_above_threshold(tenant_conn):
    """With 30+ visits and distinct Q-values, best strategy selected > 85% of the time."""
    # Insert entries where "precision" has a clearly higher Q-value
    entries = [
        ("precision", "top_k_high", 0.9, 35),
        ("temporal", "top_k_high", 0.3, 35),
        ("relational", "top_k_high", 0.3, 35),
        ("broad", "top_k_high", 0.3, 35),
    ]
    for strategy, config_key, q_value, visits in entries:
        await tenant_conn.execute(
            """
            INSERT INTO retrieval_q_table (strategy, config_key, q_value, visit_count, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            (strategy, config_key, q_value, visits, int(time.time())),
        )
    await tenant_conn.commit()

    # Run 100 selections — precision should be chosen ~85%+ of the time (1 - EPSILON)
    selections = [await select_strategy(tenant_conn) for _ in range(100)]
    precision_count = selections.count("precision")

    # With EPSILON=0.15, expected ~85% exploitation. Use 75% as safe lower bound.
    assert precision_count >= 75, (
        f"Expected precision to be selected ~85% of the time, got {precision_count}/100"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — get_router_stats
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_router_stats_empty(tenant_conn):
    """Empty Q-table returns empty strategies list, is_active=False."""
    stats = await get_router_stats(tenant_conn)

    assert stats["strategies"] == []
    assert stats["total_updates"] == 0
    assert stats["is_active"] is False


@pytest.mark.asyncio
async def test_get_router_stats_with_data(tenant_conn):
    """get_router_stats reflects Q-table entries correctly."""
    entries = [
        ("precision", "top_k_high", 0.75, 35),
        ("temporal", "top_k_high", 0.55, 10),
    ]
    for strategy, config_key, q_value, visits in entries:
        await tenant_conn.execute(
            """
            INSERT INTO retrieval_q_table (strategy, config_key, q_value, visit_count, last_updated)
            VALUES (?, ?, ?, ?, ?)
            """,
            (strategy, config_key, q_value, visits, int(time.time())),
        )
    await tenant_conn.commit()

    stats = await get_router_stats(tenant_conn)

    assert len(stats["strategies"]) == 2
    assert stats["total_updates"] == 45  # 35 + 10
    assert stats["is_active"] is True  # precision has 35 >= 30

    # Verify precision entry is activated, temporal is not
    strat_map = {e["strategy"]: e for e in stats["strategies"]}
    assert strat_map["precision"]["activated"] is True
    assert strat_map["temporal"]["activated"] is False
    assert strat_map["precision"]["q_value"] == pytest.approx(0.75)
    assert strat_map["temporal"]["visit_count"] == 10


# ──────────────────────────────────────────────────────────────────────────────
# Integration test — router stats endpoint
# ──────────────────────────────────────────────────────────────────────────────


def test_router_stats_endpoint(tmp_path, monkeypatch):
    """GET /v1/intelligence/router/stats returns 200 with RouterStats shape."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id, api_key = _setup_tenant(client)

        resp = client.get(
            "/v1/intelligence/router/stats",
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert "strategies" in body
    assert "total_updates" in body
    assert "is_active" in body
    assert "activation_threshold" in body
    assert body["activation_threshold"] == 30
    assert isinstance(body["strategies"], list)
    assert body["is_active"] is False  # no updates yet


def test_router_stats_endpoint_requires_auth(tmp_path, monkeypatch):
    """GET /v1/intelligence/router/stats without auth returns 401."""
    with _make_client(tmp_path, monkeypatch) as client:
        resp = client.get("/v1/intelligence/router/stats")

    assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# Integration test — search pipeline calls select_strategy
# ──────────────────────────────────────────────────────────────────────────────


def test_search_calls_select_strategy(tmp_path, monkeypatch):
    """POST /v1/memory/search calls select_strategy and passes its result to update_q_value."""
    rng = np.random.RandomState(99)
    base_emb = rng.randn(1024).astype(np.float32)
    base_emb = base_emb / np.linalg.norm(base_emb)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id, api_key = _setup_tenant(client)
        _seed_memory(client, tenant_id, "Memory about Q-router feedback loop", base_emb)

        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        captured_calls = []

        # Wrap update_q_value to capture its arguments
        original_update = None

        async def _capturing_update(conn, strategy, config_key, reward):
            captured_calls.append({
                "strategy": strategy,
                "config_key": config_key,
                "reward": reward,
            })
            from app.services import q_router as _qr
            return await _qr.__wrapped_update_q_value(conn, strategy, config_key, reward)

        # Use patch to intercept the call in the search pipeline
        with patch("app.services.search.update_q_value") as mock_update, \
             patch("app.services.search.select_strategy") as mock_select:

            mock_select.return_value = "precision"
            mock_update.return_value = {
                "strategy": "precision", "config_key": "top_k_high",
                "old_q": 0.5, "new_q": 0.56, "visits": 1, "activated": False
            }

            resp = client.post(
                "/v1/memory/search",
                json={"query": "Q-router feedback loop test"},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            assert resp.status_code == 200

            # Verify select_strategy was called
            assert mock_select.called, "select_strategy was not called during search"

            # Verify update_q_value was called with the strategy returned by select_strategy
            assert mock_update.called, "update_q_value was not called during search"
            call_args = mock_update.call_args
            # The strategy argument (2nd positional) must equal what select_strategy returned
            # call_args: (conn, strategy, config_key, reward)
            called_strategy = call_args[0][1]  # positional arg index 1
            assert called_strategy == "precision", (
                f"update_q_value called with strategy='{called_strategy}', "
                f"expected 'precision' (what select_strategy returned)"
            )
