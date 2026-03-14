import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator

_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


class TenantCreate(BaseModel):
    name: str = Field(description="Developer or organization name (1-100 characters)")
    email: str = Field(description="Developer email address (must be unique)")
    plan: Literal["free", "pro", "enterprise"] = Field(
        "free", description="Subscription plan tier"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"name": "Alice", "email": "alice@example.com", "plan": "free"}
            ]
        }
    }

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
    tenant_id: str = Field(description="Unique identifier for your developer account")
    email: str = Field(description="Email address associated with this account")
    plan: str = Field(description="Active subscription plan tier")
    api_key: str = Field(
        description="Your API key. Store securely — shown exactly once"
    )
    key_prefix: str = Field(
        description="First 7 characters of the key for identification (e.g. ml_xxxx)"
    )
    message: str = Field(description="Reminder to store the API key securely")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "tenant_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "email": "alice@example.com",
                    "plan": "free",
                    "api_key": "ml_4f8e2a1b9c3d5e7f0a2b4c6d8e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f",
                    "key_prefix": "ml_4f8e",
                    "message": "Store this API key securely. It will not be shown again.",
                }
            ]
        }
    }


class KeyRotateResponse(BaseModel):
    api_key: str = Field(
        description="New API key. Store securely — shown exactly once. Previous key is now revoked."
    )
    key_prefix: str = Field(
        description="First 7 characters of the new key for identification (e.g. ml_xxxx)"
    )
    message: str = Field(description="Confirmation that the previous key has been revoked")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "api_key": "ml_9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f",
                    "key_prefix": "ml_9e0f",
                    "message": "Previous key has been revoked. Store this new key securely.",
                }
            ]
        }
    }
