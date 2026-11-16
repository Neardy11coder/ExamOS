"""eliminate password hash disclosure and enforce case insensitive email

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-10-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Pre-check for duplicate logical email identities before creating unique index
    op.execute(
        """
        DO $$
        DECLARE
            v_dup_count integer;
            v_dup_emails text;
        BEGIN
            SELECT count(*), string_agg(lower_email, ', ')
            INTO v_dup_count, v_dup_emails
            FROM (
                SELECT lower(email) AS lower_email
                FROM public.users
                GROUP BY lower(email)
                HAVING count(*) > 1
            ) s;

            IF v_dup_count > 0 THEN
                RAISE EXCEPTION 'Cannot apply migration d1e2f3a4b5c6: found % duplicate logical email identities in public.users: %',
                    v_dup_count, v_dup_emails;
            END IF;
        END $$;
        """
    )

    # 2. Canonicalize any existing mixed-case or un-trimmed emails
    op.execute(
        """
        UPDATE public.users
        SET email = lower(trim(email))
        WHERE email <> lower(trim(email));
        """
    )

    # 3. Create case-insensitive unique index on lower(email) to enforce email identity at database level
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_lower_email
        ON public.users (lower(email));
        """
    )

    # 4. Drop old provision_faculty_account function and recreate without password_hash in return type
    # Old signature had: password_hash varchar(256) in RETURNS TABLE
    # New signature removes password_hash completely to eliminate credential disclosure.
    op.execute("DROP FUNCTION IF EXISTS public.provision_faculty_account(text, text, text);")

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

            -- Initial case-insensitive check for existing user
            SELECT u.id, u.email, u.display_name, u.role, u.is_active, u.created_at, u.updated_at
            INTO v_existing_id, v_existing_email, v_existing_display_name, v_existing_role, v_existing_is_active, v_existing_created_at, v_existing_updated_at
            FROM public.users u
            WHERE lower(u.email) = v_normalized_email;

            IF FOUND THEN
                IF v_existing_role = 'STUDENT' THEN
                    RAISE EXCEPTION 'Cannot bootstrap faculty account: email % is already registered as a STUDENT.', v_normalized_email;
                ELSIF v_existing_role = 'FACULTY_ADMIN' THEN
                    RETURN QUERY SELECT
                        'EXISTS'::text,
                        v_existing_id,
                        v_existing_email,
                        v_existing_display_name,
                        v_existing_role,
                        v_existing_is_active,
                        v_existing_created_at,
                        v_existing_updated_at;
                    RETURN;
                ELSE
                    RAISE EXCEPTION 'Account exists with unexpected role: %', v_existing_role;
                END IF;
            END IF;

            -- Concurrency-safe atomic insert with subtransaction savepoint
            BEGIN
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
                    'FACULTY_ADMIN'::varchar(20),
                    true,
                    v_now,
                    v_now;
                RETURN;

            EXCEPTION WHEN unique_violation THEN
                -- A concurrent transaction committed an account with the same logical email
                -- Query again to handle cleanly as an existing account without leaking constraint errors
                SELECT u.id, u.email, u.display_name, u.role, u.is_active, u.created_at, u.updated_at
                INTO v_existing_id, v_existing_email, v_existing_display_name, v_existing_role, v_existing_is_active, v_existing_created_at, v_existing_updated_at
                FROM public.users u
                WHERE lower(u.email) = v_normalized_email;

                IF FOUND THEN
                    IF v_existing_role = 'STUDENT' THEN
                        RAISE EXCEPTION 'Cannot bootstrap faculty account: email % is already registered as a STUDENT.', v_normalized_email;
                    ELSIF v_existing_role = 'FACULTY_ADMIN' THEN
                        RETURN QUERY SELECT
                            'EXISTS'::text,
                            v_existing_id,
                            v_existing_email,
                            v_existing_display_name,
                            v_existing_role,
                            v_existing_is_active,
                            v_existing_created_at,
                            v_existing_updated_at;
                        RETURN;
                    ELSE
                        RAISE EXCEPTION 'Account exists with unexpected role: %', v_existing_role;
                    END IF;
                ELSE
                    RAISE;
                END IF;
            END;
        END;
        $func$;
        """
    )

    # 5. Maintain security definer function ownership and access controls
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
    # 1. Drop case-insensitive unique index
    op.execute("DROP INDEX IF EXISTS public.uq_users_lower_email;")

    # 2. Drop the updated function
    op.execute("DROP FUNCTION IF EXISTS public.provision_faculty_account(text, text, text);")

