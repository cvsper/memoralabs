"""
Deduplication service.

Provides text-based exact dedup via SHA-256 hash and cosine similarity
dedup for post-embedding near-duplicate detection.

Port of ZimMemory text_hash + cosine dedup patterns.
"""

import hashlib
from typing import Optional

import aiosqlite
import numpy as np


def text_hash(text: str) -> str:
    """Return a 32-char hex SHA-256 digest of the normalized text.

    Normalization: strip whitespace + lowercase before hashing, so
    "Hello", "hello", and " Hello " all produce the same hash.

    Args:
        text: Raw memory text.

    Returns:
        32-character lowercase hex string.
    """
    normalized = text.strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


async def check_exact_duplicate(
    conn: aiosqlite.Connection, text: str
) -> Optional[str]:
    """Query the memories table for an existing non-deleted memory with the same text_hash.

    Args:
        conn: Open aiosqlite connection to a tenant DB.
        text: The raw memory text to check.

    Returns:
        The existing memory_id if a duplicate is found, otherwise None.
    """
    h = text_hash(text)
    async with conn.execute(
        "SELECT id FROM memories WHERE text_hash = ? AND is_deleted = 0",
        (h,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return row[0]


def check_cosine_duplicate(
    embedding: np.ndarray,
    candidate_embeddings: list[tuple[str, np.ndarray]],
    threshold: float = 0.95,
) -> Optional[str]:
    """Return the memory_id of the first candidate whose cosine similarity exceeds threshold.

    Used for post-embedding near-duplicate detection. Called after an embedding
    is computed, before persisting the new memory.

    Args:
        embedding: 1-D numpy array for the new memory.
        candidate_embeddings: List of (memory_id, embedding) tuples to compare against.
        threshold: Cosine similarity cutoff (0.0–1.0). Default 0.95.

    Returns:
        The memory_id of the first match, or None if no match found.
    """
    if embedding.ndim != 1:
        embedding = embedding.flatten()
    norm_new = np.linalg.norm(embedding)
    if norm_new == 0:
        return None

    for memory_id, candidate in candidate_embeddings:
        if candidate.ndim != 1:
            candidate = candidate.flatten()
        norm_cand = np.linalg.norm(candidate)
        if norm_cand == 0:
            continue
        similarity = float(np.dot(embedding, candidate) / (norm_new * norm_cand))
        if similarity >= threshold:
            return memory_id
    return None
