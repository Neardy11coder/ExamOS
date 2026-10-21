"""
Test helper functions and client wrappers for ExamOS tests.
"""

from __future__ import annotations

import uuid
from sqlalchemy.orm import Session

from app.core.security import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    JWT_COOKIE_NAME,
    create_access_token,
    generate_csrf_token,
    hash_password,
)
from app.models.user import User


def create_test_user(
    db: Session,
    *,
    role: str = "FACULTY_ADMIN",
    email: str | None = None,
    display_name: str | None = None,
    is_active: bool = True,
) -> User:
    """Creates a user in the test database."""
    unique_suffix = uuid.uuid4().hex[:8]
    user_email = email or f"{role.lower()}_{unique_suffix}@examos.local"
    user_name = display_name or f"Test {role} {unique_suffix}"
    user = User(
        id=uuid.uuid4(),
        email=user_email,
        display_name=user_name,
        password_hash=hash_password("StrongPassword123!"),
        role=role,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def auth_cookies_and_headers(user: User) -> tuple[None, dict[str, str]]:
    """
    Generates auth and CSRF headers for ``user`` to use in TestClient requests.

    Returns ``(None, headers)`` where ``headers`` contains:
    - A ``Cookie:`` header encoding the JWT access token and CSRF cookie, which
      FastAPI/Starlette reads identically to cookie-jar cookies (RFC 6265).
    - The ``X-CSRF-Token`` double-submit header.

    Returning ``None`` for the first element (previously the cookies dict) means
    tests continue to use the same unpacking signature::

        cookies, headers = auth_cookies_and_headers(user)
        client.post(url, cookies=cookies, headers=headers)

    ``cookies=None`` does not trigger the httpx per-request cookie
    DeprecationWarning introduced in httpx 0.27.
    """
    token = create_access_token(str(user.id), user.role)
    csrf_token = generate_csrf_token()
    # Encode cookies into the Cookie: header.  Starlette parses this into
    # request.cookies identically to cookie-jar delivery.
    cookie_header = f"{JWT_COOKIE_NAME}={token}; {CSRF_COOKIE_NAME}={csrf_token}"
    headers = {
        "Cookie": cookie_header,
        CSRF_HEADER_NAME: csrf_token,
    }
    return None, headers
