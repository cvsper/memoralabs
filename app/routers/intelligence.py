"""
Intelligence router — self-improving memory endpoints.

Exposes Q-learning router diagnostics and intelligence layer metrics.
All endpoints require tenant authentication via get_tenant.

Endpoints:
    GET /v1/intelligence/router/stats — current Q-table state and activation status
"""

import logging

from fastapi import APIRouter, Depends, Request

from app.db.system import log_usage
from app.deps import get_tenant
from app.limiter import limiter
from app.models.intelligence import QTableEntry, RouterStats
from app.services.q_router import get_router_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/intelligence", tags=["intelligence"])


@router.get(
    "/router/stats",
    response_model=RouterStats,
    responses={
        401: {
            "description": "Missing or invalid API key",
            "content": {
                "application/json": {
                    "example": {"error": "UNAUTHORIZED", "message": "Invalid API key"}
                }
            },
        },
        429: {"description": "Rate limit exceeded (30/minute)"},
    },
)
@limiter.limit("30/minute")
async def get_router_stats_endpoint(
    request: Request,
    tenant: dict = Depends(get_tenant),
):
    """Return the current Q-learning router state.

    Shows Q-values, visit counts, and activation status for each
    strategy-config pair. The router influences retrieval strategy
    selection once any pair reaches 30 visits (the activation threshold).
    Below threshold, all searches use the "default" strategy — Q-values
    accumulate silently without affecting routing.
    """
    conn = await request.app.state.tenant_manager.get_connection(tenant["id"])

    stats = await get_router_stats(conn)

    await log_usage(
        request.app.state.system_db,
        tenant["id"],
        "intelligence.router_stats",
        "/v1/intelligence/router/stats",
        200,
    )

    return RouterStats(
        strategies=[QTableEntry(**entry) for entry in stats["strategies"]],
        total_updates=stats["total_updates"],
        is_active=stats["is_active"],
    )
