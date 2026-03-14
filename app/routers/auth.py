"""
Auth router — developer registration and API key issuance.

Provides:
    POST /v1/auth/signup — register a new developer account, returns API key exactly once.
"""
import hashlib
import secrets
import uuid

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request

from app.db.system import create_api_key, create_tenant, deactivate_keys_for_tenant
from app.deps import get_tenant
from app.limiter import limiter
from app.models.schemas import KeyRotateResponse, SignupResponse, TenantCreate

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _generate_key(prefix: str = "ml") -> tuple[str, str, str]:
    """Generate API key -> (plaintext, sha256_hash, prefix_for_display).

    Format: ml_<64 hex chars> = 67 chars total, 256 bits of entropy.
    """
    raw = secrets.token_hex(32)
    plaintext = f"{prefix}_{raw}"
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    key_prefix = plaintext[:7]  # "ml_xxxx"
    return plaintext, key_hash, key_prefix


@router.post("/signup", status_code=201, response_model=SignupResponse)
@limiter.limit("5/minute")
async def signup(body: TenantCreate, request: Request):
    """Register a new developer account. Returns API key exactly once."""
    system_db = request.app.state.system_db
    tenant_id = str(uuid.uuid4())

    try:
        await create_tenant(system_db, tenant_id, body.name, body.email, body.plan)
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    plaintext, key_hash, key_prefix = _generate_key()
    key_id = str(uuid.uuid4())
    await create_api_key(system_db, key_id, tenant_id, key_hash, key_prefix)

    # Initialise the tenant's SQLite DB so memory endpoints work immediately after signup.
    await request.app.state.tenant_manager.create_tenant_db(tenant_id)

    return SignupResponse(
        tenant_id=tenant_id,
        email=body.email,
        plan=body.plan,
        api_key=plaintext,
        key_prefix=key_prefix,
        message="Store this API key securely. It will not be shown again.",
    )


@router.post("/keys/rotate", response_model=KeyRotateResponse)
async def rotate_key(request: Request, tenant: dict = Depends(get_tenant)):
    """Rotate API key. Authenticates with current key, returns new key exactly once.

    - Deactivates ALL existing keys for this tenant
    - Generates a new key and stores only the hash
    - Tenant's memories are unaffected (tenant_id stays the same)
    """
    system_db = request.app.state.system_db

    # Deactivate all existing keys for this tenant
    await deactivate_keys_for_tenant(system_db, tenant["id"])

    # Generate and store new key
    plaintext, key_hash, key_prefix = _generate_key()
    key_id = str(uuid.uuid4())
    await create_api_key(system_db, key_id, tenant["id"], key_hash, key_prefix)

    return KeyRotateResponse(
        api_key=plaintext,
        key_prefix=key_prefix,
        message="Previous key has been revoked. Store this new key securely.",
    )
