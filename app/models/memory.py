"""
Pydantic v2 models for memory API endpoints.

Defines request and response models for create, read, update, search,
and list operations on memories.
"""

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    """Request body for POST /memories."""

    text: Annotated[str, Field(min_length=1)]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class MemoryResponse(BaseModel):
    """Response body for a single memory (create, get, update)."""

    id: str
    text: str
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    created_at: int
    updated_at: Optional[int] = None
    status: Literal["created", "duplicate"] = "created"


class MemoryUpdate(BaseModel):
    """Request body for PATCH /memories/{id}.

    All fields are optional — only provided fields are updated.
    """

    text: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None


class MemorySearchRequest(BaseModel):
    """Request body for POST /memories/search."""

    query: Annotated[str, Field(min_length=1)]
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata_filter: Optional[dict[str, Any]] = None
    metadata_filter_operator: Literal["and", "or"] = "and"  # MEM-03: AND/OR logic
    limit: Annotated[int, Field(default=10, ge=1, le=100)] = 10


class MemorySearchResult(BaseModel):
    """A single result item in a search response."""

    id: str
    text: str
    score: float
    metadata: Optional[dict[str, Any]] = None
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    created_at: int


class MemorySearchResponse(BaseModel):
    """Response body for POST /memories/search."""

    results: list[MemorySearchResult]
    total: int
    memories_used: int
    memories_limit: int


class MemoryListResponse(BaseModel):
    """Response body for GET /memories (paginated list)."""

    memories: list[MemoryResponse]
    total: int
    page: int
    page_size: int
