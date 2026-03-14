# Stack Research

**Domain:** AI memory-as-a-service API platform
**Researched:** 2026-03-14
**Confidence:** HIGH (core framework, libraries) / MEDIUM (deployment constraints, embedding provider)

---

## Context: Building On What Exists

ZimMemory v15 is the foundation. It already runs:
- FastAPI + uvicorn (NOT Flask — ZimMemory switched to FastAPI for async WebSocket support)
- SQLite per-instance with hnswlib for vector search
- Fireworks.ai embeddings (mxbai-embed-large-v1, 1024-dim) + Ollama fallback
- Q-learning router, GraphRAG, temporal decay, TTL, webhooks, rate limiting (WS layer)

The productization task is: wrap this in a multi-tenant SaaS API shell with auth, billing, per-tenant isolation, and a clean public API surface. The project context says "Flask backend" — but the actual codebase uses FastAPI. Recommendation: keep FastAPI. It is a strict upgrade from Flask for an API product (async, built-in OpenAPI docs, Pydantic validation). Flask is listed here for completeness but should not be adopted over the existing FastAPI codebase.

---

## Recommended Stack

### Core Framework

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **FastAPI** | 0.115.x (latest stable) | API framework | Already used in ZimMemory. Native async, auto-generates OpenAPI 3.1 + Swagger UI + ReDoc with zero config. Pydantic v2 built-in for request/response validation. Far superior to Flask for an API-first product. MEDIUM confidence on exact version — PyPI page was inaccessible; Flask 3.1.3 confirmed, FastAPI trail version from training data. |
| **Uvicorn** | 0.41.0 | ASGI server | Production ASGI server. Already used in ZimMemory. Supports HTTP/1.1 + WebSocket. Use with `--workers` for multi-process on Render. HIGH confidence (verified PyPI). |
| **Pydantic** | 2.12.5 | Request/response schemas, data validation | V2 is 5-20x faster than v1. FastAPI depends on it. Defines tenant configs, API request models, embedding response shapes. HIGH confidence (verified PyPI). |
| **Gunicorn** | 25.1.0 | Process manager for Uvicorn workers | `gunicorn -k uvicorn.workers.UvicornWorker` is the standard production pattern for FastAPI on Render. Handles worker restarts, graceful shutdown. HIGH confidence (verified PyPI). |

**Note on Flask:** If Flask is strictly required (legacy code paths, team preference), use Flask 3.1.3 + flask-smorest 0.46.2 for auto OpenAPI docs. But the existing ZimMemory codebase is FastAPI — migrating to Flask would be a step backward.

### Database

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **SQLite** (per-tenant files) | stdlib (Python 3.9+) | Tenant memory storage, metadata | Already proven in ZimMemory. Zero infrastructure cost. Each tenant gets an isolated `.db` file. Works on Render with persistent disk ($7/mo). No separate DB service needed at MVP scale. |
| **SQLAlchemy** | 2.0.48 | ORM / query builder for tenant DBs | Battle-tested. v2.0 has a clean async API. Use for the admin/billing/tenant registry DB (not the per-tenant memory DBs — those stay raw sqlite3 for speed). HIGH confidence (verified PyPI). |
| **Alembic** | 1.18.4 | Schema migrations | Handles the central admin DB migrations. Per-tenant SQLite schemas should be managed with a lightweight internal migration runner (not Alembic — too heavy per-tenant). HIGH confidence (verified PyPI). |
| **hnswlib** | 0.8.0 | In-process vector index (HNSW) | Already embedded in ZimMemory. Pure Python/C++, no external service. Per-tenant HNSW indexes persist as `.bin` files alongside SQLite DBs. Note: last release Dec 2023 — low maintenance activity. If this becomes a concern, evaluate usearch as alternative. MEDIUM confidence (version from PyPI, maintenance concern is observation). |

**What NOT to use for DB (at $0 budget):**
- **PostgreSQL + pgvector**: Better at scale but requires a paid Render Postgres instance ($7+/mo). Defer to Phase 2+ when revenue exists.
- **Pinecone/Weaviate/Qdrant**: Managed vector DBs. Great DX but $20-100+/mo. Unnecessary when hnswlib is already working.
- **Redis as primary store**: Overkill for MVP. Use only if rate limiting requires a persistent backend (Render free tier restarts wipe in-memory state).

### Auth

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Flask-JWT-Extended** | 4.7.1 | API key / JWT auth | If on Flask. Mature, battle-tested, handles access/refresh tokens cleanly. HIGH confidence (verified PyPI). |
| **python-jose** or **PyJWT** | See note | JWT encode/decode for FastAPI | FastAPI has no bundled auth — use PyJWT (pure Python, no C deps) for stateless API key JWT validation. `pip install python-jose[cryptography]` or `pip install PyJWT`. The `cryptography` package (46.0.5) handles the underlying crypto. MEDIUM confidence — both work, convention favors python-jose for FastAPI. |
| **cryptography** | 46.0.5 | Cryptographic primitives | Used by python-jose for RS256/HS256 signing. Also handles API key hashing (bcrypt via `cryptography`). HIGH confidence (verified PyPI). |
| **API Key pattern** | — | Primary auth method | For an API product, API keys (not OAuth flows) are the standard first auth primitive. Keys are hashed (SHA-256 or bcrypt) in the admin DB, never stored in plaintext. JWT wraps the key identity. Devs expect `Authorization: Bearer <api_key>` or `X-API-Key: <key>` headers. |

**What NOT to use:**
- **OAuth2 / Auth0 / Clerk**: Appropriate for user-facing apps, not API-first dev tools. Adds cost and complexity. Build simple API key auth first.
- **Flask-Login / Flask-Security**: Session-based auth. Wrong model for a REST API consumed by machines.

### Rate Limiting

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Flask-Limiter** | 4.1.1 | Per-tenant rate limiting | If on Flask. Supports Redis and in-memory backends. Redis backend survives Render restarts; in-memory does not (fine for MVP if cold-start rate limit resets are acceptable). HIGH confidence (verified PyPI). |
| **slowapi** | 0.1.9 (approx) | Rate limiting for FastAPI | The FastAPI equivalent of Flask-Limiter. Same interface (`limits` library underneath). Use `redis://` backend on Render for persistent rate limit state. MEDIUM confidence on version — PyPI page not checked. |
| **Redis** | 7.3.0 (client) | Rate limit backend storage | Render offers a free Redis instance (limited). Rate limit counters need persistence across restarts for correctness. The `redis-py` 7.3.0 client is verified current. HIGH confidence (verified PyPI). |
| **Limits** | — | Underlying limit parsing library | Used by both Flask-Limiter and slowapi. Handles `"100 per minute"` string parsing. Pulled in automatically. |

**Rate limit tiers to implement:**
- Free tier: 100 req/min, 10K memories/month
- Paid tier: 1000 req/min, unlimited memories
- Enforce at middleware level before hitting business logic.

### Embedding Providers

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Fireworks.ai** (`fireworks-ai` SDK) | 0.19.20 | Primary embedding provider | Already integrated in ZimMemory. `mixedbread-ai/mxbai-embed-large-v1` at 1024-dim. Free tier: 60 req/min. For multi-tenant API, you'll need per-tenant embedding keys or absorb cost centrally. HIGH confidence on existing integration, MEDIUM on free tier scale. |
| **OpenAI** (`openai` SDK) | 2.28.0 | Alternative embedding provider | `text-embedding-3-small` is $0.02/1M tokens. Cheapest quality option if Fireworks.ai rate limits become a bottleneck at scale. OpenAI SDK 2.28.0 verified current. MEDIUM confidence (recommend as fallback, not primary). |
| **Ollama (local)** | — | Embedding fallback / dev mode | `mxbai-embed-large` running locally. Already in ZimMemory as fallback. Use for local dev to avoid hitting API limits. Not viable for production SaaS serving external tenants. |

**Embedding strategy for multi-tenant:**
- One embedding provider account (yours), all tenants use it
- Costs absorbed into your pricing tiers
- Add per-tenant embedding token tracking for billing metrics
- Fireworks.ai free tier (60 req/min) is fine for MVP with queue

### API Documentation

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **FastAPI built-in OpenAPI** | — | Auto-generates OpenAPI 3.1 spec | FastAPI auto-generates `/openapi.json`, `/docs` (Swagger UI), `/redoc` with zero extra libraries. This is a major argument for keeping FastAPI over Flask. HIGH confidence. |
| **flask-smorest** | 0.46.2 | OpenAPI docs if Flask is used | Provides Swagger UI, ReDoc, and RapiDoc auto-generation for Flask via marshmallow schemas. Best option in the Flask ecosystem. HIGH confidence (verified PyPI). |
| **Flasgger** | 0.9.7.1 | Swagger for Flask (avoid) | Last release May 2023. Low maintenance. Use flask-smorest instead. |

### Background Tasks

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **FastAPI BackgroundTasks** | built-in | Lightweight async post-response tasks | For simple fire-and-forget: send webhook after memory store, trigger embedding job. No extra infrastructure. Built into FastAPI. HIGH confidence. |
| **Celery** | 5.6.2 | Distributed task queue | For heavy async work: bulk embedding jobs, scheduled memory decay sweeps, digest generation. Use with Redis broker. Overkill for MVP — add in Phase 2 when embedding queue depth becomes a problem. HIGH confidence (verified PyPI). |
| **APScheduler** | 3.10.x | In-process cron scheduler | For decay sweeps, TTL cleanup, digest generation on a schedule. Lighter than Celery for single-process work. Good for MVP. MEDIUM confidence on exact version. |

### Billing

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Stripe** (`stripe` SDK) | 14.4.1 | Subscription billing | Industry standard. Handles free → paid upgrades, webhook events, per-seat or usage-based pricing. Python SDK 14.4.1 verified current. Start with flat monthly subscriptions, add usage metering later. HIGH confidence (verified PyPI). |
| **Stripe webhooks** | — | Billing event processing | `checkout.session.completed`, `customer.subscription.deleted` events gate API key activation/deactivation. Must verify Stripe signature on every webhook (`stripe.Webhook.construct_event`). |

### Observability

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Sentry** (`sentry-sdk`) | 2.54.0 | Error tracking | Free tier (5K errors/mo). FastAPI + Sentry integration is one `sentry_sdk.init()` call. Catches unhandled exceptions, traces slow requests. Critical for a prod API product. HIGH confidence (verified PyPI). |
| **Python `logging`** | stdlib | Structured application logs | Use stdlib logging with JSON formatter for Render log drain. No extra library needed. Structured logs (JSON) are parseable in Render's log viewer. |
| **Render built-in metrics** | — | CPU/memory/request metrics | Render provides basic metrics for free. Sufficient for MVP. Grafana/Prometheus: defer until paying customers demand it. |

### Development Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| **Ruff** | 0.15.6 | Linting + formatting | Replaces Black + Flake8 in one tool. 100x faster. One config in `pyproject.toml`. HIGH confidence (verified PyPI). |
| **pytest** | 9.0.2 | Test runner | Industry standard. HIGH confidence (verified PyPI). |
| **pytest-flask** | 1.3.0 | Flask test helpers | If on Flask. HIGH confidence (verified PyPI). |
| **python-dotenv** | 1.2.2 | Environment variable management | `.env` files for local dev. `load_dotenv()` at app startup. HIGH confidence (verified PyPI). |
| **tenacity** | 9.1.4 | Retry logic | For embedding API calls, ZimMemory client calls. Wrap Fireworks.ai calls in `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`. HIGH confidence (verified PyPI). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **numpy** | 2.4.3 | Vector math | Already in ZimMemory. Cosine similarity, vector normalization. HIGH confidence (verified PyPI). |
| **requests** | 2.32.5 | HTTP client (sync) | Internal service calls, Stripe API calls in sync contexts. HIGH confidence (verified PyPI). |
| **httpx** | 0.28.1 | HTTP client (async) | For async FastAPI contexts. Use when making outbound HTTP calls inside async route handlers. HIGH confidence (verified PyPI). |
| **flask-cors** | 6.0.2 | CORS headers (Flask only) | If on Flask. For browser SDK consumers. HIGH confidence (verified PyPI). |
| **flask-caching** | 2.3.1 | Response caching (Flask only) | Cache expensive recall queries for seconds. Reduces embedding API calls. HIGH confidence (verified PyPI). |

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| FastAPI | Flask 3.1.3 | ZimMemory is already FastAPI. Flask has no native async, no built-in OpenAPI. Flask-smorest adds docs but it's an extra layer. Switching to Flask would require rewriting working code. |
| FastAPI | Django REST Framework | Django is a monolith framework. MemoraLabs is a focused API product. Django's ORM, admin, sessions, templates are irrelevant weight. |
| SQLite (per-tenant) | PostgreSQL + pgvector | Postgres requires paid Render instance at $7+/mo. SQLite per-tenant is proven (ZimMemory), free, zero operational overhead. Migrate when paying customers justify it. |
| SQLite (per-tenant) | MongoDB | MongoDB Atlas free tier is 512MB shared cluster — fine for metadata, terrible for vector search at any scale. BSON overhead vs. SQLite's direct file I/O. |
| hnswlib | Qdrant/Weaviate | Managed vector DBs have generous free tiers but add network latency to every search. In-process hnswlib is microseconds vs. milliseconds. At MVP scale, this is a 100x perf advantage. |
| Fireworks.ai | Voyage AI / Cohere | Voyage AI embeddings (`voyage-3`) are excellent (MTEB SOTA in 2025) but $0.06/1M tokens. Fireworks.ai free tier is already integrated and working. Evaluate Voyage when you need SOTA retrieval quality. |
| Stripe | LemonSqueezy | LemonSqueezy is simpler but has less programmatic control. Stripe is the industry standard for dev-tool SaaS. |
| Sentry | Datadog / New Relic | Both are paid at non-trivial scale. Sentry free tier (5K events/mo) is sufficient for MVP. |
| Ruff | Black + Flake8 + isort | Three tools vs one. Ruff is strictly better: faster, same coverage, one config. |
| Render | Railway / Fly.io | Railway free tier is generous but less predictable billing. Fly.io requires Docker and more ops. Render is the simplest path for a Python API with persistent disk. Already used for junkos-backend. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Flasgger** | Last release May 2023, low maintenance. Docs generation is hacky YAML-in-docstrings. | flask-smorest (if Flask) or FastAPI built-in |
| **Flask-Security-Too** | Session/cookie auth model. Wrong for API-first products. | API keys + PyJWT |
| **Pinecone / Weaviate / Qdrant managed** | $20-100+/mo. Unnecessary when hnswlib is already working in-process. | hnswlib (existing) |
| **sentence-transformers (local)** | Downloads 400MB+ models, requires torch, 2-4GB RAM on Render. Render free tier has 512MB RAM. | Fireworks.ai embedding API |
| **FastAPI + SQLModel** | SQLModel is maintained by Tiangolo (FastAPI author) but is under-documented and has had API instability. | SQLAlchemy 2.0 directly — more battle-tested |
| **aioredis** | Merged into `redis-py` as of v4.2. Using aioredis separately causes conflicts. | `redis` 7.3.0 (includes async support) |
| **Celery for MVP** | Heavy. Requires Redis broker + separate worker process. Render free tier = 1 process. | FastAPI BackgroundTasks or APScheduler for MVP |
| **GraphQL** | Good for complex client queries, but dev tool APIs are REST-first. GraphQL adds schema complexity before you understand query patterns. | REST with well-designed endpoints |

---

## Stack Patterns by Variant

**If deploying on Render free tier ($0):**
- SQLite + persistent disk ($7/mo disk is the single paid line item — unavoidable if you need data persistence across deploys)
- In-memory rate limiting (accepts reset on restart) OR Redis free tier
- Fireworks.ai free embedding tier (60 req/min)
- Single gunicorn worker (512MB RAM limit)
- FastAPI BackgroundTasks only (no Celery worker process)

**If first paying customer arrives:**
- Add Render PostgreSQL ($7/mo) for tenant registry + billing records
- Migrate per-tenant SQLite to PostgreSQL schemas with pgvector
- Enable Celery worker for embedding queue

**If needing BYOK (bring your own key) embedding support:**
- Accept `X-Embedding-Provider` and `X-Embedding-Key` headers
- Route embedding calls through a provider abstraction layer
- Validate key on first request, cache provider config per tenant

**If building a Python SDK for customers:**
- Use `openai` SDK v2 as design reference (async client, streaming, typed responses)
- Publish to PyPI: `pip install memoralabs`

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| FastAPI | Pydantic 2.x | FastAPI 0.100+ requires Pydantic v2. Do NOT mix with Pydantic v1. |
| Flask 3.1.3 | Flask-JWT-Extended 4.7.1 | Verified Flask 3.0 compat in flask-jwt-extended changelog |
| Flask 3.1.3 | Flask-CORS 6.0.2 | v6.0 was released to fix Flask 3.x compat breaking changes |
| Flask 3.1.3 | pytest-flask 1.3.0 | 1.3.0 specifically fixes Flask 3.0 compat (request_ctx removed) |
| marshmallow 4.x | flask-smorest 0.46.2 | marshmallow 4 has breaking changes from v3. Verify flask-smorest compat before upgrading. |
| redis 7.3.0 | Flask-Limiter 4.1.1 | Flask-Limiter uses `limits` library which uses `redis-py` internally. No separate aioredis needed. |
| numpy 2.4.3 | Python >=3.11 required | numpy 2.x dropped Python 3.10 support. Verify Render Python version. |

---

## Installation

```bash
# Core (FastAPI path — recommended)
pip install fastapi==0.115.x uvicorn[standard]==0.41.0 gunicorn==25.1.0
pip install pydantic==2.12.5 python-dotenv==1.2.2

# Database
pip install sqlalchemy==2.0.48 alembic==1.18.4
# hnswlib and numpy already in ZimMemory requirements

# Auth
pip install python-jose[cryptography] cryptography==46.0.5

# Rate limiting
pip install slowapi redis==7.3.0

# Embeddings
pip install fireworks-ai==0.19.20 openai==2.28.0 tenacity==9.1.4

# Billing
pip install stripe==14.4.1

# Observability
pip install sentry-sdk==2.54.0

# HTTP clients
pip install requests==2.32.5 httpx==0.28.1

# Dev
pip install ruff==0.15.6 pytest==9.0.2

# --- OR: Flask path (if Flask strictly required) ---
pip install flask==3.1.3 gunicorn==25.1.0
pip install flask-smorest==0.46.2 marshmallow==4.2.2
pip install flask-jwt-extended==4.7.1 cryptography==46.0.5
pip install flask-limiter==4.1.1 redis==7.3.0
pip install flask-cors==6.0.2 flask-caching==2.3.1
pip install flask-sqlalchemy==3.1.1 sqlalchemy==2.0.48 alembic==1.18.4
pip install stripe==14.4.1 sentry-sdk==2.54.0
pip install fireworks-ai==0.19.20 tenacity==9.1.4
pip install python-dotenv==1.2.2 ruff==0.15.6 pytest==9.0.2 pytest-flask==1.3.0
```

---

## Sources

- PyPI: `flask` 3.1.3 — https://pypi.org/project/flask/ (verified)
- PyPI: `flask-limiter` 4.1.1 — https://pypi.org/project/flask-limiter/ (verified)
- PyPI: `flask-jwt-extended` 4.7.1 — https://pypi.org/project/flask-jwt-extended/ (verified)
- PyPI: `flask-smorest` 0.46.2 — https://pypi.org/project/flask-smorest/ (verified, OpenAPI auto-gen confirmed)
- PyPI: `marshmallow` 4.2.2 — https://pypi.org/project/marshmallow/ (verified)
- PyPI: `pydantic` 2.12.5 — https://pypi.org/project/pydantic/ (verified)
- PyPI: `sqlalchemy` 2.0.48 — https://pypi.org/project/sqlalchemy/ (verified)
- PyPI: `alembic` 1.18.4 — https://pypi.org/project/alembic/ (verified)
- PyPI: `hnswlib` 0.8.0 — https://pypi.org/project/hnswlib/ (verified, note: last release Dec 2023)
- PyPI: `gunicorn` 25.1.0 — https://pypi.org/project/gunicorn/ (verified)
- PyPI: `uvicorn` 0.41.0 — https://pypi.org/project/uvicorn/ (verified)
- PyPI: `redis` 7.3.0 — https://pypi.org/project/redis/ (verified)
- PyPI: `celery` 5.6.2 — https://pypi.org/project/celery/ (verified)
- PyPI: `stripe` 14.4.1 — https://pypi.org/project/stripe/ (verified)
- PyPI: `sentry-sdk` 2.54.0 — https://pypi.org/project/sentry-sdk/ (verified)
- PyPI: `fireworks-ai` 0.19.20 — https://pypi.org/project/fireworks-ai/ (verified)
- PyPI: `openai` 2.28.0 — https://pypi.org/project/openai/ (verified)
- PyPI: `tenacity` 9.1.4 — https://pypi.org/project/tenacity/ (verified)
- PyPI: `numpy` 2.4.3 — https://pypi.org/project/numpy/ (verified)
- PyPI: `requests` 2.32.5 — https://pypi.org/project/requests/ (verified)
- PyPI: `httpx` 0.28.1 — https://pypi.org/project/httpx/ (verified)
- PyPI: `cryptography` 46.0.5 — https://pypi.org/project/cryptography/ (verified)
- PyPI: `psycopg2-binary` 2.9.11 — https://pypi.org/project/psycopg2-binary/ (verified)
- PyPI: `pgvector` 0.4.2 — https://pypi.org/project/pgvector/ (verified)
- PyPI: `flask-cors` 6.0.2 — https://pypi.org/project/flask-cors/ (verified)
- PyPI: `flask-caching` 2.3.1 — https://pypi.org/project/flask-caching/ (verified)
- PyPI: `flask-sqlalchemy` 3.1.1 — https://pypi.org/project/flask-sqlalchemy/ (verified)
- PyPI: `pytest` 9.0.2 — https://pypi.org/project/pytest/ (verified)
- PyPI: `pytest-flask` 1.3.0 — https://pypi.org/project/pytest-flask/ (verified)
- PyPI: `python-dotenv` 1.2.2 — https://pypi.org/project/python-dotenv/ (verified)
- PyPI: `ruff` 0.15.6 — https://pypi.org/project/ruff/ (verified)
- PyPI: `mem0ai` 1.0.5 — https://pypi.org/project/mem0ai/ (competitor reference)
- FastAPI version: MEDIUM confidence — PyPI page inaccessible during research, version from ZimMemory codebase + training data cross-reference. Verify with `pip index versions fastapi` before pinning.

---
*Stack research for: MemoraLabs — AI memory-as-a-service API*
*Researched: 2026-03-14*
