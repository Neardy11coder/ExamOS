"""
Operator CLI command to bootstrap a FACULTY_ADMIN account.

M1-AUTH-2 Implementation:
  - Uses PROVISIONER_DATABASE_URL strictly; never falls back to DATABASE_URL
    or MIGRATION_DATABASE_URL.
  - Reads SEED_FACULTY_EMAIL and SEED_FACULTY_PASSWORD from configuration
    (or optional CLI overrides).
  - Idempotent: reports CREATED if account is newly created; reports EXISTS if
    already present as FACULTY_ADMIN (credentials untouched).
  - Rejects promotion if email belongs to an existing STUDENT account.
  - Passwords are never echoed or logged.

Usage:
  python -m app.commands.bootstrap_faculty
"""

from __future__ import annotations

import argparse
import getpass
import sys
from typing import Sequence

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.user import User
from app.services.auth_service import (
    ProvisioningStatus,
    StudentRoleConflictError,
    provision_faculty_account,
)


def get_provisioner_engine(database_url: str):
    """Create a standalone SQLAlchemy engine for the provisioner role."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
    )


def run_bootstrap(
    *,
    db_url: str | None = None,
    email: str | None = None,
    password: str | None = None,
    display_name: str | None = None,
) -> tuple[ProvisioningStatus, User]:
    """
    Programmatic entry point for faculty account bootstrapping.

    Raises:
      RuntimeError: If PROVISIONER_DATABASE_URL is not configured.
      ValueError: If required email or password settings are missing or blank.
      StudentRoleConflictError: If email belongs to an existing student.
    """
    effective_url = db_url or settings.PROVISIONER_DATABASE_URL
    if not effective_url:
        raise RuntimeError(
            "Configuration error: PROVISIONER_DATABASE_URL is not configured. "
            "The faculty bootstrap workflow requires dedicated least-privilege "
            "provisioner credentials and will not fall back to application runtime "
            "or administrator credentials."
        )

    target_email = email or settings.SEED_FACULTY_EMAIL
    if not target_email or not target_email.strip():
        raise ValueError("Configuration error: SEED_FACULTY_EMAIL is not configured or empty.")

    target_password = password or settings.SEED_FACULTY_PASSWORD
    if not target_password:
        raise ValueError("Configuration error: SEED_FACULTY_PASSWORD is not configured or empty.")

    target_display_name = display_name or "Faculty Administrator"

    engine = get_provisioner_engine(effective_url)
    SessionMaker = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with SessionMaker() as session:
        status, user = provision_faculty_account(
            db=session,
            email=target_email,
            password=target_password,
            display_name=target_display_name,
        )
        return status, user


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for operator invocation."""
    parser = argparse.ArgumentParser(
        description="Bootstrap initial ExamOS FACULTY_ADMIN account.",
    )
    parser.add_argument(
        "--db-url",
        dest="db_url",
        default=None,
        help="Database URL to use (defaults to PROVISIONER_DATABASE_URL setting).",
    )
    parser.add_argument(
        "--email",
        dest="email",
        default=None,
        help="Faculty email (defaults to SEED_FACULTY_EMAIL setting).",
    )
    parser.add_argument(
        "--prompt-password",
        dest="prompt_password",
        action="store_true",
        help="Interactively prompt for password without echoing.",
    )
    parser.add_argument(
        "--display-name",
        dest="display_name",
        default=None,
        help="Faculty display name (defaults to 'Faculty Administrator').",
    )

    args = parser.parse_args(argv)

    resolved_password = None
    if args.prompt_password:
        resolved_password = getpass.getpass("Enter faculty password: ")
    elif settings.SEED_FACULTY_PASSWORD:
        resolved_password = settings.SEED_FACULTY_PASSWORD
    else:
        # If seed password is unset, fall back to interactive prompt
        resolved_password = getpass.getpass("SEED_FACULTY_PASSWORD not set. Enter faculty password: ")

    try:
        status, user = run_bootstrap(
            db_url=args.db_url,
            email=args.email,
            password=resolved_password,
            display_name=args.display_name,
        )
    except StudentRoleConflictError as e:
        print(f"[CONFLICT] {e}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as e:
        print(f"[CONFIG ERROR] {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[FATAL] Bootstrap operation failed: {e}", file=sys.stderr)
        return 3

    if status == ProvisioningStatus.CREATED:
        print(
            f"[CREATED] Successfully provisioned FACULTY_ADMIN account for '{user.email}' "
            f"(id: {user.id})."
        )
    elif status == ProvisioningStatus.EXISTS:
        print(
            f"[EXISTS] FACULTY_ADMIN account for '{user.email}' already exists "
            f"(id: {user.id}). Credentials left unchanged."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
