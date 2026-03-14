"""
Pydantic v2 models for intelligence API endpoints.

Defines response models for the self-improving memory intelligence layer:
Q-learning router stats, strategy Q-values, activation state, and
knowledge gap detection.
"""

from typing import Literal

from pydantic import BaseModel, Field


class QTableEntry(BaseModel):
    """A single entry in the Q-learning routing table."""

    strategy: str = Field(description="Retrieval strategy name (precision, temporal, relational, broad)")
    config_key: str = Field(description="Config dimension this Q-value tracks (e.g. top_k_high)")
    q_value: float = Field(description="Current Q-value for this state-action pair (0.0–1.0)")
    visit_count: int = Field(description="Number of times this state-action pair has been updated")
    activated: bool = Field(
        description="True if visit_count >= activation threshold (30) — Q-values are influencing routing"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "strategy": "precision",
                    "config_key": "top_k_high",
                    "q_value": 0.72,
                    "visit_count": 45,
                    "activated": True,
                }
            ]
        }
    }


class RouterStats(BaseModel):
    """Response body for GET /v1/intelligence/router/stats.

    Reports the current state of the Q-learning routing table,
    including per-strategy Q-values and whether the router has
    accumulated enough observations to influence retrieval.
    """

    strategies: list[QTableEntry] = Field(
        description="All strategy-config entries in the Q-table"
    )
    total_updates: int = Field(
        description="Total Q-value updates applied across all strategy-config pairs"
    )
    is_active: bool = Field(
        description="True if any strategy-config pair has reached the activation threshold — routing is live"
    )
    activation_threshold: int = Field(
        30,
        description="Minimum visits per state-action pair before Q-values influence strategy selection",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "strategies": [
                        {
                            "strategy": "precision",
                            "config_key": "top_k_high",
                            "q_value": 0.72,
                            "visit_count": 45,
                            "activated": True,
                        },
                        {
                            "strategy": "temporal",
                            "config_key": "top_k_high",
                            "q_value": 0.61,
                            "visit_count": 32,
                            "activated": True,
                        },
                    ],
                    "total_updates": 77,
                    "is_active": True,
                    "activation_threshold": 30,
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Knowledge gap detection models (05-03)
# ---------------------------------------------------------------------------


class KnowledgeGap(BaseModel):
    """A single knowledge gap — an entity frequently queried but absent from memory."""

    entity: str = Field(description="Normalized entity name")
    type: str = Field(description="Entity type (person, organization, location, date, topic)")
    query_mentions: int = Field(description="Number of times this entity appeared in queries")
    status: Literal["missing"] = "missing"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "entity": "projectx",
                    "type": "topic",
                    "query_mentions": 7,
                    "status": "missing",
                }
            ]
        }
    }


class GapDetectionRequest(BaseModel):
    """Request body for POST /v1/memory/gaps."""

    days: int = Field(
        default=30,
        ge=1,
        le=365,
        description="Lookback window in days",
    )
    min_mentions: int = Field(
        default=3,
        ge=1,
        description="Minimum query mentions to qualify as a gap",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"days": 30, "min_mentions": 3},
            ]
        }
    }


class GapDetectionResponse(BaseModel):
    """Response from POST /v1/memory/gaps."""

    gaps: list[KnowledgeGap] = Field(description="Entities queried but absent from stored memories")
    total: int = Field(description="Total number of gaps found")
    window_days: int = Field(description="Lookback window used")
    queries_analyzed: int = Field(
        description="Number of queries analyzed (short queries excluded)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "gaps": [
                        {
                            "entity": "projectx",
                            "type": "topic",
                            "query_mentions": 7,
                            "status": "missing",
                        }
                    ],
                    "total": 1,
                    "window_days": 30,
                    "queries_analyzed": 42,
                }
            ]
        }
    }
