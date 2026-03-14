from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import (
    DATA_DIR,
    EMBEDDING_DIM,
    EMBEDDING_MODEL,
    FIREWORKS_API_KEY,
    MAX_TENANT_CONNECTIONS,
    MAX_VECTOR_INDEXES,
    VECTOR_INDEX_DIR,
)
from app.db.manager import TenantDBManager
from app.db.system import init_system_db
from app.deps import get_tenant
from app.limiter import limiter
from app.routers.health import router as health_router
from app.routers.memory import router as memory_router
from app.services.embedding import EmbeddingClient
from app.services.vector_index import TenantIndexManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VECTOR_INDEX_DIR.mkdir(parents=True, exist_ok=True)

    app.state.system_db = await init_system_db(DATA_DIR)
    app.state.tenant_manager = TenantDBManager(
        data_dir=DATA_DIR,
        max_connections=MAX_TENANT_CONNECTIONS,
    )
    app.state.embedding_client = EmbeddingClient(
        api_key=FIREWORKS_API_KEY,
        model=EMBEDDING_MODEL,
        dim=EMBEDDING_DIM,
    )
    app.state.index_manager = TenantIndexManager(
        data_dir=VECTOR_INDEX_DIR,
        dim=EMBEDDING_DIM,
        max_cached=MAX_VECTOR_INDEXES,
    )

    yield

    # Shutdown
    await app.state.index_manager.close()
    await app.state.embedding_client.close()
    await app.state.tenant_manager.close_all()
    await app.state.system_db.close()


app = FastAPI(
    title="MemoraLabs",
    description="Memory-as-a-Service API",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(health_router)
app.include_router(memory_router)


# ---------------------------------------------------------------------------
# Test helper endpoint — exercises Depends(get_tenant).
# Used by tests/test_deps.py; returns tenant id/email/plan for verification.
# ---------------------------------------------------------------------------


@app.get("/_test/tenant")
async def _test_get_tenant(
    tenant: Annotated[dict, Depends(get_tenant)],
) -> dict:
    """Return resolved tenant info. Used by test_deps.py to verify auth."""
    return {"id": tenant["id"], "email": tenant["email"], "plan": tenant["plan"]}
