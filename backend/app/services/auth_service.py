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

from enum import Enum


class ProvisioningStatus(str, Enum):
    """Result of an idempotent faculty account provisioning operation."""
    CREATED = "CREATED"
    EXISTS = "EXISTS"


class StudentRoleConflictError(Exception):
    """
    Raised when attempting to provision a faculty account using an email
    that is already registered to an existing STUDENT account.
    """
    def __init__(self, email: str) -> None:
        super().__init__(
            f"Account with email '{email}' already exists with role 'STUDENT'. "
            "A student account must never be promoted to faculty."
        )
        self.email = email


def provision_faculty_account(
    db: Session,
    email: str,
    password: str,
    display_name: str = "Faculty Administrator",
) -> tuple[ProvisioningStatus, User]:
    """
    Provision a FACULTY_ADMIN account idempotently.

    Invariants:
      1. CREATED: If the email does not exist, create a FACULTY_ADMIN account.
      2. EXISTS: If the email exists as FACULTY_ADMIN, leave unchanged (password
         hash and account data are untouched).
      3. CONFLICT: If the email exists as STUDENT, raise StudentRoleConflictError.
         Students must never be promoted to faculty through bootstrap.
      4. Passwords are never stored or logged in plaintext.
    """
    normalized_email = email.strip().lower()
    if not normalized_email:
        raise ValueError("Email must not be empty.")
    if not password:
        raise ValueError("Password must not be empty.")
    stripped_display_name = display_name.strip()
    if not stripped_display_name:
        raise ValueError("Display name must not be empty.")

    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user is not None:
        if existing_user.role == "STUDENT":
            raise StudentRoleConflictError(normalized_email)
        if existing_user.role == "FACULTY_ADMIN":
            return ProvisioningStatus.EXISTS, existing_user
        raise ValueError(f"Account exists with unexpected role: {existing_user.role}")

    user = User(
        id=uuid.uuid4(),
        email=normalized_email,
        display_name=stripped_display_name,
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
        # Handle race condition if created concurrently
        existing = db.query(User).filter(User.email == normalized_email).first()
        if existing is not None:
            if existing.role == "FACULTY_ADMIN":
                return ProvisioningStatus.EXISTS, existing
            if existing.role == "STUDENT":
                raise StudentRoleConflictError(normalized_email)
        raise DuplicateEmailError(normalized_email)

    db.refresh(user)
    return ProvisioningStatus.CREATED, user


def create_faculty_user(db: Session, email: str, display_name: str, password: str) -> User:
    """
    Legacy wrapper for creating a FACULTY_ADMIN account.
    """
    status, user = provision_faculty_account(
        db=db,
        email=email,
        password=password,
        display_name=display_name,
    )
    return user
