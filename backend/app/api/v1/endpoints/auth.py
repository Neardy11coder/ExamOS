"""
Authentication HTTP routes.

POST /auth/register  — public student self-registration (FR-AUTH-010, Appendix A OD-01)
POST /auth/login     — credential authentication; sets HttpOnly JWT + CSRF cookies
POST /auth/logout    — clears cookies; CSRF-protected (API §2)
GET  /auth/me        — returns the current user's public profile

Cookie design (Arch §6.2, API §1.1):
  - examos_access : HttpOnly, SameSite=Lax, Secure=configurable → JWT
  - examos_csrf   : NOT HttpOnly (JS-readable), SameSite=Lax → CSRF token
State-changing routes (login → clears+sets, logout) require the CSRF check.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, validate_csrf
from app.core.security import (
    CSRF_COOKIE_NAME,
    JWT_COOKIE_NAME,
    create_access_token,
    generate_csrf_token,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserPublic,
)
from app.services.auth_service import (
    DuplicateEmailError,
    InvalidCredentialsError,
    authenticate_user,
    register_student,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

_COOKIE_KWARGS = dict(
    httponly=False,           # overridden per cookie below
    samesite="lax",
    secure=settings.COOKIE_SECURE,
    path="/",
)


def _set_auth_cookies(response: Response, access_token: str, csrf_token: str) -> None:
    """Write the JWT (HttpOnly) and CSRF (JS-readable) cookies onto *response*."""
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=access_token,
        httponly=True,          # JS cannot read the JWT
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
        max_age=settings.AUTH_TOKEN_TTL_MINUTES * 60,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,         # JS must read this to include it as a header
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
        max_age=settings.AUTH_TOKEN_TTL_MINUTES * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    """Delete both auth cookies."""
    response.delete_cookie(key=JWT_COOKIE_NAME, path="/", samesite="lax")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/", samesite="lax")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Public student self-registration",
)
def register(
    data: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> RegisterResponse:
    """
    Create a new STUDENT account.  Role is always STUDENT regardless of any
    value the client might attempt to supply (Appendix A OD-01, FR-AUTH-007).

    Returns 409 on duplicate email without disclosing whether the account exists
    (FR-AUTH-002 generic-error principle applied to registration conflicts).
    """
    try:
        user = register_student(db, data)
    except DuplicateEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "EMAIL_ALREADY_REGISTERED",
                    "message": "Registration could not be completed. Check your details and try again.",
                }
            },
        )
    return RegisterResponse.model_validate(user)


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and issue session cookies",
)
def login(
    data: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    """
    Validate credentials and issue an HttpOnly JWT access cookie and a
    JS-readable CSRF cookie.  Returns a generic 401 on any failure (FR-AUTH-002).
    """
    try:
        user = authenticate_user(db, data.email, data.password)
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Invalid email or password.",
                }
            },
        )

    access_token = create_access_token(str(user.id), user.role)
    csrf_token = generate_csrf_token()
    _set_auth_cookies(response, access_token, csrf_token)

    return LoginResponse(
        user=UserPublic.model_validate(user),
        csrf_token=csrf_token,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear session cookies",
    dependencies=[Depends(get_current_user), Depends(validate_csrf)],
)
def logout(response: Response) -> None:
    """
    Clear the JWT and CSRF cookies.  Requires valid authentication and CSRF token.
    Server-side JWT revocation is not required in v1 (API §2, FR-AUTH-003).
    """
    _clear_auth_cookies(response)


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Return current user's public profile",
)
def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPublic:
    """Return the authenticated user's profile (FR-AUTH-001, API §2 GET /auth/me)."""
    return UserPublic.model_validate(current_user)
