"""
Pydantic v2 models for memory API endpoints.

Defines request and response models for create, read, update, search,
and list operations on memories.
"""

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    """Request body for POST /memories."""

    text: Annotated[str, Field(min_length=1, description="The text content to store as a memory")]
    user_id: Optional[str] = Field(
        None, description="Optional user ID to scope this memory to a specific user"
    )
    agent_id: Optional[str] = Field(
        None, description="Optional agent ID to scope this memory to a specific AI agent"
    )
    session_id: Optional[str] = Field(
        None, description="Optional session ID to group memories within a conversation"
    )
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Arbitrary key-value metadata attached to the memory"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "The user prefers dark mode and metric units",
                    "user_id": "user_42",
                    "agent_id": "assistant_1",
                    "metadata": {"source": "preferences", "confidence": 0.95},
                }
            ]
        }
    }


class MemoryResponse(BaseModel):
    """Response body for a single memory (create, get, update)."""

    id: str = Field(description="Unique memory identifier (UUID)")
    text: str = Field(description="The stored memory text")
    user_id: Optional[str] = Field(None, description="User ID this memory is scoped to, if any")
    agent_id: Optional[str] = Field(None, description="Agent ID this memory is scoped to, if any")
    session_id: Optional[str] = Field(
        None, description="Session ID this memory belongs to, if any"
    )
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Key-value metadata attached to this memory"
    )
    created_at: int = Field(description="Unix timestamp when the memory was created")
    updated_at: Optional[int] = Field(
        None, description="Unix timestamp when the memory was last modified"
    )
    status: Literal["created", "duplicate"] = Field(
        "created",
        description="Whether this is a newly created memory or a duplicate",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "3f7a2b1c-4e5d-6789-abcd-ef0123456789",
                    "text": "The user prefers dark mode and metric units",
                    "user_id": "user_42",
                    "agent_id": "assistant_1",
                    "session_id": "session_99",
                    "metadata": {"source": "preferences", "confidence": 0.95},
                    "created_at": 1700000000,
                    "updated_at": 1700000000,
                    "status": "created",
                }
            ]
        }
    }


class MemoryUpdate(BaseModel):
    """Request body for PATCH /memories/{id}.

    All fields are optional — only provided fields are updated.
    """

    text: Optional[str] = Field(
        None,
        description="Updated memory text. Only provided fields are updated.",
    )
    metadata: Optional[dict[str, Any]] = Field(
        None,
        description="Updated metadata. Only provided fields are updated.",
    )
    user_id: Optional[str] = Field(
        None,
        description="Updated user ID. Only provided fields are updated.",
    )
    agent_id: Optional[str] = Field(
        None,
        description="Updated agent ID. Only provided fields are updated.",
    )
    session_id: Optional[str] = Field(
        None,
        description="Updated session ID. Only provided fields are updated.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"text": "Updated preference: user now prefers light mode"}
            ]
        }
    }


class MemorySearchRequest(BaseModel):
    """Request body for POST /memories/search."""

    query: Annotated[
        str, Field(min_length=1, description="Natural language search query")
    ]
    user_id: Optional[str] = Field(None, description="Filter results to this user ID")
    agent_id: Optional[str] = Field(None, description="Filter results to this agent ID")
    session_id: Optional[str] = Field(None, description="Filter results to this session ID")
    metadata_filter: Optional[dict[str, Any]] = Field(
        None, description="Key-value pairs to filter results by metadata"
    )
    metadata_filter_operator: Literal["and", "or"] = Field(
        "and",
        description="How to combine metadata filter conditions: 'and' (all must match) or 'or' (any must match)",
    )  # MEM-03: AND/OR logic
    limit: Annotated[int, Field(default=10, ge=1, le=100, description="Maximum number of results to return (1-100)")] = 10

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "query": "what display preferences does the user have?",
                    "limit": 5,
                }
            ]
        }
    }


class MemorySearchResult(BaseModel):
    """A single result item in a search response."""

    id: str = Field(description="Unique memory identifier (UUID)")
    text: str = Field(description="The stored memory text")
    score: float = Field(description="Relevance score (0.0-1.0, higher is more relevant)")
    metadata: Optional[dict[str, Any]] = Field(
        None, description="Key-value metadata attached to this memory"
    )
    user_id: Optional[str] = Field(None, description="User ID this memory is scoped to, if any")
    agent_id: Optional[str] = Field(None, description="Agent ID this memory is scoped to, if any")
    session_id: Optional[str] = Field(
        None, description="Session ID this memory belongs to, if any"
    )
    created_at: int = Field(description="Unix timestamp when the memory was created")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "3f7a2b1c-4e5d-6789-abcd-ef0123456789",
                    "text": "The user prefers dark mode and metric units",
                    "score": 0.92,
                    "metadata": {"source": "preferences"},
                    "user_id": "user_42",
                    "agent_id": "assistant_1",
                    "session_id": None,
                    "created_at": 1700000000,
                }
            ]
        }
    }


class MemorySearchResponse(BaseModel):
    """Response body for POST /memories/search."""

    results: list[MemorySearchResult] = Field(
        description="List of matching memories ranked by relevance"
    )
    total: int = Field(description="Number of results returned")
    memories_used: int = Field(description="Total memories stored by this tenant")
    memories_limit: int = Field(description="Maximum memories allowed on current plan")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "results": [
                        {
                            "id": "3f7a2b1c-4e5d-6789-abcd-ef0123456789",
                            "text": "The user prefers dark mode and metric units",
                            "score": 0.92,
                            "metadata": {"source": "preferences"},
                            "user_id": "user_42",
                            "agent_id": None,
                            "session_id": None,
                            "created_at": 1700000000,
                        }
                    ],
                    "total": 1,
                    "memories_used": 42,
                    "memories_limit": 1000,
                }
            ]
        }
    }


class MemoryListResponse(BaseModel):
    """Response body for GET /memories (paginated list)."""

    memories: list[MemoryResponse] = Field(
        description="Page of memories ordered newest-first"
    )
    total: int = Field(description="Total number of non-deleted memories matching the filter")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of memories per page")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "memories": [
                        {
                            "id": "3f7a2b1c-4e5d-6789-abcd-ef0123456789",
                            "text": "The user prefers dark mode and metric units",
                            "user_id": "user_42",
                            "agent_id": None,
                            "session_id": None,
                            "metadata": {},
                            "created_at": 1700000000,
                            "updated_at": 1700000000,
                            "status": "created",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                }
            ]
        }
    }
