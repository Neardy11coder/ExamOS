"""
Tests for M1-AUTH-2: Faculty Account Provisioning & Invariants.

Verifies:
  1. A missing email produces exactly one FACULTY_ADMIN account and returns CREATED.
  2. Repeating the operation returns EXISTS and leaves the original password hash unchanged.
  3. An existing STUDENT produces a conflict, remains a student, and retains original hash.
  4. Invalid or missing configuration fails safely.
  5. Failures do not leave unintended database changes.
  6. Operator CLI execution paths (CREATED, EXISTS, CONFLICT, CONFIG ERROR).
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.commands.bootstrap_faculty import main as cli_main, run_bootstrap
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.services.auth_service import (
    ProvisioningStatus,
    StudentRoleConflictError,
    authenticate_user,
    provision_faculty_account,
)


class TestFacultyProvisioningService:
    """Core service invariants for provision_faculty_account."""

    def test_missing_email_creates_faculty_admin(self, test_db_session: Session) -> None:
        email = f"faculty_{uuid.uuid4().hex[:8]}@example.com"
        password = "FacultySecret123!"

        status, user = provision_faculty_account(
            db=test_db_session,
            email=email,
            password=password,
            display_name="Dr. Smith",
        )

        assert status == ProvisioningStatus.CREATED
        assert user.email == email
        assert user.role == "FACULTY_ADMIN"
        assert user.display_name == "Dr. Smith"
        assert user.is_active is True
        assert verify_password(password, user.password_hash)

        # Confirm persisted in database
        persisted = test_db_session.query(User).filter(User.email == email).first()
        assert persisted is not None
        assert persisted.id == user.id
        assert persisted.role == "FACULTY_ADMIN"

    def test_idempotent_exists_does_not_modify_password(self, test_db_session: Session) -> None:
        email = f"faculty_{uuid.uuid4().hex[:8]}@example.com"
        original_password = "OriginalPassword1!"

        # First run: CREATED
        status_1, user_1 = provision_faculty_account(
            db=test_db_session,
            email=email,
            password=original_password,
            display_name="Prof. Original",
        )
        assert status_1 == ProvisioningStatus.CREATED
        original_hash = user_1.password_hash
        original_id = user_1.id

        # Second run with different password and display name: EXISTS
        status_2, user_2 = provision_faculty_account(
            db=test_db_session,
            email=email,
            password="AttemptedNewPassword2@",
            display_name="Prof. Renamed",
        )

        assert status_2 == ProvisioningStatus.EXISTS
        assert user_2.id == original_id
        # Password hash must remain completely unchanged
        assert user_2.password_hash == original_hash
        # Original credentials still verify; new ones do not
        assert verify_password(original_password, user_2.password_hash) is True
        assert verify_password("AttemptedNewPassword2@", user_2.password_hash) is False

    def test_existing_student_produces_conflict_and_is_not_promoted(
        self, test_db_session: Session
    ) -> None:
        email = f"student_{uuid.uuid4().hex[:8]}@example.com"
        student_password = "StudentPassword123!"

        # Create student account
        student = User(
            id=uuid.uuid4(),
            email=email,
            display_name="Undergrad Alice",
            password_hash=hash_password(student_password),
            role="STUDENT",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        test_db_session.add(student)
        test_db_session.commit()
        original_student_hash = student.password_hash

        # Attempt to provision faculty with the student's email
        with pytest.raises(StudentRoleConflictError) as exc_info:
            provision_faculty_account(
                db=test_db_session,
                email=email,
                password="FacultyPassword123!",
                display_name="Alice Attempting Faculty",
            )

        assert "STUDENT" in str(exc_info.value)
        assert email in str(exc_info.value)

        # Verify student record was not touched or promoted
        persisted = test_db_session.query(User).filter(User.email == email).one()
        assert persisted.role == "STUDENT"
        assert persisted.display_name == "Undergrad Alice"
        assert persisted.password_hash == original_student_hash
        assert verify_password(student_password, persisted.password_hash)

    def test_email_normalization_case_insensitivity(self, test_db_session: Session) -> None:
        raw_email = f"FACULTY_{uuid.uuid4().hex[:8]}@EXAMPLE.COM"
        normalized = raw_email.strip().lower()

        status_1, user_1 = provision_faculty_account(
            db=test_db_session,
            email=raw_email,
            password="SecurePassword1!",
        )
        assert status_1 == ProvisioningStatus.CREATED
        assert user_1.email == normalized

        # Repeating with lower case matches existing
        status_2, user_2 = provision_faculty_account(
            db=test_db_session,
            email=normalized,
            password="DifferentPassword!",
        )
        assert status_2 == ProvisioningStatus.EXISTS
        assert user_2.id == user_1.id

    def test_invalid_input_validation(self, test_db_session: Session) -> None:
        with pytest.raises(ValueError, match="Email must not be empty"):
            provision_faculty_account(test_db_session, email="   ", password="ValidPass123!")

        with pytest.raises(ValueError, match="Password must not be empty"):
            provision_faculty_account(
                test_db_session, email="valid@example.com", password=""
            )

        with pytest.raises(ValueError, match="Display name must not be empty"):
            provision_faculty_account(
                test_db_session,
                email="valid@example.com",
                password="ValidPass123!",
                display_name="   ",
            )

    def test_provisioned_faculty_can_authenticate(self, test_db_session: Session) -> None:
        email = f"auth_faculty_{uuid.uuid4().hex[:8]}@example.com"
        password = "FacultyAuthPass123!"

        provision_faculty_account(test_db_session, email=email, password=password)

        authenticated = authenticate_user(test_db_session, email=email, password=password)
        assert authenticated is not None
        assert authenticated.role == "FACULTY_ADMIN"


class TestFacultyBootstrapCLI:
    """Tests for the operator CLI command and configuration requirements."""

    def test_fails_closed_when_provisioner_database_url_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "PROVISIONER_DATABASE_URL", None)

        with pytest.raises(RuntimeError, match="PROVISIONER_DATABASE_URL is not configured"):
            run_bootstrap(email="test@examos.local", password="SecretPassword1!")

    def test_cli_main_exit_code_on_missing_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "PROVISIONER_DATABASE_URL", None)
        monkeypatch.setattr(settings, "SEED_FACULTY_PASSWORD", "Secret1!")
        exit_code = cli_main(["--email", "test@examos.local"])
        assert exit_code == 2

    def test_cli_main_created_flow(self, test_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pass test database URL explicitly to CLI (unmasked password)
        test_url = test_db_engine.url.render_as_string(hide_password=False)
        email = f"cli_created_{uuid.uuid4().hex[:8]}@examos.test"
        monkeypatch.setattr(settings, "SEED_FACULTY_PASSWORD", "CLIPassword123!")

        try:
            exit_code = cli_main([
                "--db-url", test_url,
                "--email", email,
                "--display-name", "CLI Faculty",
            ])
            assert exit_code == 0

            # Run again: should return EXISTS with exit code 0
            monkeypatch.setattr(settings, "SEED_FACULTY_PASSWORD", "DifferentPass!")
            exit_code_repeat = cli_main([
                "--db-url", test_url,
                "--email", email,
            ])
            assert exit_code_repeat == 0
        finally:
            with Session(test_db_engine) as session:
                session.query(User).filter(User.email == email).delete()
                session.commit()

    def test_cli_main_conflict_on_student(self, test_db_engine, monkeypatch: pytest.MonkeyPatch) -> None:
        test_url = test_db_engine.url.render_as_string(hide_password=False)
        email = f"cli_student_{uuid.uuid4().hex[:8]}@examos.test"
        monkeypatch.setattr(settings, "SEED_FACULTY_PASSWORD", "FacultyPass!")

        # Create student directly with committed transaction so external engine can see it
        with Session(test_db_engine) as session:
            student = User(
                id=uuid.uuid4(),
                email=email,
                display_name="Student Bob",
                password_hash=hash_password("StudentPass1!"),
                role="STUDENT",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(student)
            session.commit()

        try:
            # Run CLI with student email: should exit with code 1
            exit_code = cli_main([
                "--db-url", test_url,
                "--email", email,
            ])
            assert exit_code == 1
        finally:
            with Session(test_db_engine) as session:
                session.query(User).filter(User.email == email).delete()
                session.commit()
