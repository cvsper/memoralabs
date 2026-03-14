"""
Memory router — POST, GET, PATCH, DELETE /v1/memory.

Primary memory ingestion and management endpoints. Responsibilities:
- Exact-match dedup via text_hash (case- and whitespace-insensitive)
- Background embedding generation (non-blocking response)
- Background entity extraction (non-blocking response)
- Paginated list with optional scope filters (user_id, agent_id, session_id)
- Get single memory by ID with access_count tracking
- Get entities/relations linked to a memory (RETR-03)
- Patch memory fields; re-queues embedding on text change
- Soft-delete with vector index removal
- Usage logging for every request
- Per-tenant rate limiting at 60 requests/minute (MEM-12)
"""

import json
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from starlette.responses import JSONResponse

from app.db.system import log_usage
from app.deps import get_tenant
from app.limiter import limiter
from app.models.memory import MemoryCreate, MemoryListResponse, MemoryResponse, MemoryUpdate
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


# ---------------------------------------------------------------------------
# GET /v1/memory — list with pagination + scope filters
# ---------------------------------------------------------------------------


@router.get("/memory", response_model=MemoryListResponse)
async def list_memories(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user_id: str | None = Query(None),
    agent_id: str | None = Query(None),
    session_id: str | None = Query(None),
    tenant: dict = Depends(get_tenant),
):
    """Return a paginated list of non-deleted memories for the authenticated tenant.

    Optionally filter by user_id, agent_id, or session_id. Results are ordered
    newest-first by created_at.
    """
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    # Build dynamic WHERE clause
    conditions = ["is_deleted = 0"]
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

    where_clause = " AND ".join(conditions)

    # Count total
    async with conn.execute(
        f"SELECT COUNT(*) FROM memories WHERE {where_clause}",
        params,
    ) as cur:
        row = await cur.fetchone()
    total = row[0]

    # Fetch page
    offset = (page - 1) * page_size
    fetch_params = params + [page_size, offset]
    memories = []
    async with conn.execute(
        f"SELECT id, text, user_id, agent_id, session_id, metadata, created_at, updated_at "
        f"FROM memories WHERE {where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        fetch_params,
    ) as cur:
        async for mem_row in cur:
            try:
                meta = json.loads(mem_row["metadata"]) if mem_row["metadata"] else {}
            except (json.JSONDecodeError, TypeError):
                meta = {}
            memories.append(
                MemoryResponse(
                    id=mem_row["id"],
                    text=mem_row["text"],
                    user_id=mem_row["user_id"],
                    agent_id=mem_row["agent_id"],
                    session_id=mem_row["session_id"],
                    metadata=meta,
                    created_at=mem_row["created_at"],
                    updated_at=mem_row["updated_at"],
                    status="created",
                )
            )

    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "memory.list",
        "/v1/memory",
        200,
    )

    return MemoryListResponse(memories=memories, total=total, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# GET /v1/memory/{memory_id}/entities — RETR-03
# Must be registered BEFORE /memory/{memory_id} to avoid path-match conflict.
# ---------------------------------------------------------------------------


@router.get("/memory/{memory_id}/entities")
async def get_memory_entities(
    memory_id: str,
    request: Request,
    tenant: dict = Depends(get_tenant),
):
    """Return entities and relations extracted for a specific memory (RETR-03).

    Entities are discovered by finding all distinct entity IDs referenced as
    source or target in the relations table for this memory. Relations are
    returned with resolved source/target names and types.
    """
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    # Verify memory exists and is not deleted
    async with conn.execute(
        "SELECT id FROM memories WHERE id = ? AND is_deleted = 0",
        (memory_id,),
    ) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Memory not found")

    # Query relations for this memory (includes full source/target info)
    relations = []
    # Track entity IDs referenced by relations
    referenced_entity_ids: set[str] = set()
    async with conn.execute(
        """
        SELECT r.id, r.source_entity_id, r.relationship, r.target_entity_id,
               se.name AS source_name, se.entity_type AS source_type,
               te.name AS target_name, te.entity_type AS target_type
        FROM relations r
        JOIN entities se ON r.source_entity_id = se.id
        JOIN entities te ON r.target_entity_id = te.id
        WHERE r.memory_id = ?
        """,
        (memory_id,),
    ) as cur:
        async for rel_row in cur:
            referenced_entity_ids.add(rel_row["source_entity_id"])
            referenced_entity_ids.add(rel_row["target_entity_id"])
            relations.append(
                {
                    "id": rel_row["id"],
                    "source_entity_id": rel_row["source_entity_id"],
                    "relationship": rel_row["relationship"],
                    "target_entity_id": rel_row["target_entity_id"],
                    "source_name": rel_row["source_name"],
                    "source_type": rel_row["source_type"],
                    "target_name": rel_row["target_name"],
                    "target_type": rel_row["target_type"],
                }
            )

    # Fetch entity details for all entities referenced by relations
    entities = []
    if referenced_entity_ids:
        placeholders = ",".join("?" * len(referenced_entity_ids))
        async with conn.execute(
            f"SELECT id, name, entity_type, name_normalized, created_at "
            f"FROM entities WHERE id IN ({placeholders})",
            list(referenced_entity_ids),
        ) as cur:
            async for ent_row in cur:
                entities.append(
                    {
                        "id": ent_row["id"],
                        "name": ent_row["name"],
                        "entity_type": ent_row["entity_type"],
                        "name_normalized": ent_row["name_normalized"],
                        "created_at": ent_row["created_at"],
                    }
                )

    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "memory.entities",
        f"/v1/memory/{memory_id}/entities",
        200,
    )

    return {
        "memory_id": memory_id,
        "entities": entities,
        "relations": relations,
        "total_entities": len(entities),
        "total_relations": len(relations),
    }


# ---------------------------------------------------------------------------
# GET /v1/memory/{memory_id} — get single memory
# ---------------------------------------------------------------------------


@router.get("/memory/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    request: Request,
    tenant: dict = Depends(get_tenant),
):
    """Return a single memory by ID. Updates access_count and last_accessed on each call."""
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    async with conn.execute(
        "SELECT * FROM memories WHERE id = ? AND is_deleted = 0",
        (memory_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Update access tracking
    now = int(time.time())
    await conn.execute(
        "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
        (now, memory_id),
    )
    await conn.commit()

    try:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "memory.get",
        f"/v1/memory/{memory_id}",
        200,
    )

    return MemoryResponse(
        id=row["id"],
        text=row["text"],
        user_id=row["user_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        metadata=meta,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        status="created",
    )


# ---------------------------------------------------------------------------
# PATCH /v1/memory/{memory_id} — partial update
# ---------------------------------------------------------------------------


@router.patch("/memory/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant),
):
    """Update one or more fields of an existing memory.

    If text is updated, text_hash is recalculated and embedding + entity
    extraction are re-queued as background tasks.
    """
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    # Verify memory exists
    async with conn.execute(
        "SELECT id FROM memories WHERE id = ? AND is_deleted = 0",
        (memory_id,),
    ) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Memory not found")

    now = int(time.time())
    set_clauses: list[str] = ["updated_at = ?"]
    update_params: list = [now]
    text_changed = False

    if body.text is not None:
        set_clauses.append("text = ?")
        update_params.append(body.text)
        set_clauses.append("text_hash = ?")
        update_params.append(text_hash(body.text))
        text_changed = True

    if body.metadata is not None:
        set_clauses.append("metadata = ?")
        update_params.append(json.dumps(body.metadata))

    if body.user_id is not None:
        set_clauses.append("user_id = ?")
        update_params.append(body.user_id)

    if body.agent_id is not None:
        set_clauses.append("agent_id = ?")
        update_params.append(body.agent_id)

    if body.session_id is not None:
        set_clauses.append("session_id = ?")
        update_params.append(body.session_id)

    update_params.append(memory_id)
    await conn.execute(
        f"UPDATE memories SET {', '.join(set_clauses)} WHERE id = ?",
        update_params,
    )
    await conn.commit()

    if text_changed:
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

    # Fetch updated memory
    async with conn.execute(
        "SELECT * FROM memories WHERE id = ?",
        (memory_id,),
    ) as cur:
        updated_row = await cur.fetchone()

    try:
        meta = json.loads(updated_row["metadata"]) if updated_row["metadata"] else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "memory.update",
        f"/v1/memory/{memory_id}",
        200,
    )

    return MemoryResponse(
        id=updated_row["id"],
        text=updated_row["text"],
        user_id=updated_row["user_id"],
        agent_id=updated_row["agent_id"],
        session_id=updated_row["session_id"],
        metadata=meta,
        created_at=updated_row["created_at"],
        updated_at=updated_row["updated_at"],
        status="created",
    )


# ---------------------------------------------------------------------------
# DELETE /v1/memory/{memory_id} — soft-delete
# ---------------------------------------------------------------------------


@router.delete("/memory/{memory_id}")
async def delete_memory(
    memory_id: str,
    request: Request,
    tenant: dict = Depends(get_tenant),
):
    """Soft-delete a memory (sets is_deleted=1). Removes it from the vector index.

    Memory records are never physically removed from the database.
    Subsequent GET/PATCH/DELETE calls will return 404.
    """
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    async with conn.execute(
        "SELECT id FROM memories WHERE id = ? AND is_deleted = 0",
        (memory_id,),
    ) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Memory not found")

    now = int(time.time())
    await conn.execute(
        "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE id = ?",
        (now, memory_id),
    )
    await conn.commit()

    # Remove from vector index (non-fatal — index may not have this memory yet)
    try:
        await request.app.state.index_manager.remove_vector(tenant["id"], memory_id)
    except Exception:
        logger.debug("Vector index removal skipped for memory %s (not indexed or error)", memory_id)

    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "memory.delete",
        f"/v1/memory/{memory_id}",
        200,
    )

    return {"id": memory_id, "status": "deleted"}
