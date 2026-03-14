"""
Tests for TenantIndexManager.

All tests use tmp_path for isolated index directories.
No disk state is shared between tests.
"""

import asyncio
import uuid
from pathlib import Path

import numpy as np
import pytest

from app.services.vector_index import TenantIndexManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DIM = 64  # smaller dimension for faster tests


def _rand_vec(seed: int | None = None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(DIM).astype(np.float32)
    return v / np.linalg.norm(v)  # unit vector for consistent cosine scores


def _make_manager(tmp_path: Path, max_cached: int = 20) -> TenantIndexManager:
    return TenantIndexManager(
        data_dir=tmp_path / "indexes", dim=DIM, max_cached=max_cached
    )


def _tid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_new_index(tmp_path):
    """get_index for an unseen tenant creates a new empty index."""
    mgr = _make_manager(tmp_path)
    tid = _tid()
    index, id_map = await mgr.get_index(tid)
    assert index is not None
    assert id_map == []
    assert index.get_current_count() == 0


@pytest.mark.asyncio
async def test_add_and_search(tmp_path):
    """add_vector then search with same vector returns that memory_id with high score."""
    mgr = _make_manager(tmp_path)
    tid = _tid()
    mem_id = str(uuid.uuid4())
    vec = _rand_vec(1)

    await mgr.add_vector(tid, mem_id, vec)
    results = await mgr.search(tid, vec, k=1)

    assert len(results) == 1
    assert results[0][0] == mem_id
    assert results[0][1] > 0.99  # near-identical vector should score ~1.0


@pytest.mark.asyncio
async def test_add_multiple_search_top_k(tmp_path):
    """search returns at most k results, closest first."""
    mgr = _make_manager(tmp_path)
    tid = _tid()

    ids = [str(uuid.uuid4()) for _ in range(5)]
    vecs = [_rand_vec(i) for i in range(5)]
    for mem_id, vec in zip(ids, vecs):
        await mgr.add_vector(tid, mem_id, vec)

    results = await mgr.search(tid, vecs[0], k=3)

    assert len(results) == 3
    # First result should be the exact match
    assert results[0][0] == ids[0]
    assert results[0][1] > 0.99
    # Results sorted by score descending
    scores = [r[1] for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_empty_index(tmp_path):
    """search on an index with no vectors returns empty list."""
    mgr = _make_manager(tmp_path)
    tid = _tid()
    results = await mgr.search(tid, _rand_vec(0), k=5)
    assert results == []


@pytest.mark.asyncio
async def test_search_with_candidate_filter(tmp_path):
    """search with candidate_ids only returns memories in that set."""
    mgr = _make_manager(tmp_path)
    tid = _tid()

    ids = [str(uuid.uuid4()) for _ in range(5)]
    vecs = [_rand_vec(i) for i in range(5)]
    for mem_id, vec in zip(ids, vecs):
        await mgr.add_vector(tid, mem_id, vec)

    allowed = {ids[1], ids[3]}
    results = await mgr.search(tid, vecs[1], k=5, candidate_ids=allowed)

    returned_ids = {r[0] for r in results}
    assert returned_ids.issubset(allowed)
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_remove_vector(tmp_path):
    """After remove_vector, the memory_id is no longer returned by search."""
    mgr = _make_manager(tmp_path)
    tid = _tid()
    mem_id = str(uuid.uuid4())
    vec = _rand_vec(7)

    await mgr.add_vector(tid, mem_id, vec)
    # Confirm it's there
    results = await mgr.search(tid, vec, k=1)
    assert any(r[0] == mem_id for r in results)

    await mgr.remove_vector(tid, mem_id)

    # After deletion search should not return the deleted id
    results_after = await mgr.search(tid, vec, k=10)
    assert not any(r[0] == mem_id for r in results_after)


@pytest.mark.asyncio
async def test_persistence(tmp_path):
    """Vector added in one manager instance is found by a second manager on same dir."""
    idx_dir = tmp_path / "indexes"
    mgr1 = TenantIndexManager(data_dir=idx_dir, dim=DIM, max_cached=20)
    tid = _tid()
    mem_id = str(uuid.uuid4())
    vec = _rand_vec(99)

    await mgr1.add_vector(tid, mem_id, vec)
    await mgr1.close()

    # New manager — cold start, must load from disk
    mgr2 = TenantIndexManager(data_dir=idx_dir, dim=DIM, max_cached=20)
    results = await mgr2.search(tid, vec, k=1)

    assert len(results) == 1
    assert results[0][0] == mem_id
    assert results[0][1] > 0.99


@pytest.mark.asyncio
async def test_lru_eviction(tmp_path):
    """With max_cached=2, the first tenant is evicted when a third is accessed."""
    mgr = _make_manager(tmp_path, max_cached=2)

    tids = [_tid() for _ in range(3)]
    vecs = [_rand_vec(i) for i in range(3)]
    ids = [str(uuid.uuid4()) for _ in range(3)]

    # Access tenants 0, 1, 2 — tenant 0 should be evicted when tenant 2 is loaded
    for tid, vec, mem_id in zip(tids, vecs, ids):
        await mgr.add_vector(tid, mem_id, vec)

    # Cache should have exactly max_cached=2 entries
    assert len(mgr._indexes) == 2
    # Tenant 0 should have been evicted (it was LRU)
    assert tids[0] not in mgr._indexes
    # Tenants 1 and 2 should be in cache
    assert tids[1] in mgr._indexes
    assert tids[2] in mgr._indexes


@pytest.mark.asyncio
async def test_resize_on_capacity(tmp_path):
    """Index grows without error when approaching capacity."""
    mgr = TenantIndexManager(
        data_dir=tmp_path / "indexes", dim=DIM, max_cached=20
    )
    # Override initial max_elements to a small value to test resize
    mgr.INITIAL_MAX_ELEMENTS = 100

    tid = _tid()
    n = 85  # > 80% of 100 = triggers resize on last batch

    for i in range(n):
        mem_id = str(uuid.uuid4())
        vec = _rand_vec(i)
        await mgr.add_vector(tid, mem_id, vec)

    index, id_map = await mgr.get_index(tid)
    assert index.get_current_count() == n
    assert len(id_map) == n
    # Max elements should have grown
    assert index.get_max_elements() > 100


@pytest.mark.asyncio
async def test_concurrent_add(tmp_path):
    """Concurrent add_vector calls (via asyncio.gather) all succeed without corruption."""
    mgr = _make_manager(tmp_path)
    tid = _tid()
    n = 10
    mem_ids = [str(uuid.uuid4()) for _ in range(n)]
    vecs = [_rand_vec(i + 100) for i in range(n)]

    await asyncio.gather(
        *[mgr.add_vector(tid, mid, v) for mid, v in zip(mem_ids, vecs)]
    )

    index, id_map = await mgr.get_index(tid)
    assert index.get_current_count() == n
    assert len(id_map) == n
    # Every memory_id should be searchable
    for mem_id, vec in zip(mem_ids, vecs):
        results = await mgr.search(tid, vec, k=1)
        assert results[0][0] == mem_id
