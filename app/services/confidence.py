"""
Confidence scoring service.

Computes a 0.0-1.0 confidence estimate for search results based on four
signals: similarity normalization, entity overlap, engagement, and freshness.
Distinct from the relevance `score` (cosine + decay) — confidence measures
how trustworthy a result is, not how well it matches the query.

Port of ZimMemory confidence pattern, adapted for MemoraLabs multi-tenant.
"""

import math

from app.services.decay import decay_factor
from app.services.entity_extraction import extract_entities, normalize_entity_name


def compute_confidence(
    raw_cosine: float,
    max_cosine_in_set: float,
    query_entities: list[dict],
    memory_text: str,
    access_count: int,
    created_at: int,
) -> float:
    """Compute confidence score for a search result.

    Components (weighted sum, each normalized to 0.0-1.0):
      - similarity_norm (40%): raw_cosine / max_cosine_in_set
      - entity_overlap (30%): fraction of query entities found in memory text
      - engagement (20%): log(1 + access_count) / log(101), capped at 1.0
      - freshness (10%): decay_factor(created_at) from decay.py

    Args:
        raw_cosine: Raw cosine similarity for this result.
        max_cosine_in_set: Highest cosine similarity in the result set.
        query_entities: Entities extracted from the query (from extract_entities()).
        memory_text: The memory's text content (for entity overlap check).
        access_count: Number of times this memory has been accessed.
        created_at: Unix timestamp when the memory was created.

    Returns:
        Float in [0.0, 1.0], rounded to 4 decimal places.
    """
    # Component 1: Similarity normalization (40%)
    sim_norm = (raw_cosine / max_cosine_in_set) if max_cosine_in_set > 0 else 0.0

    # Component 2: Entity overlap (30%)
    if query_entities:
        memory_entities = extract_entities(memory_text)
        memory_entity_keys = {
            normalize_entity_name(e["name"]) for e in memory_entities
        }
        query_entity_keys = {
            normalize_entity_name(e["name"]) for e in query_entities
        }
        overlap = len(query_entity_keys & memory_entity_keys)
        entity_overlap_ratio = overlap / len(query_entity_keys)
    else:
        entity_overlap_ratio = 0.0

    # Component 3: Engagement (20%)
    engagement = min(1.0, math.log(1 + access_count) / math.log(101))

    # Component 4: Freshness (10%)
    freshness = decay_factor(created_at)

    confidence = (
        0.40 * sim_norm
        + 0.30 * entity_overlap_ratio
        + 0.20 * engagement
        + 0.10 * freshness
    )
    return round(max(0.0, min(1.0, confidence)), 4)
