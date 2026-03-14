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
