import os
from datetime import datetime, timezone

from fastapi import APIRouter

from app.config import DATA_DIR, FIREWORKS_API_KEY

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Health check endpoint. No auth required. Always returns 200."""
    # disk_mounted: only meaningful on Render where a persistent disk is expected
    if os.environ.get("RENDER"):
        disk_mounted = os.path.ismount(str(DATA_DIR))
    else:
        disk_mounted = None  # not applicable locally

    embedding_configured = bool(FIREWORKS_API_KEY)

    # Collect non-None checks; degraded if any are False
    non_null_checks = [v for v in [disk_mounted, embedding_configured] if v is not None]
    status = "healthy" if all(non_null_checks) else "degraded"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "checks": {
            "disk_mounted": disk_mounted,
            "disk_path": str(DATA_DIR),
            "embedding_configured": embedding_configured,
        },
    }
