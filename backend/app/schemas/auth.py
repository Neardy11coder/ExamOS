"""
Pydantic DTOs for authentication endpoints.

API contract §2 (POST /auth/register, /auth/login, /auth/logout, /auth/me).

Rules enforced here (server-side check in service, not just schema):
  - RegisterRequest never accepts a 'role' field (Appendix A OD-01, FR-AUTH-007).
  - Password is write-only; never appears in any response model.
  - Email is normalized (stripped, lower-cased) at the schema level.
"""

from typing import Annotated
import uuid

import email_validator
from pydantic import BaseModel, BeforeValidator, Field, WithJsonSchema, field_validator

from app.core.config import settings


def validate_email_address(value: str) -> str:
    """
    Validate and normalize an email address.

    - Strips leading/trailing whitespace and converts to lowercase.
    - Under production configuration (settings.allow_local_email_domains == False):
      Special-use domains like '.local' are rejected per RFC 6762.
    - Under development/testing configuration (settings.allow_local_email_domains == True):
      Local-use domains ending in '.local' (e.g. faculty@examos.local) are permitted,
      while still enforcing full RFC 5322 syntax validation on local-part and hostname labels.
    """
    if not isinstance(value, str):
        raise ValueError("Email must be a string.")

    v = value.strip().lower()
    if not v:
        raise ValueError("Email must not be empty.")
    if len(v) > 320:
        raise ValueError("Email length must not exceed 320 characters.")
    if "@" not in v:
        raise ValueError("An email address must have an @-sign.")

    local_part, domain = v.rsplit("@", 1)
    if not local_part:
        raise ValueError("There must be something before the @-sign.")
    if not domain:
        raise ValueError("There must be something after the @-sign.")

    is_local_domain = domain == "local" or domain.endswith(".local")
    if is_local_domain:
        if not settings.allow_local_email_domains:
            # Let standard email_validator reject special-use domain name as in production
            try:
                email_validator.validate_email(v, check_deliverability=False)
            except email_validator.EmailNotValidError as e:
                raise ValueError(str(e)) from e
            raise ValueError("The domain '.local' is not allowed in production environments.")

        # Local domains permitted in dev/test: validate syntax using synthetic valid TLD
        if domain == "local":
            test_domain = "dummy.org"
        else:
            base = domain[:-6]  # strip '.local'
            if not base or base.startswith(".") or base.endswith(".") or ".." in base:
                raise ValueError("Invalid domain label in local email address.")
            test_domain = f"{base}.org"

        try:
            email_validator.validate_email(
                f"{local_part}@{test_domain}", check_deliverability=False
            )
        except email_validator.EmailNotValidError as e:
            raise ValueError(str(e)) from e
        return v

    try:
        validated = email_validator.validate_email(v, check_deliverability=False)
        return validated.normalized
    except email_validator.EmailNotValidError as e:
        raise ValueError(str(e)) from e


EmailAddress = Annotated[
    str,
    Field(max_length=320),
    BeforeValidator(validate_email_address),
    WithJsonSchema({"type": "string", "format": "email"}),
]

# Backward-compatibility alias
EmailStr = EmailAddress


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """Public student self-registration. Role is always forced to STUDENT."""

    email: EmailAddress
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("display_name", mode="before")
    @classmethod
    def strip_display_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped


class LoginRequest(BaseModel):
    """Login credentials. Generic error on failure (FR-AUTH-002)."""

    email: EmailAddress
    password: str = Field(min_length=1, max_length=128)


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
