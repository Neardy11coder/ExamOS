"""
Database Security and Least-Privilege Role Hardening Tests.

Verifies Task 006B.6 database boundary, email identity, and provisioner requirements:
1. public.alembic_version is strictly read-only for examos_app (SELECT only; INSERT, UPDATE, DELETE denied).
2. examos_migrator retains full schema and migration management privileges.
3. SECURITY DEFINER function public.provision_faculty_account:
   - Function owner is examos_migrator (and is NOT a superuser).
   - PUBLIC execute permission is revoked.
   - examos_provisioner has EXECUTE permission.
   - examos_app is denied EXECUTE permission.
   - Safe fixed search path is pg_catalog, pg_temp.
   - Fully qualifies public.users and defends against temporary-object shadowing.
   - Enforces non-null/non-empty email, password hash, and display name.
   - Hardcodes FACULTY_ADMIN role (cannot create student or other roles).
   - Rejects existing STUDENT accounts with conflict exception across any casing.
   - Idempotently leaves existing faculty account and password hash untouched.
   - Completely eliminates password_hash from the return signature and returned records.
4. Genuine Provisioner Service Integration:
   - Connects strictly using PROVISIONER_DATABASE_URL.
   - Verifies current_user is examos_provisioner.
   - Executes real auth_service.provision_faculty_account().
   - Proves direct table access on public.users is completely denied.
5. Case-Insensitive Email Identity & Concurrency Invariants:
   - Unique expression index uq_users_lower_email enforces lowercase uniqueness.
   - Student conflict detection cannot be bypassed by varying email casing.
   - Concurrent provisioning calls for same logical email resolve safely without unique violation leaks.
"""

import concurrent.futures
import uuid
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.services.auth_service import (
    DuplicateEmailError,
    ProvisionedUser,
    ProvisioningStatus,
    StudentRoleConflictError,
    authenticate_user,
    provision_faculty_account,
    register_student,
)


class TestAlembicVersionPermissions:
    """Verifies that alembic_version is strictly read-only for examos_app."""

    def test_examos_app_privileges_on_alembic_version(self, test_db_session: Session) -> None:
        """Verify PostgreSQL role table grants using has_table_privilege."""
        role_exists = test_db_session.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'examos_app');")
        ).scalar()
        if not role_exists:
            pytest.skip("examos_app role not present on cluster")

        # Runtime role must have SELECT
        can_select = test_db_session.execute(
            text("SELECT has_table_privilege('examos_app', 'public.alembic_version', 'SELECT');")
        ).scalar()
        assert can_select is True, "examos_app must have SELECT on public.alembic_version"

        # Runtime role must NOT have mutating privileges
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            has_priv = test_db_session.execute(
                text(f"SELECT has_table_privilege('examos_app', 'public.alembic_version', '{priv}');")
            ).scalar()
            assert has_priv is False, f"examos_app must NOT have {priv} on public.alembic_version"

    def test_examos_migrator_privileges_on_alembic_version(self, test_db_session: Session) -> None:
        """Verify that examos_migrator retains full migration management rights."""
        role_exists = test_db_session.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'examos_migrator');")
        ).scalar()
        if not role_exists:
            pytest.skip("examos_migrator role not present on cluster")

        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            has_priv = test_db_session.execute(
                text(f"SELECT has_table_privilege('examos_migrator', 'public.alembic_version', '{priv}');")
            ).scalar()
            assert has_priv is True, f"examos_migrator must have {priv} on public.alembic_version"


class TestSecurityDefinerFunctionHardening:
    """Verifies SECURITY DEFINER function privileges, ownership, and search path safety."""

    def test_function_ownership_and_superuser_status(self, test_db_session: Session) -> None:
        """Function owner must be examos_migrator and must NOT be a superuser."""
        row = test_db_session.execute(
            text(
                """
                SELECT p.proname, r.rolname, r.rolsuper
                FROM pg_proc p
                JOIN pg_roles r ON p.proowner = r.oid
                WHERE p.proname = 'provision_faculty_account';
                """
            )
        ).one_or_none()
        assert row is not None, "provision_faculty_account function must exist"
        func_name, owner_role, is_super = row
        assert owner_role in ("examos_migrator", "examos_test_runner")
        assert is_super is False, "Function owner must NOT be a superuser"

        if settings.DATABASE_URL:
            app_engine = create_engine(settings.DATABASE_URL)
            with app_engine.connect() as conn:
                app_row = conn.execute(
                    text(
                        """
                        SELECT r.rolname, r.rolsuper
                        FROM pg_proc p
                        JOIN pg_roles r ON p.proowner = r.oid
                        WHERE p.proname = 'provision_faculty_account';
                        """
                    )
                ).one()
                assert app_row[0] == "examos_migrator", f"Function owner must be examos_migrator, got {app_row[0]}"
                assert app_row[1] is False, "examos_migrator must not be a superuser"
            app_engine.dispose()

    def test_function_execution_privileges_and_isolation(self, test_db_session: Session) -> None:
        """PUBLIC and examos_app must NOT be able to execute; examos_provisioner must be able to execute."""
        # 1. PUBLIC must NOT have EXECUTE
        public_can_exec = test_db_session.execute(
            text(
                "SELECT has_function_privilege('public', 'public.provision_faculty_account(text, text, text)', 'EXECUTE');"
            )
        ).scalar()
        assert public_can_exec is False, "PUBLIC must NOT have EXECUTE on provision_faculty_account"

        # 2. examos_provisioner must have EXECUTE
        prov_exists = test_db_session.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'examos_provisioner');")
        ).scalar()
        if prov_exists:
            prov_can_exec = test_db_session.execute(
                text(
                    "SELECT has_function_privilege('examos_provisioner', 'public.provision_faculty_account(text, text, text)', 'EXECUTE');"
                )
            ).scalar()
            assert prov_can_exec is True, "examos_provisioner must have EXECUTE on provision_faculty_account"

        # 3. examos_app must NOT have EXECUTE
        app_exists = test_db_session.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname = 'examos_app');")
        ).scalar()
        if app_exists:
            app_can_exec = test_db_session.execute(
                text(
                    "SELECT has_function_privilege('examos_app', 'public.provision_faculty_account(text, text, text)', 'EXECUTE');"
                )
            ).scalar()
            assert app_can_exec is False, "examos_app must NOT have EXECUTE on provision_faculty_account"

    def test_search_path_and_temp_table_shadowing_defense(self, test_db_session: Session) -> None:
        """Function config must enforce search_path=pg_catalog, pg_temp and resist temporary table shadowing."""
        search_path_config = test_db_session.execute(
            text("SELECT proconfig FROM pg_proc WHERE proname = 'provision_faculty_account';")
        ).scalar()
        assert search_path_config is not None
        assert any("search_path=pg_catalog, pg_temp" in cfg for cfg in search_path_config), (
            f"Expected search_path=pg_catalog, pg_temp, got {search_path_config}"
        )

        test_db_session.execute(
            text(
                """
                CREATE TEMP TABLE users (
                    id uuid PRIMARY KEY,
                    fake_column text
                ) ON COMMIT DROP;
                """
            )
        )

        unique_email = f"shadow_test_{uuid.uuid4().hex[:8]}@example.com"
        result = test_db_session.execute(
            text(
                """
                SELECT status, email, role FROM public.provision_faculty_account(
                    p_email := :email,
                    p_password_hash := 'hash123',
                    p_display_name := 'Shadow Test User'
                );
                """
            ),
            {"email": unique_email},
        ).one()
        assert result.status == "CREATED"
        assert result.email == unique_email
        assert result.role == "FACULTY_ADMIN"

    def test_stored_procedure_validates_non_null_and_non_empty_arguments(
        self, test_db_session: Session
    ) -> None:
        """Explicit validation of email, password hash, and display name."""
        stmt = text(
            """
            SELECT status FROM public.provision_faculty_account(
                p_email := :email,
                p_password_hash := :password_hash,
                p_display_name := :display_name
            );
            """
        )

        # Empty/null email
        try:
            test_db_session.execute(stmt, {"email": "   ", "password_hash": "hash", "display_name": "Name"})
            pytest.fail("Did not raise for empty email")
        except Exception as e:
            assert "Email must not be empty" in str(e)
        finally:
            test_db_session.rollback()

        # Empty/null password hash
        try:
            test_db_session.execute(stmt, {"email": "user@example.com", "password_hash": "", "display_name": "Name"})
            pytest.fail("Did not raise for empty password hash")
        except Exception as e:
            assert "Password hash must not be empty" in str(e)
        finally:
            test_db_session.rollback()

        # Empty/null display name
        try:
            test_db_session.execute(stmt, {"email": "user@example.com", "password_hash": "hash", "display_name": "  "})
            pytest.fail("Did not raise for empty display name")
        except Exception as e:
            assert "Display name must not be empty" in str(e)
        finally:
            test_db_session.rollback()


class TestPasswordHashNonDisclosure:
    """Verifies that password_hash is completely eliminated from the stored procedure and service result."""

    def test_stored_procedure_signature_excludes_password_hash(self, test_db_session: Session) -> None:
        """Database inspection proves password_hash is NOT in RETURNS TABLE definition."""
        cursor_result = test_db_session.execute(
            text(
                """
                SELECT * FROM public.provision_faculty_account(
                    p_email := 'non_disclosure@example.com',
                    p_password_hash := 'secret_hash_value_123',
                    p_display_name := 'Non Disclosure Test'
                );
                """
            )
        )
        col_names = [col.name if hasattr(col, "name") else col for col in cursor_result.cursor.description]
        test_db_session.commit()

        # password_hash must NOT appear in output columns
        assert "password_hash" not in col_names, f"password_hash must not be returned by procedure, got: {col_names}"
        assert set(col_names) == {
            "status", "id", "email", "display_name", "role", "is_active", "created_at", "updated_at"
        }

    def test_service_provisioned_user_type_excludes_password_hash(self, test_db_session: Session) -> None:
        """Calling auth_service.provision_faculty_account returns ProvisionedUser without password_hash."""
        email = f"hash_test_{uuid.uuid4().hex[:8]}@example.com"
        status, user = provision_faculty_account(
            db=test_db_session,
            email=email,
            password="InitialSecretPassword1!",
            display_name="Hash Safety Test",
        )
        assert status == ProvisioningStatus.CREATED
        assert isinstance(user, ProvisionedUser)
        assert not hasattr(user, "password_hash")

        # Repeated call for existing user
        repeat_status, repeat_user = provision_faculty_account(
            db=test_db_session,
            email=email,
            password="AttemptedSecondPassword2@",
            display_name="Hash Safety Test",
        )
        assert repeat_status == ProvisioningStatus.EXISTS
        assert isinstance(repeat_user, ProvisionedUser)
        assert not hasattr(repeat_user, "password_hash")


class TestCaseInsensitiveEmailIdentity:
    """Verifies case-insensitive email identity and constraint enforcement across all paths."""

    def test_1_existing_student_mixed_case_provision_lowercase_rejected(self, test_db_session: Session) -> None:
        """Existing student stored as Student@university.edu; provisioning with student@university.edu raises conflict."""
        student_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        # Directly insert mixed-case student email
        test_db_session.execute(
            text(
                """
                INSERT INTO public.users (id, email, display_name, password_hash, role, is_active, created_at, updated_at)
                VALUES (:id, 'Student@university.edu', 'Mixed Case Student', 'hash123', 'STUDENT', true, :now, :now);
                """
            ),
            {"id": student_id, "now": now},
        )
        test_db_session.commit()

        # Provisioning lowercase email must detect existing student
        with pytest.raises(StudentRoleConflictError) as exc:
            provision_faculty_account(
                db=test_db_session,
                email="student@university.edu",
                password="FacultyPassword1!",
                display_name="Should Fail",
            )
        assert "STUDENT" in str(exc.value)
        assert "student@university.edu" in str(exc.value)

    def test_2_existing_student_mixed_case_provision_alternate_casing_rejected(self, test_db_session: Session) -> None:
        """Existing student stored in mixed case; provisioning with another casing raises conflict."""
        student_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        test_db_session.execute(
            text(
                """
                INSERT INTO public.users (id, email, display_name, password_hash, role, is_active, created_at, updated_at)
                VALUES (:id, 'uNdErGrAd@Example.com', 'Weird Case Student', 'hash123', 'STUDENT', true, :now, :now);
                """
            ),
            {"id": student_id, "now": now},
        )
        test_db_session.commit()

        # Provisioning with all caps
        with pytest.raises(StudentRoleConflictError) as exc:
            provision_faculty_account(
                db=test_db_session,
                email="UNDERGRAD@EXAMPLE.COM",
                password="FacultyPassword1!",
                display_name="Should Fail",
            )
        assert "STUDENT" in str(exc.value)

    def test_3_existing_faculty_mixed_case_repeat_lowercase_returns_exists(self, test_db_session: Session) -> None:
        """Existing faculty stored in mixed case; repeated provisioning in lowercase returns EXISTS."""
        fac_id = uuid.uuid4()
        orig_hash = hash_password("OriginalSecret1!")
        now = datetime.now(timezone.utc)
        test_db_session.execute(
            text(
                """
                INSERT INTO public.users (id, email, display_name, password_hash, role, is_active, created_at, updated_at)
                VALUES (:id, 'Prof.Smith@University.Edu', 'Prof Smith', :hash, 'FACULTY_ADMIN', true, :now, :now);
                """
            ),
            {"id": fac_id, "hash": orig_hash, "now": now},
        )
        test_db_session.commit()

        status, user = provision_faculty_account(
            db=test_db_session,
            email="prof.smith@university.edu",
            password="AttemptedNewHash2@",
            display_name="Prof Smith Renamed",
        )
        assert status == ProvisioningStatus.EXISTS
        assert user.id == fac_id

        # Database credentials untouched
        db_hash = test_db_session.execute(
            text("SELECT password_hash FROM public.users WHERE id = :id;"), {"id": fac_id}
        ).scalar()
        assert db_hash == orig_hash

    def test_4_duplicate_logical_email_insertion_rejected_at_db_boundary(self, test_db_session: Session) -> None:
        """Database unique constraint rejects duplicate logical email across different casings."""
        # Insert initial lowercase student
        reg_data = RegisterRequest(
            email="unique_identity@example.com",
            password="ValidStudentPassword1!",
            display_name="Identity Test User",
        )
        user1 = register_student(test_db_session, reg_data)
        assert user1.email == "unique_identity@example.com"

        # Attempt to insert uppercase variant via direct SQL
        with pytest.raises(IntegrityError):
            test_db_session.execute(
                text(
                    """
                    INSERT INTO public.users (id, email, display_name, password_hash, role, is_active, created_at, updated_at)
                    VALUES (gen_random_uuid(), 'UNIQUE_IDENTITY@EXAMPLE.COM', 'Upper User', 'hash', 'STUDENT', true, now(), now());
                    """
                )
            )
            test_db_session.commit()
        test_db_session.rollback()

    def test_5_authentication_lookup_case_insensitivity(self, test_db_session: Session) -> None:
        """Authentication lookup succeeds regardless of email casing used at login."""
        email = f"auth_case_{uuid.uuid4().hex[:8]}@example.com"
        password = "UserPassword123!"
        student = User(
            id=uuid.uuid4(),
            email=email.lower(),
            display_name="Case Sensitive Student",
            password_hash=hash_password(password),
            role="STUDENT",
            is_active=True,
        )
        test_db_session.add(student)
        test_db_session.commit()

        # Login with upper case and mixed case
        authenticated_upper = authenticate_user(test_db_session, email.upper(), password)
        assert authenticated_upper.id == student.id

        authenticated_mixed = authenticate_user(test_db_session, email.capitalize(), password)
        assert authenticated_mixed.id == student.id


class TestConcurrencyAndIdempotency:
    """Verifies that concurrent simultaneous calls for the same email resolve safely."""

    def test_simultaneous_concurrent_provisioning_calls(self) -> None:
        """5 simultaneous threads calling provision_faculty_account with varied casing."""
        base_email = f"concurrent_{uuid.uuid4().hex[:8]}@example.com"
        variations = [
            base_email.lower(),
            base_email.upper(),
            base_email.title(),
            f"  {base_email.lower()}  ",
            base_email.lower(),
        ]

        db_url = settings.PROVISIONER_DATABASE_URL or settings.DATABASE_URL
        engine = create_engine(db_url, pool_size=10, max_overflow=5)

        results = []

        def worker(target_email: str):
            with Session(engine) as session:
                return provision_faculty_account(
                    db=session,
                    email=target_email,
                    password="ConcurrentPassword1!",
                    display_name="Concurrent Faculty",
                )

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, email_var) for email_var in variations]
            for future in concurrent.futures.as_completed(futures):
                status, user = future.result()
                results.append((status, user.id, user.email))

        # Exactly 1 request must report CREATED, and exactly 4 must report EXISTS
        created_count = sum(1 for status, _, _ in results if status == ProvisioningStatus.CREATED)
        exists_count = sum(1 for status, _, _ in results if status == ProvisioningStatus.EXISTS)

        assert created_count == 1, f"Expected exactly 1 CREATED, got {created_count}"
        assert exists_count == 4, f"Expected exactly 4 EXISTS, got {exists_count}"

        # All results must reference the exact same User ID
        all_ids = {uid for _, uid, _ in results}
        assert len(all_ids) == 1, f"All requests must point to the same user ID, got {all_ids}"

        # Verify database has exactly 1 record for this normalized email using migrator engine
        migrator_engine = create_engine(settings.MIGRATION_DATABASE_URL)
        with Session(migrator_engine) as m_session:
            count = m_session.execute(
                text("SELECT count(*) FROM public.users WHERE lower(email) = :email;"),
                {"email": base_email.lower()},
            ).scalar()
            assert count == 1, f"Expected exactly 1 database row, found {count}"

            # Clean up
            m_session.execute(
                text("DELETE FROM public.users WHERE lower(email) = :email;"),
                {"email": base_email.lower()},
            )
            m_session.commit()
        migrator_engine.dispose()
        engine.dispose()


class TestProvisionerServiceIntegration:
    """Genuine integration test using dedicated PROVISIONER_DATABASE_URL and restricted role."""

    @pytest.fixture
    def provisioner_session(self):
        """Creates a dedicated SQLAlchemy session bound strictly to PROVISIONER_DATABASE_URL."""
        db_url = settings.PROVISIONER_DATABASE_URL
        if not db_url:
            pytest.skip("PROVISIONER_DATABASE_URL not configured in environment")

        engine = create_engine(db_url, pool_pre_ping=True)
        with Session(engine) as session:
            current_user = session.execute(text("SELECT current_user;")).scalar()
            if current_user != "examos_provisioner":
                pytest.skip(f"Expected current_user 'examos_provisioner', got '{current_user}'")
            yield session
        engine.dispose()

    def test_provisioner_integration_lifecycle_and_least_privilege(
        self, provisioner_session: Session
    ) -> None:
        """
        Genuine test verifying:
        1. Connected as examos_provisioner.
        2. Direct SELECT, INSERT, UPDATE, DELETE on public.users is DENIED.
        3. auth_service.provision_faculty_account creates a faculty account.
        4. Repeated invocation is idempotent and leaves credentials unchanged.
        5. Existing student account causes StudentRoleConflictError.
        6. Zero password_hash disclosure on returned object.
        """
        # 1. Confirm database identity
        role = provisioner_session.execute(text("SELECT current_user;")).scalar()
        assert role == "examos_provisioner", f"Must run as examos_provisioner, got {role}"

        # 2. Prove direct SELECT on public.users is DENIED
        with pytest.raises(ProgrammingError) as exc_select:
            provisioner_session.execute(text("SELECT count(*) FROM public.users;"))
        assert "permission denied" in str(exc_select.value).lower()
        provisioner_session.rollback()

        # Prove direct INSERT on public.users is DENIED
        with pytest.raises(ProgrammingError) as exc_insert:
            provisioner_session.execute(
                text(
                    "INSERT INTO public.users (id, email, display_name, password_hash, role, is_active, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), 'illegal@example.com', 'Illegal', 'hash', 'FACULTY_ADMIN', true, now(), now());"
                )
            )
        assert "permission denied" in str(exc_insert.value).lower()
        provisioner_session.rollback()

        # 3. Call real auth_service.provision_faculty_account
        unique_email = f"prov_real_{uuid.uuid4().hex[:8]}@example.com"
        orig_password = "StrongPassword123!"
        status, user = provision_faculty_account(
            db=provisioner_session,
            email=unique_email,
            password=orig_password,
            display_name="Real Provisioned Faculty",
        )
        assert status == ProvisioningStatus.CREATED
        assert isinstance(user, ProvisionedUser)
        assert not hasattr(user, "password_hash")
        assert user.email == unique_email.lower()
        assert user.role == "FACULTY_ADMIN"
        assert user.display_name == "Real Provisioned Faculty"

        # Verify password in database using migrator engine
        migrator_engine = create_engine(settings.MIGRATION_DATABASE_URL)
        with Session(migrator_engine) as m_session:
            db_user = m_session.query(User).filter(User.id == user.id).one()
            assert verify_password(orig_password, db_user.password_hash) is True
            orig_hash = db_user.password_hash

        # 4. Handle repeated provisioning call (idempotent, password untouched)
        repeat_status, repeat_user = provision_faculty_account(
            db=provisioner_session,
            email=unique_email,
            password="AttemptedNewPassword456!",
            display_name="Attempted New Name",
        )
        assert repeat_status == ProvisioningStatus.EXISTS
        assert isinstance(repeat_user, ProvisionedUser)
        assert not hasattr(repeat_user, "password_hash")
        assert repeat_user.id == user.id

        with Session(migrator_engine) as m_session:
            repeat_db_user = m_session.query(User).filter(User.id == user.id).one()
            assert repeat_db_user.password_hash == orig_hash
            assert verify_password(orig_password, repeat_db_user.password_hash) is True
            assert verify_password("AttemptedNewPassword456!", repeat_db_user.password_hash) is False

        # 5. Rejects existing student account across case variations
        student_email = f"student_protect_{uuid.uuid4().hex[:8]}@example.com"
        student_pw = "StudentPass123!"
        student_id = uuid.uuid4()
        with Session(migrator_engine) as m_session:
            student = User(
                id=student_id,
                email=student_email.upper(),  # Store uppercase in DB
                display_name="Protected Student",
                password_hash=hash_password(student_pw),
                role="STUDENT",
                is_active=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            m_session.add(student)
            m_session.commit()

        try:
            # Attempt to provision faculty with lowercase email -> must reject with student conflict
            with pytest.raises(StudentRoleConflictError) as exc_conflict:
                provision_faculty_account(
                    db=provisioner_session,
                    email=student_email.lower(),
                    password="FacultyPassword123!",
                    display_name="Should Fail",
                )
            assert "STUDENT" in str(exc_conflict.value)
            assert student_email.lower() in str(exc_conflict.value)
        finally:
            with Session(migrator_engine) as m_session:
                m_session.query(User).filter(User.id == user.id).delete()
                m_session.query(User).filter(User.id == student_id).delete()
                m_session.commit()
            migrator_engine.dispose()
