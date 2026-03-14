"""Tests for app/services/dedup.py."""
import uuid
import aiosqlite
import numpy as np
import pytest
import pytest_asyncio
from app.db.tenant import init_tenant_db
from app.services.dedup import check_cosine_duplicate, check_exact_duplicate, text_hash

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest_asyncio.fixture
async def tenant_conn():
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = aiosqlite.Row
    await init_tenant_db(conn)
    yield conn
    await conn.close()

def test_text_hash_deterministic():
    assert text_hash("Hello World") == text_hash("Hello World")

def test_text_hash_case_insensitive():
    assert text_hash("Hello") == text_hash("hello")

def test_text_hash_whitespace_normalized():
    assert text_hash(" hello ") == text_hash("hello")

def test_text_hash_different_texts():
    assert text_hash("foo") != text_hash("bar")

def test_text_hash_length():
    h = text_hash("some text")
    assert len(h) == 32
    assert all(c in "0123456789abcdef" for c in h)

def test_text_hash_combined_normalization():
    assert text_hash("Hello World") == text_hash("hello world")
    assert text_hash("Hello World") == text_hash(" hello world ")

@pytest.mark.anyio
async def test_check_exact_duplicate_found(tenant_conn):
    memory_id = str(uuid.uuid4())
    h = text_hash("my test memory")
    await tenant_conn.execute(
        "INSERT INTO memories (id, text, text_hash, created_at) VALUES (?, ?, ?, ?)",
        (memory_id, "my test memory", h, 1700000000),
    )
    await tenant_conn.commit()
    result = await check_exact_duplicate(tenant_conn, "my test memory")
    assert result == memory_id

@pytest.mark.anyio
async def test_check_exact_duplicate_not_found(tenant_conn):
    result = await check_exact_duplicate(tenant_conn, "this text does not exist")
    assert result is None

@pytest.mark.anyio
async def test_check_exact_duplicate_ignores_deleted(tenant_conn):
    memory_id = str(uuid.uuid4())
    h = text_hash("deleted memory")
    await tenant_conn.execute(
        "INSERT INTO memories (id, text, text_hash, created_at, is_deleted) VALUES (?, ?, ?, ?, ?)",
        (memory_id, "deleted memory", h, 1700000000, 1),
    )
    await tenant_conn.commit()
    result = await check_exact_duplicate(tenant_conn, "deleted memory")
    assert result is None

def test_cosine_duplicate_above_threshold():
    vec = np.array([1.0, 0.0, 0.0])
    candidates = [("mem-abc", np.array([1.0, 0.0, 0.0]))]
    result = check_cosine_duplicate(vec, candidates, threshold=0.95)
    assert result == "mem-abc"

def test_cosine_duplicate_below_threshold():
    vec = np.array([1.0, 0.0, 0.0])
    candidates = [("mem-xyz", np.array([0.0, 1.0, 0.0]))]
    result = check_cosine_duplicate(vec, candidates, threshold=0.95)
    assert result is None

def test_cosine_duplicate_uses_threshold():
    a = np.array([1.0, 0.0])
    b = np.array([0.9, 0.436])
    candidates = [("mem-near", b)]
    assert check_cosine_duplicate(a, candidates, threshold=0.85) == "mem-near"
    assert check_cosine_duplicate(a, candidates, threshold=0.99) is None

def test_cosine_duplicate_returns_first_match():
    vec = np.array([1.0, 0.0])
    candidates = [("first-match", np.array([1.0, 0.0])), ("second-match", np.array([1.0, 0.0]))]
    result = check_cosine_duplicate(vec, candidates, threshold=0.95)
    assert result == "first-match"

def test_cosine_duplicate_empty_candidates():
    vec = np.array([1.0, 0.0, 0.0])
    result = check_cosine_duplicate(vec, [])
    assert result is None
