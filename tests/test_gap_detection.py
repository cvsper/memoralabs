"""
Tests for the knowledge gap detection service (app/services/gap_detection.py)
and POST /v1/memory/gaps endpoint.

Covers:
- detect_knowledge_gaps returns empty result on empty retrieval_log
- No gaps returned when entity already exists in stored memories
- Gap returned when entity appears 3+ times in queries but is absent from entities table
- min_mentions threshold respected (2 mentions does NOT qualify)
- Short queries (< 5 words) are skipped entirely
- Days window respected (old entries excluded)
- POST /v1/memory/gaps endpoint returns 200 with valid GapDetectionResponse shape
- POST /v1/memory/gaps respects custom days/min_mentions params

All async unit tests use the aiosqlite-direct fixture pattern from test_retrieval_feedback.py.
Endpoint tests use Starlette TestClient following project conventions (02-01 decision).
"""

import hashlib
import json
import time
import uuid

import aiosqlite
import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from app.db.tenant import init_tenant_db
from app.main import app
from app.services.gap_detection import detect_knowledge_gaps


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def tenant_conn(tmp_path):
    """Open a fresh aiosqlite tenant DB with full schema applied."""
    db_path = tmp_path / "test_gaps.db"
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
    api_key = f"test-gaps-key-{tenant_id[:8]}"
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    async def _setup():
        await create_tenant(
            system_db, tenant_id, "Gaps Test", f"gaps-{tenant_id[:8]}@example.com"
        )
        await create_api_key(
            system_db,
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            key_hash=key_hash,
            key_prefix="test",
            name="test-gaps-key",
        )
        await app.state.tenant_manager.create_tenant_db(tenant_id)

    client.portal.call(_setup)
    return tenant_id, api_key


def _insert_retrieval_log(conn_or_client, query: str, created_at: int | None = None):
    """Insert a single retrieval_log row. Accepts either aiosqlite.Connection or client portal."""
    now = created_at if created_at is not None else int(time.time())
    row_id = str(uuid.uuid4())
    query_hash = hashlib.sha256(query.lower().strip().encode()).hexdigest()

    async def _do_insert(conn):
        await conn.execute(
            """
            INSERT INTO retrieval_log
                (id, query, query_hash, result_ids, scores, strategy, hit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row_id, query, query_hash, json.dumps([]), json.dumps([]), "default", None, now),
        )
        await conn.commit()

    return row_id, _do_insert


# ──────────────────────────────────────────────────────────────────────────────
# Unit tests — detect_knowledge_gaps service
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_gaps_empty_log(tenant_conn):
    """No retrieval_log entries -> gaps=[], total=0, queries_analyzed=0."""
    result = await detect_knowledge_gaps(tenant_conn)

    assert result["gaps"] == []
    assert result["total"] == 0
    assert result["queries_analyzed"] == 0
    assert result["window_days"] == 30


@pytest.mark.asyncio
async def test_detect_gaps_no_gaps_when_entities_exist(tenant_conn):
    """Entity queried 3+ times but already in entities table -> no gap returned."""
    # Insert 3 queries mentioning "Alice"
    long_queries = [
        "Can you tell me what Alice said about the project last week",
        "What was the decision that Alice made about deployment timeline",
        "I need to know about the conversation where Alice discussed the budget",
    ]
    for q in long_queries:
        _, insert_fn = _insert_retrieval_log(tenant_conn, q)
        await insert_fn(tenant_conn)

    # Insert "alice" entity into entities table
    entity_id = str(uuid.uuid4())
    now = int(time.time())
    await tenant_conn.execute(
        """
        INSERT INTO entities (id, name, name_normalized, entity_type, created_at, mention_count, last_seen_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
        """,
        (entity_id, "Alice", "alice", "person", now, now),
    )
    await tenant_conn.commit()

    result = await detect_knowledge_gaps(tenant_conn, min_query_mentions=3)

    # Alice is in entities — should NOT be a gap
    gap_entities = [g["entity"] for g in result["gaps"]]
    assert "alice" not in gap_entities, f"alice should not be a gap, got: {gap_entities}"


@pytest.mark.asyncio
async def test_detect_gaps_finds_missing_entity(tenant_conn):
    """Entity queried 3+ times and absent from entities table -> gap returned.

    Uses queries mentioning "Alice" (person) — extract_entities() reliably
    extracts the capitalized proper name "Alice" from these long queries.
    The entities table is empty so "alice" is a gap.
    """
    queries = [
        "What did Alice say about the project deployment and timeline this week",
        "Can you summarize the decisions that Alice made about the release schedule",
        "Tell me about the meeting where Alice discussed the architecture changes",
        "What are the blockers that Alice identified for the upcoming sprint review",
    ]
    for q in queries:
        _, insert_fn = _insert_retrieval_log(tenant_conn, q)
        await insert_fn(tenant_conn)

    result = await detect_knowledge_gaps(tenant_conn, min_query_mentions=3)

    assert result["queries_analyzed"] == 4
    assert result["total"] >= 1, f"Expected at least 1 gap, got: {result}"

    # "alice" should appear as a gap (person entity queried 4 times, absent from entities)
    alice_gaps = [g for g in result["gaps"] if g["entity"] == "alice" and g["type"] == "person"]
    assert len(alice_gaps) >= 1, f"Expected alice/person gap, got gaps: {result['gaps']}"

    gap = alice_gaps[0]
    assert gap["query_mentions"] >= 3
    assert gap["status"] == "missing"


@pytest.mark.asyncio
async def test_detect_gaps_respects_min_mentions(tenant_conn):
    """Entity appearing only 2 times is NOT returned with default min_mentions=3."""
    # Only 2 queries mentioning the same entity
    queries = [
        "Tell me about the work that Prometheus AI is doing on language models",
        "What is the current roadmap for Prometheus AI product development",
    ]
    for q in queries:
        _, insert_fn = _insert_retrieval_log(tenant_conn, q)
        await insert_fn(tenant_conn)

    result = await detect_knowledge_gaps(tenant_conn, min_query_mentions=3)

    # 2 mentions < 3 threshold — should have no gaps
    assert result["gaps"] == [], f"Expected no gaps with 2 mentions, got: {result['gaps']}"


@pytest.mark.asyncio
async def test_detect_gaps_skips_short_queries(tenant_conn):
    """Queries with fewer than 5 words are excluded from entity extraction."""
    short_queries = [
        "Alice project",
        "what is Alice",
        "tell me Alice",
        "about Alice today",
    ]
    for q in short_queries:
        _, insert_fn = _insert_retrieval_log(tenant_conn, q)
        await insert_fn(tenant_conn)

    result = await detect_knowledge_gaps(tenant_conn)

    assert result["queries_analyzed"] == 0, (
        f"Expected 0 analyzed (all short), got {result['queries_analyzed']}"
    )
    assert result["gaps"] == []


@pytest.mark.asyncio
async def test_detect_gaps_respects_days_window(tenant_conn):
    """Entries older than the window are excluded from analysis."""
    now = int(time.time())
    old_ts = now - (35 * 86_400)  # 35 days ago — outside default 30-day window

    # Insert 5 old queries that would produce gaps if analyzed
    old_queries = [
        "Tell me about the status of ProjectY deployment in production",
        "What is the current roadmap for ProjectY feature development",
        "I need a summary of ProjectY architecture decisions made recently",
        "What are the blockers preventing ProjectY from launching soon",
        "Can you describe the ProjectY timeline for the next release",
    ]
    for q in old_queries:
        _, insert_fn = _insert_retrieval_log(tenant_conn, q, created_at=old_ts)
        await insert_fn(tenant_conn)

    result = await detect_knowledge_gaps(tenant_conn, days=30)

    assert result["queries_analyzed"] == 0, (
        f"Expected 0 analyzed (all outside 30d window), got {result['queries_analyzed']}"
    )
    assert result["gaps"] == []


# ──────────────────────────────────────────────────────────────────────────────
# Integration tests — POST /v1/memory/gaps endpoint
# ──────────────────────────────────────────────────────────────────────────────


def test_gaps_endpoint_returns_200(tmp_path, monkeypatch):
    """POST /v1/memory/gaps with valid auth returns 200 and GapDetectionResponse shape."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id, api_key = _setup_tenant(client)

        resp = client.post(
            "/v1/memory/gaps",
            json={"days": 30, "min_mentions": 3},
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "gaps" in body
    assert "total" in body
    assert "window_days" in body
    assert "queries_analyzed" in body
    assert isinstance(body["gaps"], list)
    assert body["total"] == 0  # no retrieval log entries
    assert body["window_days"] == 30


def test_gaps_endpoint_custom_params(tmp_path, monkeypatch):
    """POST /v1/memory/gaps with custom days/min_mentions uses those values."""
    with _make_client(tmp_path, monkeypatch) as client:
        tenant_id, api_key = _setup_tenant(client)

        resp = client.post(
            "/v1/memory/gaps",
            json={"days": 7, "min_mentions": 5},
            headers={"Authorization": f"Bearer {api_key}"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["window_days"] == 7, f"Expected window_days=7, got {body['window_days']}"
    assert body["queries_analyzed"] == 0
