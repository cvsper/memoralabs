"""
Search orchestrator service.

Implements the metadata-first hybrid search pattern (RETR-05, Pattern 4):
  1. Build candidate set via SQL metadata/scope filters (cheap, index-backed)
  2. Embed query text (Fireworks.ai)
  3. Vector ANN search restricted to candidate IDs (hnswlib)
  4. Apply temporal decay (recent memories rank higher)
  5. Sort by final score, return top-k

Fallback: if the embedding client is unavailable (circuit breaker open),
return candidates sorted by created_at DESC rather than an empty result.
This ensures useful responses even under Fireworks.ai outages.

MEM-03: metadata_filter supports AND (all conditions must match) or OR
(at least one condition must match).
"""

import json
import logging
from typing import Optional

import aiosqlite

from app.services.confidence import compute_confidence
from app.services.decay import apply_decay
from app.services.embedding import EmbeddingClient
from app.services.entity_extraction import extract_entities
from app.services.q_router import compute_reward, select_strategy, update_q_value
from app.services.retrieval_feedback import log_retrieval
from app.services.vector_index import TenantIndexManager

logger = logging.getLogger(__name__)


async def search_memories(
    conn: aiosqlite.Connection,
    embedding_client: EmbeddingClient,
    index_manager: TenantIndexManager,
    tenant_id: str,
    query: str,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata_filter: Optional[dict] = None,
    metadata_filter_operator: str = "and",
    limit: int = 10,
) -> list[dict]:
    """Hybrid search: metadata-first filtering + vector scoring + temporal decay.

    Args:
        conn: Open aiosqlite connection to a tenant DB.
        embedding_client: EmbeddingClient instance (circuit-breaker protected).
        index_manager: TenantIndexManager for ANN search.
        tenant_id: Tenant identifier for the vector index.
        query: Natural language query text.
        user_id: Optional scope filter.
        agent_id: Optional scope filter.
        session_id: Optional scope filter.
        metadata_filter: Optional key-value pairs to filter by. Applied before
            vector search to narrow the candidate set (RETR-05).
        metadata_filter_operator: "and" (all conditions required, default) or
            "or" (at least one condition required). MEM-03.
        limit: Maximum number of results to return (1-100).

    Returns:
        List of result dicts matching MemorySearchResult fields, sorted by
        final_score descending.
    """
    # ------------------------------------------------------------------
    # Step 1: Build SQL candidate set with metadata-first filtering
    # ------------------------------------------------------------------
    conditions: list[str] = ["is_deleted = 0", "embedding IS NOT NULL"]
    params: list = []

    if user_id is not None:
        conditions.append("user_id = ?")
        params.append(user_id)

    if agent_id is not None:
        conditions.append("agent_id = ?")
        params.append(agent_id)

    if session_id is not None:
        conditions.append("session_id = ?")
        params.append(session_id)

    if metadata_filter:
        kv_pairs = list(metadata_filter.items())
        if metadata_filter_operator == "or":
            # At least one key-value condition must match
            or_clauses = [f"json_extract(metadata, '$.{key}') = ?" for key, _ in kv_pairs]
            conditions.append(f"({' OR '.join(or_clauses)})")
            for _, val in kv_pairs:
                params.append(val)
        else:
            # Default AND: all key-value conditions must match
            for key, val in kv_pairs:
                conditions.append(f"json_extract(metadata, '$.{key}') = ?")
                params.append(val)

    where_sql = " AND ".join(conditions)
    select_sql = (
        f"SELECT id, text, user_id, agent_id, session_id, metadata, created_at, access_count "
        f"FROM memories WHERE {where_sql}"
    )

    # ------------------------------------------------------------------
    # Step 2: Fetch candidate rows
    # ------------------------------------------------------------------
    candidates: dict[str, dict] = {}
    async with conn.execute(select_sql, params) as cur:
        async for row in cur:
            candidates[row["id"]] = dict(row)

    if not candidates:
        return []

    # ------------------------------------------------------------------
    # Step 3: Embed the query
    # ------------------------------------------------------------------
    query_embedding = await embedding_client.embed_single(query)

    if query_embedding is None:
        # Circuit breaker tripped -- fall back to recency sort
        logger.warning("Embedding client unavailable during search; falling back to recency sort")
        sorted_candidates = sorted(
            candidates.values(),
            key=lambda r: r["created_at"],
            reverse=True,
        )
        results = []
        for row in sorted_candidates[:limit]:
            try:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            results.append({
                "id": row["id"],
                "text": row["text"],
                "score": 0.0,
                "confidence": 0.0,
                "metadata": meta,
                "user_id": row["user_id"],
                "agent_id": row["agent_id"],
                "session_id": row["session_id"],
                "created_at": row["created_at"],
            })
        # ------------------------------------------------------------------
        # Fallback Step 8: Log retrieval feedback (training signal for Q-learning)
        # ------------------------------------------------------------------
        try:
            result_ids = [r["id"] for r in results]
            result_scores = [r["score"] for r in results]
            await log_retrieval(conn, query, result_ids, result_scores, strategy="fallback")
        except Exception:
            logger.debug("Retrieval feedback logging failed (non-fatal)")

        # ------------------------------------------------------------------
        # Fallback Step 9: Q-learning router -- select strategy, compute reward, update
        # ------------------------------------------------------------------
        try:
            strategy = await select_strategy(conn)
            avg_score = sum(r["score"] for r in results) / len(results) if results else 0.0
            reward = compute_reward(len(results), avg_score, max_possible=limit)
            await update_q_value(conn, strategy, "top_k_high", reward)
        except Exception:
            logger.debug("Q-router update failed (non-fatal)")

        return results

    # ------------------------------------------------------------------
    # Step 3b: Extract query entities for confidence scoring (entity overlap component)
    # ------------------------------------------------------------------
    query_entities = extract_entities(query)

    # ------------------------------------------------------------------
    # Step 4: ANN vector search restricted to candidate IDs
    # ------------------------------------------------------------------
    raw_results = await index_manager.search(
        tenant_id,
        query_embedding,
        k=limit,
        candidate_ids=set(candidates.keys()),
    )

    # ------------------------------------------------------------------
    # Step 4b: Track raw cosines for confidence normalization
    # ------------------------------------------------------------------
    raw_cosines: dict[str, float] = {mid: rs for mid, rs in raw_results}
    max_cosine = max(raw_cosines.values()) if raw_cosines else 0.0

    # ------------------------------------------------------------------
    # Step 5: Apply temporal decay to each score
    # ------------------------------------------------------------------
    scored: list[tuple[str, float]] = []
    for memory_id, raw_score in raw_results:
        row = candidates[memory_id]
        final_score = apply_decay(raw_score, row["created_at"])
        scored.append((memory_id, final_score))

    # Step 6: Sort by final_score DESC, take top limit
    scored.sort(key=lambda x: x[1], reverse=True)
    scored = scored[:limit]

    # ------------------------------------------------------------------
    # Step 7: Build result dicts
    # ------------------------------------------------------------------
    results = []
    for memory_id, final_score in scored:
        row = candidates[memory_id]
        try:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
        except (json.JSONDecodeError, TypeError):
            meta = {}

        # Compute confidence score
        raw_cos = raw_cosines.get(memory_id, 0.0)
        access_ct = row.get("access_count", 0) or 0
        conf = compute_confidence(
            raw_cosine=raw_cos,
            max_cosine_in_set=max_cosine,
            query_entities=query_entities,
            memory_text=row["text"],
            access_count=access_ct,
            created_at=row["created_at"],
        )

        results.append({
            "id": row["id"],
            "text": row["text"],
            "score": final_score,
            "confidence": conf,
            "metadata": meta,
            "user_id": row["user_id"],
            "agent_id": row["agent_id"],
            "session_id": row["session_id"],
            "created_at": row["created_at"],
        })

    # ------------------------------------------------------------------
    # Step 8: Log retrieval feedback (training signal for Q-learning)
    # ------------------------------------------------------------------
    try:
        result_ids = [r["id"] for r in results]
        result_scores = [r["score"] for r in results]
        await log_retrieval(conn, query, result_ids, result_scores)
    except Exception:
        logger.debug("Retrieval feedback logging failed (non-fatal)")

    # ------------------------------------------------------------------
    # Step 9: Q-learning router -- select strategy, compute reward, update
    # ------------------------------------------------------------------
    try:
        strategy = await select_strategy(conn)
        avg_score = sum(r["score"] for r in results) / len(results) if results else 0.0
        reward = compute_reward(len(results), avg_score, max_possible=limit)
        await update_q_value(conn, strategy, "top_k_high", reward)
    except Exception:
        logger.debug("Q-router update failed (non-fatal)")

    return results


async def count_tenant_memories(conn: aiosqlite.Connection) -> int:
    """Count non-deleted memories for a tenant (DX-05 memories_used).

    Args:
        conn: Open aiosqlite connection to the tenant's DB.

    Returns:
        Integer count of memories where is_deleted = 0.
    """
    async with conn.execute(
        "SELECT COUNT(*) FROM memories WHERE is_deleted = 0"
    ) as cur:
        row = await cur.fetchone()
    return row[0]
