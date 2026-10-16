"""
Security helpers: password hashing, JWT generation/validation, CSRF token.

FR-AUTH-004: passwords stored only as salted bcrypt hashes via passlib.
FR-AUTH-005: JWT has a bounded lifetime (AUTH_TOKEN_TTL_MINUTES).
API §1.1:    JWT in HttpOnly cookie; CSRF token required for state-changing requests.
Arch §6.2:  SameSite=Lax, Secure configurable, restricted CORS; CSRF token in header.

Password hashing uses passlib[bcrypt]. JWT is signed with HS256 using APP_SECRET_KEY.
CSRF tokens are random hex strings stored in a second non-HttpOnly cookie so the
frontend JS can read and send them as a request header.
"""

import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash for *plaintext*. Never store the input."""
    return _pwd_context.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True iff *plaintext* matches *hashed*.  Safe to call with any string."""
    return _pwd_context.verify(plaintext, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"
_JWT_COOKIE_NAME = "examos_access"
_CSRF_COOKIE_NAME = "examos_csrf"
_CSRF_HEADER_NAME = "X-CSRF-Token"


def create_access_token(user_id: str, role: str) -> str:
    """
    Return a signed JWT containing *user_id* and *role* claims with an expiry
    equal to AUTH_TOKEN_TTL_MINUTES from now (UTC).
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.AUTH_TOKEN_TTL_MINUTES)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": expire,
    }
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and validate *token*.  Returns the payload dict on success.
    Raises jwt.PyJWTError (subclasses) on any failure (expired, invalid sig, etc.).
    """
    return jwt.decode(token, settings.APP_SECRET_KEY, algorithms=[_ALGORITHM])


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def generate_csrf_token() -> str:
    """Return a 32-byte URL-safe hex CSRF token."""
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Cookie names / header name — exposed for use in endpoints and tests
# ---------------------------------------------------------------------------

JWT_COOKIE_NAME = _JWT_COOKIE_NAME
CSRF_COOKIE_NAME = _CSRF_COOKIE_NAME
CSRF_HEADER_NAME = _CSRF_HEADER_NAME
