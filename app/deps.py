"""
FastAPI dependency injection for tenant resolution.

Provides two dependencies:
    - get_tenant: Resolves Authorization: Bearer <key> to a tenant dict.
    - get_tenant_conn: Returns an open aiosqlite connection for the resolved tenant.

Both raise HTTP 401 if the key is missing, invalid, or the tenant is inactive.
"""

import hashlib
from typing import Annotated

import aiosqlite
from fastapi import Depends, HTTPException, Request, status

from app.db.system import get_tenant_by_key_hash, update_key_last_used


def _hash_api_key(raw_key: str) -> str:
    """SHA-256 hash a raw API key for lookup against stored key_hash values."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def get_tenant(request: Request) -> dict:
    """FastAPI dependency: resolve Authorization: Bearer <key> to a tenant dict.

    Extracts the Bearer token from the Authorization header, hashes it with
    SHA-256, and looks it up in the system DB via get_tenant_by_key_hash.

    Raises:
        HTTPException(401): If the header is missing, malformed, or the key
            does not resolve to an active tenant.

    Returns:
        The tenant row as a dict (id, name, email, plan, status, memory_limit, ...).
    """
    auth_header: str | None = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raw_key = parts[1].strip()
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    key_hash = _hash_api_key(raw_key)
    tenant = await get_tenant_by_key_hash(request.app.state.system_db, key_hash)

    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fire-and-forget: update last_used_at (non-blocking, best effort)
    try:
        await update_key_last_used(request.app.state.system_db, key_hash)
    except Exception:
        pass  # Never fail auth because of usage tracking

    return tenant


async def get_tenant_conn(
    request: Request,
    tenant: Annotated[dict, Depends(get_tenant)],
) -> aiosqlite.Connection:
    """FastAPI dependency: return an open aiosqlite connection for the resolved tenant.

    Relies on get_tenant to resolve the API key first. Then retrieves (or opens)
    the tenant's connection from the TenantDBManager connection pool.

    Args:
        request: The incoming FastAPI request (provides access to app.state).
        tenant: The resolved tenant dict from get_tenant.

    Returns:
        An open aiosqlite.Connection for the tenant's SQLite database.
    """
    conn: aiosqlite.Connection = await request.app.state.tenant_manager.get_connection(
        tenant["id"]
    )
    return conn
