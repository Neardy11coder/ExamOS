"""
FastAPI dependency functions for authentication and authorization.

FR-AUTH-001: authenticate identity for protected requests.
FR-AUTH-005: reject expired tokens with 401.
FR-AUTH-006: require valid auth for every protected operation.
FR-AUTH-008: enforce permission matrix (role check) per route.
API §1.1:    JWT read from HttpOnly cookie; CSRF token validated from header.
"""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    JWT_COOKIE_NAME,
    decode_access_token,
)
from app.db.session import get_db
from app.models.user import User


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get_user_from_token(token: str, db: Session) -> User:
    """
    Decode *token*, look up the user in *db*, and return the User row.
    Raises HTTP 401 on any failure (missing, expired, invalid, deactivated).
    """
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": {"code": "UNAUTHENTICATED", "message": "Not authenticated."}},
    )
    try:
        payload = decode_access_token(token)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exc
    except jwt.PyJWTError:
        raise credentials_exc

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise credentials_exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exc

    return user


# ---------------------------------------------------------------------------
# Public auth dependency
# ---------------------------------------------------------------------------

def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Cookie(alias=JWT_COOKIE_NAME)] = None,
) -> User:
    """
    FastAPI dependency — returns the authenticated User or raises HTTP 401.
    Reads the JWT from the HttpOnly access cookie.
    """
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "UNAUTHENTICATED", "message": "Not authenticated."}},
        )
    return _get_user_from_token(token, db)


# ---------------------------------------------------------------------------
# Role-specific dependencies
# ---------------------------------------------------------------------------

def require_student(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the authenticated user to have role STUDENT."""
    if current_user.role != "STUDENT":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Students only."}},
        )
    return current_user


def require_faculty(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the authenticated user to have role FACULTY_ADMIN."""
    if current_user.role != "FACULTY_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Faculty access only."}},
        )
    return current_user


# ---------------------------------------------------------------------------
# CSRF validation dependency
# ---------------------------------------------------------------------------

def validate_csrf(
    csrf_header: Annotated[str | None, Header(alias=CSRF_HEADER_NAME)] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=CSRF_COOKIE_NAME)] = None,
) -> None:
    """
    Validate that the CSRF token in the X-CSRF-Token header matches the
    value in the non-HttpOnly CSRF cookie.  Only active when CSRF_ENABLED=true.

    Uses secrets.compare_digest-style comparison via == on constant-time strings;
    both values are random 64-char hex so length comparison is implicit.
    """
    if not settings.CSRF_ENABLED:
        return
    if not csrf_header or not csrf_cookie:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "CSRF_MISSING", "message": "CSRF token missing."}},
        )
    import hmac
    if not hmac.compare_digest(csrf_header, csrf_cookie):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "CSRF_INVALID", "message": "CSRF token mismatch."}},
        )
