"""
Shared rate limiter instance.

Defined in a standalone module to avoid circular imports between
app.main (which wires the app) and app.routers.* (which use the limiter).

app/main.py imports from here to register the limiter on the FastAPI app.
app/routers/memory.py imports from here to apply @limiter.limit decorators.
"""

import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def get_tenant_key(request: Request) -> str:
    """Rate limit by tenant API key hash (or IP as fallback).

    Uses the first 16 hex chars of the SHA-256 of the Bearer token so we
    never store the raw key in the rate limiter's in-memory store.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
    return get_remote_address(request)


limiter = Limiter(key_func=get_tenant_key)
