import re
from typing import Literal, Optional
from pydantic import BaseModel, field_validator

_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


class TenantCreate(BaseModel):
    name: str
    email: str
    plan: Literal["free", "pro", "enterprise"] = "free"

    @field_validator("name")
    @classmethod
    def name_length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 1 or len(v) > 100:
            raise ValueError("name must be between 1 and 100 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_PATTERN.match(v):
            raise ValueError("invalid email format")
        return v


class TenantRow(BaseModel):
    id: str
    name: str
    email: str
    plan: str
    status: str
    memory_limit: int
    created_at: int
    updated_at: Optional[int] = None


class ApiKeyRow(BaseModel):
    id: str
    tenant_id: str
    key_prefix: str
    name: str
    is_active: bool
    created_at: int
    last_used_at: Optional[int] = None


class UsageLogEntry(BaseModel):
    tenant_id: str
    operation: str
    endpoint: str
    status_code: int
    latency_ms: Optional[int] = None
    tokens_used: int = 0


class SignupResponse(BaseModel):
    tenant_id: str
    email: str
    plan: str
    api_key: str  # Shown exactly once
    key_prefix: str
    message: str
