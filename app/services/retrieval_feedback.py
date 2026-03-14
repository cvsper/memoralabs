"""
Retrieval feedback logging service.

Records every search operation into the per-tenant `retrieval_log` table.
This data is the training signal for the Q-learning router (plan 05-02) and
knowledge gap detector (plan 05-03).

Pattern: fire-and-forget INSERT — intentionally lightweight so it never adds
latency to the search hot path. Wrapped in try/except at call sites.

Port of ZimMemory consciousness heartbeat logging pattern, adapted for
per-tenant SQLite isolation.
"""

import json
import time
import uuid
from typing import Optional

import aiosqlite

from app.services.dedup import text_hash


async def log_retrieval(
    conn: aiosqlite.Connection,
    query: str,
    result_ids: list,
    scores: list,
    strategy: str = "default",
    hit: Optional[int] = None,
) -> str:
    """Insert a retrieval feedback row into the tenant's retrieval_log table.

    Computes a query hash via text_hash() (reuses the SHA-256 normalization
    from the dedup service) so rows for semantically identical queries can be
    grouped without storing raw query text in indexes.

    Args:
        conn: Open aiosqlite.Connection to a tenant DB.
        query: The raw natural language query string.
        result_ids: List of memory IDs returned by the search.
        scores: List of final scores (float) corresponding to result_ids.
        strategy: Retrieval strategy label (e.g., "default", "vector", "fallback").
        hit: Optional explicit relevance signal — 1 for positive, 0 for negative,
             None if unknown (most calls). Used by Q-learning reward computation.

    Returns:
        The log_id (UUID string) of the newly inserted row.
    """
    log_id = str(uuid.uuid4())
    q_hash = text_hash(query)
    now = int(time.time())

    await conn.execute(
        """
        INSERT INTO retrieval_log
            (id, query, query_hash, result_ids, scores, strategy, hit, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            log_id,
            query,
            q_hash,
            json.dumps(result_ids),
            json.dumps(scores),
            strategy,
            hit,
            now,
        ),
    )
    await conn.commit()
    return log_id


async def get_feedback_stats(
    conn: aiosqlite.Connection,
    days: int = 30,
) -> dict:
    """Return diagnostic statistics from the retrieval_log for the last N days.

    Intended for monitoring and debugging — not on the search hot path.

    Args:
        conn: Open aiosqlite.Connection to a tenant DB.
        days: How far back to look (default 30). Rows older than this are excluded.

    Returns:
        Dict with keys:
          - total_queries (int): Number of retrieval log rows in the window.
          - avg_result_count (float): Average number of results returned per query.
          - hit_rate (float | None): Fraction of rows with hit=1 among rows that
            have an explicit hit signal. None if no rows have a hit value set.
          - strategies (dict): Mapping of strategy label -> count.
    """
    since = int(time.time()) - (days * 86_400)

    # Aggregate counts
    total_queries = 0
    total_result_count = 0
    hit_count = 0
    explicit_hit_rows = 0
    strategies: dict[str, int] = {}

    async with conn.execute(
        "SELECT result_ids, strategy, hit FROM retrieval_log WHERE created_at >= ?",
        (since,),
    ) as cur:
        async for row in cur:
            total_queries += 1

            try:
                ids = json.loads(row["result_ids"]) if row["result_ids"] else []
            except (json.JSONDecodeError, TypeError):
                ids = []
            total_result_count += len(ids)

            strat = row["strategy"] or "default"
            strategies[strat] = strategies.get(strat, 0) + 1

            if row["hit"] is not None:
                explicit_hit_rows += 1
                if row["hit"] == 1:
                    hit_count += 1

    avg_result_count = total_result_count / total_queries if total_queries > 0 else 0.0
    hit_rate = hit_count / explicit_hit_rows if explicit_hit_rows > 0 else None

    return {
        "total_queries": total_queries,
        "avg_result_count": avg_result_count,
        "hit_rate": hit_rate,
        "strategies": strategies,
    }
