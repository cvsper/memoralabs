# Phase 4: Developer Experience - Research

**Researched:** 2026-03-14
**Domain:** FastAPI OpenAPI docs, static landing page, quickstart guide
**Confidence:** HIGH

## Summary

Phase 4 focuses on three deliverables: polishing the auto-generated OpenAPI docs with response examples and descriptions (04-02), building a simple landing page at `/` (04-03), and writing a quickstart guide (04-04). DX-04 (structured errors) and DX-05 (usage metadata) are already implemented in the codebase and only need verification.

The existing FastAPI app at `app/main.py` already generates Swagger UI at `/docs` with basic metadata (`title="MemoraLabs"`, `description="Memory-as-a-Service API"`, `version="0.1.0"`). The Pydantic models are clean and well-typed but lack `json_schema_extra` examples and `Field(description=...)` annotations. The routers use `tags=["auth"]` and `tags=["memory"]` but endpoint docstrings are developer-facing comments, not user-facing API descriptions.

**Primary recommendation:** Add `model_config` with `json_schema_extra` examples to all Pydantic request/response models, enrich the `FastAPI()` constructor with full OpenAPI metadata, serve a single-file HTML landing page via `HTMLResponse` at `/`, and host the quickstart as a Markdown file in the repo plus an in-docs description block.

## Standard Stack

### Core (Already Installed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.115.0 | Auto-generates OpenAPI 3.1 schema + Swagger UI at `/docs` | Built-in, zero config |
| Pydantic | >=2.0.0 | Request/response schema with JSON Schema generation | Native FastAPI integration |
| uvicorn | >=0.34.0 | ASGI server | Standard FastAPI server |

### Supporting (No New Dependencies Needed)
| Library | Purpose | Notes |
|---------|---------|-------|
| `fastapi.responses.HTMLResponse` | Serve landing page HTML inline | Already available, no install |
| `fastapi.staticfiles.StaticFiles` | Serve CSS/JS assets if needed | Already available via starlette |

### What NOT to Add
| Don't Add | Why |
|-----------|-----|
| Jinja2 | Overkill for a single landing page; `HTMLResponse` is sufficient |
| Sphinx/MkDocs | The OpenAPI docs ARE the API reference; quickstart is a simple markdown/HTML page |
| Redoc | FastAPI already bundles ReDoc at `/redoc` automatically |
| sphinx-openapi | Unnecessary — Swagger UI and ReDoc are already served |

## Architecture Patterns

### Recommended File Structure for Phase 4
```
app/
├── main.py              # Add OpenAPI metadata, landing page route, mount static
├── static/              # NEW: CSS/assets for landing page
│   └── style.css        # Minimal landing page styles
├── routers/
│   ├── auth.py          # Add response examples, descriptions
│   ├── memory.py        # Add response examples, descriptions
│   └── health.py        # Already minimal, just add tags
├── models/
│   ├── schemas.py       # Add json_schema_extra examples
│   └── memory.py        # Add json_schema_extra examples
QUICKSTART.md            # NEW: Quickstart guide (repo root)
```

### Pattern 1: OpenAPI Metadata on FastAPI Constructor
**What:** Enrich the `FastAPI()` call with full API metadata
**When to use:** Once, in `main.py`
**Example:**
```python
# Source: https://fastapi.tiangolo.com/tutorial/metadata/
app = FastAPI(
    title="MemoraLabs",
    description="""
## Memory-as-a-Service API

MemoraLabs gives your AI agents persistent, searchable memory.
Store facts, conversations, and context — then retrieve them
with semantic search.

### Quick Start
1. **Sign up** → `POST /v1/auth/signup`
2. **Store a memory** → `POST /v1/memory`
3. **Search memories** → `POST /v1/memory/search`

[Full Quickstart Guide](/quickstart)
""",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {
            "name": "auth",
            "description": "Developer registration and API key management",
        },
        {
            "name": "memory",
            "description": "Store, search, list, update, and delete memories",
        },
        {
            "name": "health",
            "description": "Service health check",
        },
    ],
)
```

### Pattern 2: Pydantic Model Examples via `model_config`
**What:** Add realistic examples to request/response models so Swagger UI shows them
**When to use:** On every Pydantic model used as request body or response
**Example:**
```python
# Source: https://fastapi.tiangolo.com/tutorial/schema-extra-example/
class MemoryCreate(BaseModel):
    text: Annotated[str, Field(min_length=1, description="The text content to memorize")]
    user_id: Optional[str] = Field(None, description="ID of the user this memory belongs to")
    agent_id: Optional[str] = Field(None, description="ID of the AI agent that created this memory")
    session_id: Optional[str] = Field(None, description="Session identifier for grouping memories")
    metadata: Optional[dict[str, Any]] = Field(None, description="Arbitrary key-value metadata")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "text": "The user prefers dark mode and metric units",
                    "user_id": "user_42",
                    "agent_id": "assistant_1",
                    "metadata": {"source": "preferences", "confidence": 0.95}
                }
            ]
        }
    }
```

### Pattern 3: Response Examples on Endpoints via `responses` Parameter
**What:** Document error responses with schemas in OpenAPI
**When to use:** On endpoints that return non-200 status codes
**Example:**
```python
# Source: https://fastapi.tiangolo.com/advanced/additional-responses/
@router.post(
    "/memory",
    status_code=201,
    response_model=MemoryResponse,
    responses={
        200: {
            "model": MemoryResponse,
            "description": "Duplicate — identical text already stored",
        },
        401: {
            "description": "Missing or invalid API key",
            "content": {
                "application/json": {
                    "example": {"error": "UNAUTHORIZED", "message": "Invalid API key"}
                }
            },
        },
        429: {
            "description": "Rate limit exceeded (60/minute)",
            "content": {
                "application/json": {
                    "example": {"error": "RATE_LIMITED", "message": "Rate limit exceeded"}
                }
            },
        },
    },
)
```

### Pattern 4: Landing Page via HTMLResponse at `/`
**What:** Serve a static marketing page without templates or extra dependencies
**When to use:** At the root route `/`
**Example:**
```python
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Mount static assets (CSS, images)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page():
    return """<!DOCTYPE html>
    <html>
    <head><title>MemoraLabs</title>
    <link rel="stylesheet" href="/static/style.css">
    </head>
    <body>...</body>
    </html>"""
```

**Important:** Use `include_in_schema=False` so the landing page does not appear in OpenAPI docs. Mount static files AFTER defining API routes (mount order matters in FastAPI — later mounts don't shadow earlier routes).

### Pattern 5: Quickstart at a Dedicated Route
**What:** Serve the quickstart guide as an HTML page at `/quickstart`
**When to use:** For the developer-facing getting started guide
```python
@app.get("/quickstart", response_class=HTMLResponse, include_in_schema=False)
async def quickstart():
    return """<!DOCTYPE html>..."""
```

### Anti-Patterns to Avoid
- **Jinja2 for one page:** Adding a template engine dependency for a single static page is unnecessary overhead. Use `HTMLResponse` with an inline or file-read HTML string.
- **Mounting StaticFiles at `/`:** This would shadow ALL API routes. Mount at `/static` instead and serve the landing page via an explicit `@app.get("/")` route.
- **Separate frontend deployment:** For a simple landing page, a separate Vercel/Netlify deployment adds complexity. Keep it in the same FastAPI app since it's deployed on Render already.
- **Swagger UI as the landing page:** `/docs` should not be the first thing developers see. A proper landing page explains the product; docs are linked from it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| API documentation | Custom docs renderer | FastAPI's built-in `/docs` (Swagger UI) + `/redoc` | Auto-generated from Pydantic models, always in sync |
| OpenAPI schema | Manual JSON/YAML | FastAPI auto-generation from type annotations | Zero maintenance, always accurate |
| Request validation docs | Manual parameter lists | Pydantic `Field(description=...)` + `json_schema_extra` | Flows directly into OpenAPI schema |
| Landing page styling | CSS framework build pipeline | Single CSS file or inline styles | This is a minimal marketing page, not a web app |

## Common Pitfalls

### Pitfall 1: StaticFiles Mount Shadowing API Routes
**What goes wrong:** Mounting `StaticFiles` at `/` catches all requests, making API endpoints unreachable.
**Why it happens:** FastAPI/Starlette processes mounts in order; a root mount intercepts everything.
**How to avoid:** Mount at `/static` (not `/`). Serve the landing page via `@app.get("/")`.
**Warning signs:** All API requests return 404 or HTML after adding static files.

### Pitfall 2: Missing Response Models on Endpoints
**What goes wrong:** Swagger UI shows `{}` or "Successful Response" with no schema for response bodies.
**Why it happens:** Endpoints return plain dicts without `response_model=` set.
**How to avoid:** Set `response_model=` on every endpoint decorator. For endpoints returning custom JSONResponse (like the duplicate memory case), use the `responses={}` parameter.
**Warning signs:** Swagger UI "Try it out" works but the response schema section is empty.

### Pitfall 3: Examples Not Appearing in Swagger UI
**What goes wrong:** Examples added to Pydantic models don't show in the "Example Value" tab.
**Why it happens:** Using `Field(example=...)` (singular, deprecated in Pydantic v2) instead of `Field(examples=[...])` (list) or `model_config` with `json_schema_extra`.
**How to avoid:** Use `model_config = {"json_schema_extra": {"examples": [...]}}` on the model class, or `Field(examples=[...])` on individual fields.

### Pitfall 4: Landing Page HTML Inline in Python
**What goes wrong:** A large HTML string embedded in a Python function becomes unmaintainable.
**Why it happens:** Starting with `HTMLResponse("...")` and then the HTML grows.
**How to avoid:** Read the HTML from a file: `Path("app/static/landing.html").read_text()`. Cache it at module level or in app state for performance.

### Pitfall 5: Quickstart Curl Examples That Don't Work
**What goes wrong:** Documentation shows curl commands with placeholder URLs or wrong headers.
**Why it happens:** Copy-paste from development environment, not testing against production.
**How to avoid:** Every curl command in the quickstart should be tested against the actual deployed API. Use `https://memoralabs.onrender.com` as the base URL (or `memoralabs.io` once DNS is set).

## Code Examples

### Adding Field Descriptions to Existing Models
```python
# Current (app/models/memory.py):
text: Annotated[str, Field(min_length=1)]

# Updated:
text: Annotated[str, Field(min_length=1, description="The text content to store as a memory")]
```

### Adding Response Model to Entities Endpoint
```python
# Current (app/routers/memory.py line 423):
@router.get("/memory/{memory_id}/entities")

# Updated — add response schema:
class MemoryEntitiesResponse(BaseModel):
    memory_id: str
    entities: list[dict]
    relations: list[dict]
    total_entities: int
    total_relations: int

@router.get("/memory/{memory_id}/entities", response_model=MemoryEntitiesResponse)
```

### Quickstart Curl Commands (for the guide)
```bash
# 1. Sign up
curl -X POST https://memoralabs.onrender.com/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice", "email": "alice@example.com"}'

# Response: {"tenant_id": "...", "api_key": "ml_abc123...", ...}

# 2. Store a memory
curl -X POST https://memoralabs.onrender.com/v1/memory \
  -H "Authorization: Bearer ml_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"text": "The user prefers dark mode and metric units"}'

# 3. Search memories
curl -X POST https://memoralabs.onrender.com/v1/memory/search \
  -H "Authorization: Bearer ml_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"query": "what display preferences does the user have?"}'
```

### Python SDK-style Example (for quickstart)
```python
import requests

BASE = "https://memoralabs.onrender.com"

# Sign up
r = requests.post(f"{BASE}/v1/auth/signup", json={
    "name": "Alice",
    "email": "alice@example.com"
})
api_key = r.json()["api_key"]
headers = {"Authorization": f"Bearer {api_key}"}

# Store a memory
requests.post(f"{BASE}/v1/memory", headers=headers, json={
    "text": "The user prefers dark mode and metric units"
})

# Search
r = requests.post(f"{BASE}/v1/memory/search", headers=headers, json={
    "query": "display preferences"
})
print(r.json()["results"])
```

## Existing Codebase Analysis

### What's Already Done (Verify Only)
| Feature | Status | Where |
|---------|--------|-------|
| Structured error responses (DX-04) | DONE | `app/main.py` lines 70-127 — three exception handlers covering HTTP, validation, and unhandled errors |
| `memories_used`/`memories_limit` in search (DX-05) | DONE | `app/routers/memory.py` lines 313-314, returned in `MemorySearchResponse` |

### What Needs Work
| Area | Current State | Gap |
|------|---------------|-----|
| OpenAPI metadata | Basic title/description/version | No `openapi_tags`, no `contact`, no `license_info` |
| Pydantic field descriptions | None on any field | All fields show as just type + name in docs |
| Pydantic examples | None on any model | "Example Value" in Swagger UI shows generic defaults |
| Endpoint response docs | No `responses={}` parameter | Error responses (401, 404, 409, 422, 429) not documented |
| Health router tags | No tags set | Appears ungrouped in Swagger UI |
| Landing page | No route at `/` | Returns 404 |
| Quickstart | Does not exist | No getting-started content anywhere |
| `_test/tenant` endpoint | Visible in docs | Should have `include_in_schema=False` |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Field(example=...)` singular | `Field(examples=[...])` list | Pydantic v2 (2023) | Old `example` still works but `examples` is the standard |
| `schema_extra` in `Config` class | `model_config = {"json_schema_extra": {...}}` | Pydantic v2 (2023) | Inner `Config` class deprecated |
| Separate API docs site | Built-in Swagger UI + ReDoc | FastAPI has always had this | No need for external docs tooling |

## Open Questions

1. **Custom domain (memoralabs.io)**
   - What we know: Domain is planned but not confirmed as configured on Render
   - What's unclear: Whether DNS is set up, whether HTTPS is provisioned
   - Recommendation: Use `memoralabs.onrender.com` in quickstart examples; update to `memoralabs.io` when DNS is confirmed

2. **Quickstart hosting location**
   - What we know: Could be at `/quickstart` route, in the OpenAPI description, or as a repo QUICKSTART.md
   - Recommendation: All three. The OpenAPI description gets a brief quickstart. `/quickstart` route serves a styled HTML version. QUICKSTART.md in repo root for GitHub visitors.

3. **Landing page scope**
   - What we know: Needs to explain what MemoraLabs does, who it's for, how to start
   - What's unclear: Design requirements, branding assets
   - Recommendation: Build a clean, minimal HTML page. No external dependencies (no React, no Tailwind CDN). Inline or single-file CSS. Can be enhanced later.

## Sources

### Primary (HIGH confidence)
- FastAPI official docs: [Additional Responses](https://fastapi.tiangolo.com/advanced/additional-responses/) — response examples pattern
- FastAPI official docs: [Schema Extra Example](https://fastapi.tiangolo.com/tutorial/schema-extra-example/) — Pydantic model examples
- FastAPI official docs: [Static Files](https://fastapi.tiangolo.com/tutorial/static-files/) — StaticFiles mount
- Starlette docs: [StaticFiles](https://www.starlette.io/staticfiles/) — `html=True` parameter
- Codebase: `app/main.py`, `app/routers/*.py`, `app/models/*.py` — current state analysis

### Secondary (MEDIUM confidence)
- [Theneo API docs best practices 2025](https://www.theneo.io/blog/api-documentation-best-practices-guide-2025) — quickstart guide structure
- [Fern API docs best practices 2026](https://buildwithfern.com/post/api-documentation-best-practices-guide) — layered documentation approach

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — FastAPI built-in features, verified against official docs
- Architecture: HIGH — patterns verified against FastAPI official documentation
- Pitfalls: HIGH — derived from official docs and known FastAPI/Starlette behavior
- Existing codebase: HIGH — read directly from source files

**Research date:** 2026-03-14
**Valid until:** 2026-04-14 (stable — FastAPI OpenAPI features are mature)
