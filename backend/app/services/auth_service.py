"""
Authentication service: register, authenticate, create tokens.

Business rules:
  FR-AUTH-001  Authenticate from credentials; establish identity.
  FR-AUTH-002  Invalid credentials → generic error (no account-existence disclosure).
  FR-AUTH-004  Passwords stored only as bcrypt hashes.
  FR-AUTH-007  Every account has exactly one role: STUDENT or FACULTY_ADMIN.
  Appendix A OD-01 / A.3 FR-AUTH-010:
               Public registration always inserts STUDENT. Role is never accepted
               from caller input.
  DB §3.1:     email stored lower-case, unique; display_name non-empty.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class DuplicateEmailError(Exception):
    """Raised when the requested email is already registered."""


def register_student(db: Session, data: RegisterRequest) -> User:
    """
    Create a new STUDENT account.

    Raises DuplicateEmailError if the normalized email already exists.
    Role is always forced to STUDENT regardless of any caller-supplied value.
    """
    user = User(
        id=uuid.uuid4(),
        email=data.email,          # already normalized by the schema validator
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        role="STUDENT",            # ALWAYS forced — never from caller input
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateEmailError(data.email)
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class InvalidCredentialsError(Exception):
    """Raised when email/password do not match. Generic; do not reveal cause."""


def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    Look up *email* (already lower-cased) and verify *password*.

    Raises InvalidCredentialsError on any failure — not found, wrong password,
    or deactivated account.  The error is intentionally generic (FR-AUTH-002).
    """
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        # Run a dummy verification to spend constant time and prevent timing attacks
        verify_password(password, "$2b$12$ADsZy1B7evRnT5B25R9QaOkSNafH2cXCzZwfobJDub2nMELdaBaMO")
        raise InvalidCredentialsError()

    if not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()

    if not user.is_active:
        raise InvalidCredentialsError()

    return user


# ---------------------------------------------------------------------------
# Faculty bootstrap (seed command — not a public API path)
# ---------------------------------------------------------------------------

def create_faculty_user(db: Session, email: str, display_name: str, password: str) -> User:
    """
    Create a FACULTY_ADMIN account. Must only be called from a trusted
    operator/seed command, never from a public API route.
    """
    user = User(
        id=uuid.uuid4(),
        email=email.strip().lower(),
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        role="FACULTY_ADMIN",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise DuplicateEmailError(email)
    db.refresh(user)
    return user
