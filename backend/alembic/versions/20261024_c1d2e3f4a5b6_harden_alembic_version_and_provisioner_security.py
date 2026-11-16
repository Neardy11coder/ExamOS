"""harden_alembic_version_and_provisioner_security

Revision ID: c1d2e3f4a5b6
Revises: a7b8c9d0e1f2
Create Date: 2026-10-24 10:00:00.000000

Task 006B.4 Security Hardening:
1. Make public.alembic_version read-only for examos_app (revoke INSERT, UPDATE, DELETE,
   TRUNCATE, REFERENCES, TRIGGER; grant SELECT).
2. Restrict examos_provisioner at the database boundary via a SECURITY DEFINER
   function public.provision_faculty_account with a safe search_path, fully qualified
   table references, hardcoded FACULTY_ADMIN role, email normalization, and student conflict
   rejection. Revoke direct SELECT, INSERT, UPDATE, DELETE on public.users from examos_provisioner.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Hardening alembic_version for examos_app runtime role
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_migrator') THEN
                GRANT ALL ON TABLE public.alembic_version TO examos_migrator;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_app') THEN
                REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.alembic_version FROM examos_app;
                GRANT SELECT ON TABLE public.alembic_version TO examos_app;
            END IF;
        END $$;
        """
    )

    # 2. Narrowly scoped SECURITY DEFINER function for faculty account bootstrapping
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.provision_faculty_account(
            p_email text,
            p_password_hash text,
            p_display_name text DEFAULT 'Faculty Administrator'
        )
        RETURNS TABLE (
            status text,
            id uuid,
            email varchar(254),
            display_name varchar(200),
            password_hash varchar(256),
            role varchar(20),
            is_active boolean,
            created_at timestamptz,
            updated_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $func$
        DECLARE
            v_normalized_email text;
            v_trimmed_display text;
            v_existing_id uuid;
            v_existing_email varchar(254);
            v_existing_display_name varchar(200);
            v_existing_password_hash varchar(256);
            v_existing_role varchar(20);
            v_existing_is_active boolean;
            v_existing_created_at timestamptz;
            v_existing_updated_at timestamptz;
            v_new_id uuid;
            v_now timestamptz;
        BEGIN
            -- Validate email: non-null and non-empty
            IF p_email IS NULL OR trim(p_email) = '' THEN
                RAISE EXCEPTION 'Email must not be empty.' USING ERRCODE = 'invalid_parameter_value';
            END IF;
            v_normalized_email := lower(trim(p_email));
            IF v_normalized_email = '' THEN
                RAISE EXCEPTION 'Email must not be empty.' USING ERRCODE = 'invalid_parameter_value';
            END IF;

            -- Validate password hash: non-null and non-empty
            IF p_password_hash IS NULL OR trim(p_password_hash) = '' THEN
                RAISE EXCEPTION 'Password hash must not be empty.' USING ERRCODE = 'invalid_parameter_value';
            END IF;

            -- Validate full name / display name: non-null and non-empty
            IF p_display_name IS NULL OR trim(p_display_name) = '' THEN
                RAISE EXCEPTION 'Display name must not be empty.' USING ERRCODE = 'invalid_parameter_value';
            END IF;
            v_trimmed_display := trim(p_display_name);

            -- Check if user already exists (fully qualified public.users table reference)
            SELECT u.id, u.email, u.display_name, u.password_hash, u.role, u.is_active, u.created_at, u.updated_at
            INTO v_existing_id, v_existing_email, v_existing_display_name, v_existing_password_hash, v_existing_role, v_existing_is_active, v_existing_created_at, v_existing_updated_at
            FROM public.users u
            WHERE u.email = v_normalized_email;

            IF FOUND THEN
                IF v_existing_role = 'STUDENT' THEN
                    RAISE EXCEPTION 'Cannot bootstrap faculty account: email % is already registered as a STUDENT.', v_normalized_email;
                ELSIF v_existing_role = 'FACULTY_ADMIN' THEN
                    RETURN QUERY SELECT
                        'EXISTS'::text,
                        v_existing_id,
                        v_existing_email,
                        v_existing_display_name,
                        v_existing_password_hash,
                        v_existing_role,
                        v_existing_is_active,
                        v_existing_created_at,
                        v_existing_updated_at;
                    RETURN;
                ELSE
                    RAISE EXCEPTION 'Account exists with unexpected role: %', v_existing_role;
                END IF;
            END IF;

            v_new_id := gen_random_uuid();
            v_now := clock_timestamp();

            INSERT INTO public.users (
                id,
                email,
                display_name,
                password_hash,
                role,
                is_active,
                created_at,
                updated_at
            ) VALUES (
                v_new_id,
                v_normalized_email,
                v_trimmed_display,
                p_password_hash,
                'FACULTY_ADMIN',
                true,
                v_now,
                v_now
            );

            RETURN QUERY SELECT
                'CREATED'::text,
                v_new_id,
                v_normalized_email::varchar(254),
                v_trimmed_display::varchar(200),
                p_password_hash::varchar(256),
                'FACULTY_ADMIN'::varchar(20),
                true,
                v_now,
                v_now;
            RETURN;
        END;
        $func$;
        """
    )

    # 3. Secure function ownership and access controls
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_migrator') 
               AND pg_has_role(CURRENT_USER, 'examos_migrator', 'MEMBER') THEN
                ALTER FUNCTION public.provision_faculty_account(text, text, text) OWNER TO examos_migrator;
            END IF;
        END $$;

        REVOKE ALL ON FUNCTION public.provision_faculty_account(text, text, text) FROM PUBLIC;

        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_provisioner') THEN
                REVOKE ALL ON TABLE public.users FROM examos_provisioner;
                GRANT EXECUTE ON FUNCTION public.provision_faculty_account(text, text, text) TO examos_provisioner;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_test_runner') THEN
                GRANT EXECUTE ON FUNCTION public.provision_faculty_account(text, text, text) TO examos_test_runner;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_app') THEN
                REVOKE EXECUTE ON FUNCTION public.provision_faculty_account(text, text, text) FROM examos_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Drop SECURITY DEFINER function
    op.execute("DROP FUNCTION IF EXISTS public.provision_faculty_account(text, text, text);")

    # Restore prior grants if roles exist
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_provisioner') THEN
                GRANT SELECT, INSERT ON TABLE public.users TO examos_provisioner;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'examos_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.alembic_version TO examos_app;
            END IF;
        END $$;
        """
    )
