"""
Tests for the retrieval feedback logging service (app/services/retrieval_feedback.py).

Covers:
- log_retrieval creates a row with correct field values
- log_retrieval produces consistent query_hash for identical queries
- log_retrieval stores result_ids and scores as valid JSON arrays
- get_feedback_stats returns zero totals on empty DB
- get_feedback_stats aggregates correctly across multiple rows
- get_feedback_stats respects the days window (excludes old rows)
- POST /v1/memory/search endpoint writes a row to retrieval_log end-to-end

All async tests use pytest-asyncio with the aiosqlite-direct fixture pattern
established in test_tenant_db.py. The endpoint test uses Starlette TestClient
following the pattern in test_memory_search.py.
"""

import hashlib
import json
import time
import uuid
from unittest.mock import AsyncMock

import aiosqlite
import numpy as np
import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app.db.tenant import init_tenant_db
from app.main import app
from app.services.dedup import text_hash
from app.services.retrieval_feedback import get_feedback_stats, log_retrieval


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant_conn(tmp_path):
    """Open a fresh aiosqlite in-memory-equivalent tenant DB with schema applied."""
    db_path = tmp_path / "test_feedback.db"
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
    api_key = f"test-feedback-key-{tenant_id[:8]}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    async def _setup():
        await create_tenant(
            system_db, tenant_id, "Feedback Test", f"fb-{tenant_id[:8]}@example.com"
        )
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix="test",
            name="test-feedback-key",
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
# Unit tests — log_retrieval
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_retrieval_creates_row(tenant_conn):
    """log_retrieval inserts a row with the correct field values."""
    query = "What did Alice say about the project?"
    result_ids = ["mem-001", "mem-002", "mem-003"]
    scores = [0.95, 0.82, 0.71]

    log_id = await log_retrieval(tenant_conn, query, result_ids, scores)

    assert isinstance(log_id, str)
    assert len(log_id) == 36  # UUID4 format

    async with tenant_conn.execute(
        "SELECT * FROM retrieval_log WHERE id = ?", (log_id,)
    ) as cur:
        row = await cur.fetchone()

    assert row is not None, "No row found in retrieval_log after log_retrieval call"
    assert row["query"] == query
    assert row["strategy"] == "default"
    assert row["hit"] is None
    assert row["created_at"] > 0


@pytest.mark.asyncio
async def test_log_retrieval_hashes_query(tenant_conn):
    """Two calls with the same query produce rows with identical query_hash."""
    query = "duplicate query text"
    expected_hash = text_hash(query)

    id1 = await log_retrieval(tenant_conn, query, ["a"], [0.9])
    id2 = await log_retrieval(tenant_conn, query, ["b"], [0.8])

    async with tenant_conn.execute(
        "SELECT query_hash FROM retrieval_log WHERE id IN (?, ?)", (id1, id2)
    ) as cur:
        rows = await cur.fetchall()

    assert len(rows) == 2
    hashes = {row["query_hash"] for row in rows}
    assert len(hashes) == 1, f"Expected same hash for same query, got: {hashes}"
    assert hashes.pop() == expected_hash


@pytest.mark.asyncio
async def test_log_retrieval_stores_json_arrays(tenant_conn):
    """result_ids and scores columns store valid JSON arrays readable as Python lists."""
    result_ids = ["id-alpha", "id-beta"]
    scores = [0.88, 0.64]

    log_id = await log_retrieval(tenant_conn, "json array test", result_ids, scores)

    async with tenant_conn.execute(
        "SELECT result_ids, scores FROM retrieval_log WHERE id = ?", (log_id,)
    ) as cur:
        row = await cur.fetchone()

    assert row is not None
    stored_ids = json.loads(row["result_ids"])
    stored_scores = json.loads(row["scores"])

    assert isinstance(stored_ids, list), "result_ids must deserialize to a list"
    assert isinstance(stored_scores, list), "scores must deserialize to a list"
    assert stored_ids == result_ids
    assert stored_scores == scores


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — get_feedback_stats
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_feedback_stats_empty(tenant_conn):
    """get_feedback_stats on an empty retrieval_log returns zeroed stats."""
    stats = await get_feedback_stats(tenant_conn)

    assert stats["total_queries"] == 0
    assert stats["avg_result_count"] == 0.0
    assert stats["hit_rate"] is None
    assert stats["strategies"] == {}


@pytest.mark.asyncio
async def test_get_feedback_stats_with_data(tenant_conn):
    """get_feedback_stats aggregates correctly after inserting 5 rows."""
    now = int(time.time())

    # Insert 5 rows with varying strategies and result counts
    rows_to_insert = [
        ("query-a", ["id1", "id2"], [0.9, 0.8], "default"),
        ("query-b", ["id3"], [0.7], "vector"),
        ("query-c", ["id4", "id5", "id6"], [0.6, 0.5, 0.4], "default"),
        ("query-d", [], [], "fallback"),
        ("query-e", ["id7", "id8"], [0.95, 0.85], "vector"),
    ]

    for query, result_ids, scores, strategy in rows_to_insert:
        await tenant_conn.execute(
            """
            INSERT INTO retrieval_log
                (id, query, query_hash, result_ids, scores, strategy, hit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                query,
                text_hash(query),
                json.dumps(result_ids),
                json.dumps(scores),
                strategy,
                None,
                now,
            ),
        )
    await tenant_conn.commit()

    stats = await get_feedback_stats(tenant_conn)

    assert stats["total_queries"] == 5
    # total results: 2 + 1 + 3 + 0 + 2 = 8; avg = 8/5 = 1.6
    assert stats["avg_result_count"] == pytest.approx(1.6)
    assert stats["hit_rate"] is None  # no explicit hit signals
    assert "default" in stats["strategies"]
    assert stats["strategies"]["default"] == 2
    assert stats["strategies"]["vector"] == 2
    assert stats["strategies"]["fallback"] == 1


@pytest.mark.asyncio
async def test_get_feedback_stats_respects_days_window(tenant_conn):
    """Rows older than the days window are excluded from stats."""
    now = int(time.time())
    old_time = now - (35 * 86_400)  # 35 days ago — outside 30-day window

    # Insert one current row and one old row
    for ts, query in [(now, "recent query"), (old_time, "old query")]:
        await tenant_conn.execute(
            """
            INSERT INTO retrieval_log
                (id, query, query_hash, result_ids, scores, strategy, hit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                query,
                text_hash(query),
                json.dumps(["id-x"]),
                json.dumps([0.9]),
                "default",
                None,
                ts,
            ),
        )
    await tenant_conn.commit()

    stats = await get_feedback_stats(tenant_conn, days=30)

    assert stats["total_queries"] == 1, (
        f"Expected only 1 row in 30-day window, got {stats['total_queries']}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Integration test — search endpoint writes to retrieval_log
# ──────────────────────────────────────────────────────────────────────────────


def test_search_endpoint_logs_feedback(tmp_path, monkeypatch):
    """POST /v1/memory/search creates a retrieval_log row for the tenant."""
    rng = np.random.RandomState(42)
    base_emb = rng.randn(1024).astype(np.float32)
    base_emb = base_emb / np.linalg.norm(base_emb)

    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id, api_key = _setup_tenant(client)
        _seed_memory(client, tenant_id, "Memory about testing feedback logging", base_emb)

        app.state.embedding_client.embed_single = AsyncMock(return_value=base_emb)

        resp = client.post(
            "/v1/memory/search",
            json={"query": "feedback logging test"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        async def _check_log():
            conn = await app.state.tenant_manager.get_connection(tenant_id)
            async with conn.execute(
                "SELECT id, query, strategy FROM retrieval_log ORDER BY created_at DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
            return dict(row) if row else None

        log_row = client.portal.call(_check_log)

    assert log_row is not None, "No retrieval_log row written after search"
    assert log_row["query"] == "feedback logging test"
    assert log_row["strategy"] == "default"
