"""
Knowledge gap detection service.

Scans the retrieval_log to find entity patterns that appear frequently
in user queries but are absent from stored memory entities. Surfaces
actionable intelligence: "your agents keep asking about X but you haven't
stored any memories about X."

Pitfall #5 from research: short queries (< 5 words) produce noisy entity
matches from the regex extractor and are excluded from analysis.
"""

import time
from collections import Counter

import aiosqlite

from app.services.entity_extraction import extract_entities, normalize_entity_name


async def detect_knowledge_gaps(
    conn: aiosqlite.Connection,
    days: int = 30,
    min_query_mentions: int = 3,
) -> dict:
    """Surface entity patterns absent from memory but present in queries.

    Scans the retrieval_log for the given time window, extracts entities
    from query text, and compares against the entities table. Entities
    that appear in queries >= min_query_mentions times but have no
    matching stored entity are returned as "gaps."

    Queries shorter than 5 words are skipped to avoid false positives
    from the regex entity extractor (research pitfall #5).

    Args:
        conn: Open aiosqlite connection to a tenant DB.
        days: Lookback window in days (default 30).
        min_query_mentions: Minimum query mentions to qualify as a gap.

    Returns:
        Dict with keys: gaps (list of gap dicts), total, window_days, queries_analyzed.
    """
    cutoff = int(time.time()) - (days * 86400)

    # Fetch all queries in the window
    rows = []
    async with conn.execute(
        "SELECT query FROM retrieval_log WHERE created_at > ?", (cutoff,)
    ) as cur:
        async for row in cur:
            rows.append(row["query"])

    # Extract entities from queries, skip short queries (< 5 words)
    query_entity_counts: Counter = Counter()
    queries_analyzed = 0
    for query_text in rows:
        if len(query_text.split()) < 5:
            continue
        queries_analyzed += 1
        entities = extract_entities(query_text)
        for ent in entities:
            key = (normalize_entity_name(ent["name"]), ent["type"])
            if key[0]:  # skip empty normalized names
                query_entity_counts[key] += 1

    # Check which entities exist in stored memories
    gaps = []
    for (name_norm, etype), count in query_entity_counts.most_common():
        if count < min_query_mentions:
            continue
        async with conn.execute(
            "SELECT id FROM entities WHERE name_normalized = ? AND entity_type = ?",
            (name_norm, etype),
        ) as cur:
            if await cur.fetchone() is None:
                gaps.append({
                    "entity": name_norm,
                    "type": etype,
                    "query_mentions": count,
                    "status": "missing",
                })

    return {
        "gaps": gaps,
        "total": len(gaps),
        "window_days": days,
        "queries_analyzed": queries_analyzed,
    }
