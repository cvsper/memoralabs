"""
TenantIndexManager — Per-tenant hnswlib vector index manager with LRU cache.

Responsibilities:
- Lazy-load or create per-tenant hnswlib indexes from disk
- Cache up to max_cached indexes in memory (LRU eviction)
- Persist indexes to disk on eviction and shutdown
- Add vectors, search with optional candidate ID filtering, mark deleted
- Guard all mutations with an asyncio.Lock (hnswlib is NOT thread-safe)

Index files live at: {data_dir}/{tenant_id}.idx
ID map files live at: {data_dir}/{tenant_id}.ids.json
"""

import asyncio
import json
from collections import OrderedDict
from pathlib import Path

import hnswlib
import numpy as np


class TenantIndexManager:
    """Per-tenant hnswlib index cache with LRU eviction and disk persistence."""

    INITIAL_MAX_ELEMENTS = 10_000
    GROWTH_FACTOR = 2
    RESIZE_THRESHOLD = 0.8  # Resize when 80% full

    def __init__(
        self, data_dir: Path, dim: int = 1024, max_cached: int = 20
    ) -> None:
        self.data_dir = data_dir
        self.dim = dim
        self.max_cached = max_cached

        # LRU cache: tenant_id -> hnswlib.Index
        self._indexes: OrderedDict[str, hnswlib.Index] = OrderedDict()
        # Position map: tenant_id -> list[memory_uuid] (index = position in hnswlib)
        self._id_maps: dict[str, list[str]] = {}
        self._lock = asyncio.Lock()

        # Ensure index directory exists
        data_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _index_path(self, tenant_id: str) -> Path:
        return self.data_dir / f"{tenant_id}.idx"

    def _id_map_path(self, tenant_id: str) -> Path:
        return self.data_dir / f"{tenant_id}.ids.json"

    # ------------------------------------------------------------------
    # Private disk I/O
    # ------------------------------------------------------------------

    def _save_index(
        self, tenant_id: str, index: hnswlib.Index, id_map: list[str]
    ) -> None:
        """Save index file and id_map JSON to disk (synchronous C++ I/O)."""
        index.save_index(str(self._index_path(tenant_id)))
        self._id_map_path(tenant_id).write_text(
            json.dumps(id_map), encoding="utf-8"
        )

    def _load_or_create(
        self, tenant_id: str
    ) -> tuple[hnswlib.Index, list[str]]:
        """Load existing index from disk or create a new empty one."""
        idx_path = self._index_path(tenant_id)
        id_map_path = self._id_map_path(tenant_id)

        index = hnswlib.Index(space="cosine", dim=self.dim)

        if idx_path.exists():
            # Load existing index; allow_replace_deleted=True for mark_deleted support
            index.load_index(str(idx_path), max_elements=0)
            id_map: list[str] = json.loads(id_map_path.read_text(encoding="utf-8"))
        else:
            # Create new index
            index.init_index(
                max_elements=self.INITIAL_MAX_ELEMENTS,
                ef_construction=200,
                M=16,
            )
            index.set_ef(200)
            id_map = []

        return index, id_map

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_index(
        self, tenant_id: str
    ) -> tuple[hnswlib.Index, list[str]]:
        """Return (index, id_map) for tenant, loading from disk if needed.

        LRU semantics: cache hit moves to most-recently-used position.
        Evicts least-recently-used tenant (after saving) when at capacity.
        """
        async with self._lock:
            if tenant_id in self._indexes:
                self._indexes.move_to_end(tenant_id)
                return self._indexes[tenant_id], self._id_maps[tenant_id]

            # Evict LRU if at capacity
            if len(self._indexes) >= self.max_cached:
                evicted_id, evicted_idx = self._indexes.popitem(last=False)
                evicted_map = self._id_maps.pop(evicted_id)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, self._save_index, evicted_id, evicted_idx, evicted_map
                )

            # Load or create
            loop = asyncio.get_event_loop()
            index, id_map = await loop.run_in_executor(
                None, self._load_or_create, tenant_id
            )
            self._indexes[tenant_id] = index
            self._id_maps[tenant_id] = id_map
            return index, id_map

    async def add_vector(
        self, tenant_id: str, memory_id: str, embedding: np.ndarray
    ) -> None:
        """Add an embedding vector with its memory UUID to the tenant index.

        Resizes the hnswlib index if approaching capacity before adding.
        """
        async with self._lock:
            # Use get_index internals without re-acquiring lock
            if tenant_id in self._indexes:
                self._indexes.move_to_end(tenant_id)
                index = self._indexes[tenant_id]
                id_map = self._id_maps[tenant_id]
            else:
                # Evict LRU if at capacity
                if len(self._indexes) >= self.max_cached:
                    evicted_id, evicted_idx = self._indexes.popitem(last=False)
                    evicted_map = self._id_maps.pop(evicted_id)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, self._save_index, evicted_id, evicted_idx, evicted_map
                    )
                loop = asyncio.get_event_loop()
                index, id_map = await loop.run_in_executor(
                    None, self._load_or_create, tenant_id
                )
                self._indexes[tenant_id] = index
                self._id_maps[tenant_id] = id_map

            # Resize if approaching capacity
            current_count = index.get_current_count()
            max_elements = index.get_max_elements()
            if current_count >= max_elements * self.RESIZE_THRESHOLD:
                new_max = max_elements * self.GROWTH_FACTOR
                index.resize_index(new_max)

            # Add vector at next position
            position = len(id_map)
            id_map.append(memory_id)
            index.add_items(
                embedding.reshape(1, -1), np.array([position])
            )

            # Persist to disk
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._save_index, tenant_id, index, id_map
            )

    async def search(
        self,
        tenant_id: str,
        query_embedding: np.ndarray,
        k: int = 10,
        candidate_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Search the tenant index for the k nearest neighbors.

        Args:
            tenant_id: Tenant identifier.
            query_embedding: Query vector of shape (dim,) or (1, dim).
            k: Number of results to return.
            candidate_ids: Optional set of memory UUIDs to restrict results to.

        Returns:
            List of (memory_id, similarity_score) sorted by score descending.
            similarity_score = 1.0 - cosine_distance (range 0.0 to 1.0).
        """
        async with self._lock:
            if tenant_id in self._indexes:
                self._indexes.move_to_end(tenant_id)
                index = self._indexes[tenant_id]
                id_map = self._id_maps[tenant_id]
            else:
                if len(self._indexes) >= self.max_cached:
                    evicted_id, evicted_idx = self._indexes.popitem(last=False)
                    evicted_map = self._id_maps.pop(evicted_id)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, self._save_index, evicted_id, evicted_idx, evicted_map
                    )
                loop = asyncio.get_event_loop()
                index, id_map = await loop.run_in_executor(
                    None, self._load_or_create, tenant_id
                )
                self._indexes[tenant_id] = index
                self._id_maps[tenant_id] = id_map

        current_count = index.get_current_count()
        if current_count == 0:
            return []

        # Over-fetch to allow for candidate filtering and deleted items
        fetch_k = min(k * 3, current_count)
        positions, distances = index.knn_query(
            query_embedding.reshape(1, -1), k=fetch_k
        )

        results: list[tuple[str, float]] = []
        for pos, dist in zip(positions[0], distances[0]):
            pos = int(pos)
            if pos >= len(id_map):
                continue
            mem_id = id_map[pos]
            if candidate_ids is not None and mem_id not in candidate_ids:
                continue
            similarity = 1.0 - float(dist)
            results.append((mem_id, similarity))

        # Sort by similarity descending, return top-k
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]

    async def remove_vector(self, tenant_id: str, memory_id: str) -> None:
        """Mark a vector as deleted in the tenant index.

        Note: hnswlib positions are permanent — the position is marked deleted
        but NOT removed from id_map (positions are integer IDs in hnswlib).
        """
        async with self._lock:
            if tenant_id in self._indexes:
                self._indexes.move_to_end(tenant_id)
                index = self._indexes[tenant_id]
                id_map = self._id_maps[tenant_id]
            else:
                if len(self._indexes) >= self.max_cached:
                    evicted_id, evicted_idx = self._indexes.popitem(last=False)
                    evicted_map = self._id_maps.pop(evicted_id)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, self._save_index, evicted_id, evicted_idx, evicted_map
                    )
                loop = asyncio.get_event_loop()
                index, id_map = await loop.run_in_executor(
                    None, self._load_or_create, tenant_id
                )
                self._indexes[tenant_id] = index
                self._id_maps[tenant_id] = id_map

            try:
                position = id_map.index(memory_id)
                index.mark_deleted(position)
            except ValueError:
                # memory_id not in id_map — nothing to remove
                return

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, self._save_index, tenant_id, index, id_map
            )

    async def save_all(self) -> None:
        """Save all cached indexes to disk. Called on graceful shutdown."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            for tenant_id, index in self._indexes.items():
                id_map = self._id_maps[tenant_id]
                await loop.run_in_executor(
                    None, self._save_index, tenant_id, index, id_map
                )

    async def close(self) -> None:
        """Persist all indexes and clear the cache."""
        await self.save_all()
        async with self._lock:
            self._indexes.clear()
            self._id_maps.clear()
