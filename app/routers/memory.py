"""
Memory write router — POST /v1/memory.

Primary memory ingestion endpoint. Responsibilities:
- Exact-match dedup via text_hash (case- and whitespace-insensitive)
- Background embedding generation (non-blocking response)
- Background entity extraction (non-blocking response)
- Usage logging for every request
- Per-tenant rate limiting at 60 requests/minute (MEM-12)
"""

import json
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from starlette.responses import JSONResponse

from app.db.system import log_usage
from app.deps import get_tenant
from app.limiter import limiter
from app.models.memory import MemoryCreate, MemoryResponse
from app.services.dedup import check_cosine_duplicate, text_hash
from app.services.entity_extraction import process_entities_for_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["memory"])


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------


async def _generate_embedding(
    tenant_id: str,
    memory_id: str,
    text: str,
    app_state,
) -> None:
    """Generate embedding in background and persist to tenant DB + vector index.

    - Fetches embedding from EmbeddingClient (circuit breaker protected).
    - If unavailable (breaker tripped or no API key), logs warning and returns.
    - Stores serialized numpy bytes in memories.embedding column.
    - Adds vector to TenantIndexManager for ANN search.
    - Runs cosine dedup check; soft-deletes the new memory if a near-duplicate
      is found (similarity >= 0.95).

    BackgroundTasks silently swallows exceptions — this function wraps all
    logic in try/except with logging to ensure failures are observable.
    """
    try:
        embedding = await app_state.embedding_client.embed_single(text)
        if embedding is None:
            logger.warning(
                "Embedding skipped for memory %s (circuit breaker open or no API key)",
                memory_id,
            )
            return

        # Persist embedding blob to tenant DB
        conn = await app_state.tenant_manager.get_connection(tenant_id)
        await conn.execute(
            "UPDATE memories SET embedding = ? WHERE id = ?",
            (embedding.tobytes(), memory_id),
        )
        await conn.commit()

        # Add to vector index
        app_state.index_manager.add_vector(tenant_id, memory_id, embedding)

        # Post-embedding cosine dedup check
        # Fetch embeddings of other non-deleted memories for this tenant
        import numpy as np

        candidate_embeddings = []
        async with conn.execute(
            "SELECT id, embedding FROM memories WHERE is_deleted = 0 AND id != ? AND embedding IS NOT NULL",
            (memory_id,),
        ) as cur:
            async for row in cur:
                other_id = row["id"]
                emb_bytes_val = row["embedding"]
                if emb_bytes_val is not None:
                    other_embedding = np.frombuffer(emb_bytes_val, dtype=np.float32)
                    candidate_embeddings.append((other_id, other_embedding))

        if candidate_embeddings:
            dupe_id = check_cosine_duplicate(embedding, candidate_embeddings)
            if dupe_id is not None:
                logger.info(
                    "Cosine near-duplicate detected: memory %s ~ %s (threshold=0.95) — soft-deleting new memory",
                    memory_id,
                    dupe_id,
                )
                await conn.execute(
                    "UPDATE memories SET is_deleted = 1 WHERE id = ?",
                    (memory_id,),
                )
                await conn.commit()

    except Exception:
        logger.exception("Background embedding failed for memory %s", memory_id)


async def _extract_entities(
    tenant_id: str,
    memory_id: str,
    text: str,
    app_state,
) -> None:
    """Extract and persist entities/relations for a memory in the background.

    BackgroundTasks silently swallows exceptions — wrapped in try/except with
    logging to ensure failures are observable.
    """
    try:
        conn = await app_state.tenant_manager.get_connection(tenant_id)
        result = await process_entities_for_memory(conn, memory_id, text)
        logger.debug(
            "Entity extraction for memory %s: %d entities, %d relations",
            memory_id,
            result["entities_found"],
            result["relations_found"],
        )
    except Exception:
        logger.exception("Background entity extraction failed for memory %s", memory_id)


# ---------------------------------------------------------------------------
# POST /v1/memory
# ---------------------------------------------------------------------------


@router.post("/memory", status_code=201)
@limiter.limit("60/minute")
async def create_memory(
    body: MemoryCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant),
):
    """Store a new memory for the authenticated tenant.

    - Returns 201 + MemoryResponse(status="created") for new memories.
    - Returns 200 + MemoryResponse(status="duplicate") when the same text was
      already stored (exact match via text_hash — case/whitespace insensitive).
    - Background tasks: embedding generation + entity extraction.
    - Every call is recorded in usage_log.
    - Rate-limited at 60 requests/minute per tenant (MEM-12).
    """
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    # Exact-match dedup via text_hash
    th = text_hash(body.text)
    async with conn.execute(
        "SELECT id, text, user_id, agent_id, session_id, metadata, created_at, updated_at "
        "FROM memories WHERE text_hash = ? AND is_deleted = 0",
        (th,),
    ) as cur:
        existing = await cur.fetchone()

    if existing is not None:
        # Duplicate — log and return 200
        await log_usage(
            request.app.state.system_db,
            tenant["id"],
            "memory.create.duplicate",
            "/v1/memory",
            200,
        )
        metadata_raw = existing["metadata"] if existing["metadata"] else "{}"
        try:
            metadata_parsed = json.loads(metadata_raw)
        except (json.JSONDecodeError, TypeError):
            metadata_parsed = {}
        return JSONResponse(
            status_code=200,
            content=MemoryResponse(
                id=existing["id"],
                text=existing["text"],
                user_id=existing["user_id"],
                agent_id=existing["agent_id"],
                session_id=existing["session_id"],
                metadata=metadata_parsed,
                created_at=existing["created_at"],
                updated_at=existing["updated_at"],
                status="duplicate",
            ).model_dump(),
        )

    # New memory — insert and queue background tasks
    memory_id = str(uuid.uuid4())
    now = int(time.time())

    await conn.execute(
        """
        INSERT INTO memories
            (id, text, text_hash, user_id, agent_id, session_id, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            body.text,
            th,
            body.user_id,
            body.agent_id,
            body.session_id,
            json.dumps(body.metadata or {}),
            now,
            now,
        ),
    )
    await conn.commit()

    # Queue background tasks (non-blocking — response returns immediately)
    background_tasks.add_task(
        _generate_embedding,
        tenant["id"],
        memory_id,
        body.text,
        request.app.state,
    )
    background_tasks.add_task(
        _extract_entities,
        tenant["id"],
        memory_id,
        body.text,
        request.app.state,
    )

    # Log usage
    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "memory.create",
        "/v1/memory",
        201,
    )

    return MemoryResponse(
        id=memory_id,
        text=body.text,
        user_id=body.user_id,
        agent_id=body.agent_id,
        session_id=body.session_id,
        metadata=body.metadata or {},
        created_at=now,
        updated_at=now,
        status="created",
    )
