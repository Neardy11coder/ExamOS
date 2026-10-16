"""
Pydantic DTOs for authentication endpoints.

API contract §2 (POST /auth/register, /auth/login, /auth/logout, /auth/me).

Rules enforced here (server-side check in service, not just schema):
  - RegisterRequest never accepts a 'role' field (Appendix A OD-01, FR-AUTH-007).
  - Password is write-only; never appears in any response model.
  - Email is normalized (stripped, lower-cased) at the schema level.
"""

import uuid
from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Public student self-registration. Role is always forced to STUDENT."""

    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_display_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped


class LoginRequest(BaseModel):
    """Login credentials. Generic error on failure (FR-AUTH-002)."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class UserPublic(BaseModel):
    """Public user profile — never includes password_hash."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    display_name: str
    role: str


class LoginResponse(BaseModel):
    """Login success payload: user profile plus CSRF token for the frontend."""

    model_config = {"from_attributes": False}

    user: UserPublic
    csrf_token: str


class RegisterResponse(UserPublic):
    """201 response after successful registration."""
    pass
