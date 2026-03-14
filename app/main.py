from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

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
from app.routers.auth import router as auth_router
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
    description="""## Memory-as-a-Service API

MemoraLabs gives your AI agents persistent, searchable memory.
Store facts, conversations, and context — then retrieve them with semantic search.

### Quick Start
1. **Sign up** — `POST /v1/auth/signup`
2. **Store a memory** — `POST /v1/memory`
3. **Search memories** — `POST /v1/memory/search`

[Full Quickstart Guide](/quickstart) | [GitHub](https://github.com/memoralabs)
""",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "auth", "description": "Developer registration and API key management"},
        {"name": "memory", "description": "Store, search, list, update, and delete memories"},
        {"name": "health", "description": "Service health and status"},
    ],
)


def _status_to_error_code(status_code: int) -> str:
    """Map HTTP status code to a machine-readable error code."""
    codes = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }
    return codes.get(status_code, "INTERNAL_ERROR")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Ensure all HTTP exceptions return structured JSON (never HTML)."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": _status_to_error_code(exc.status_code),
            "message": exc.detail,
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic validation errors return structured JSON with field details."""
    # Pydantic v2 error dicts may contain non-serializable ctx values (e.g. ValueError).
    # Stringify ctx entries so the response is always valid JSON.
    def _safe_error(e: dict) -> dict:
        safe = {k: v for k, v in e.items() if k != "ctx"}
        if "ctx" in e:
            safe["ctx"] = {k: str(v) for k, v in e["ctx"].items()}
        return safe

    return JSONResponse(
        status_code=422,
        content={
            "error": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": [_safe_error(e) for e in exc.errors()],
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all: never leak stack traces to clients."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
        },
    )


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(auth_router)
app.include_router(health_router)
app.include_router(memory_router)


# ---------------------------------------------------------------------------
# Test helper endpoint — exercises Depends(get_tenant).
# Used by tests/test_deps.py; returns tenant id/email/plan for verification.
# ---------------------------------------------------------------------------


@app.get("/_test/tenant", include_in_schema=False)
async def _test_get_tenant(
    tenant: Annotated[dict, Depends(get_tenant)],
) -> dict:
    """Return resolved tenant info. Used by test_deps.py to verify auth."""
    return {"id": tenant["id"], "email": tenant["email"], "plan": tenant["plan"]}
