-- ============================================================================
-- ExamOS M8 — Script B: Post-Migration Least-Privilege Grants & RLS Setup
-- Target: Neon PostgreSQL 16.16 (AWS Singapore, database: neondb)
-- Role executing this script: neondb_owner (switches to examos_migrator)
-- Mode: Transactional & Idempotent (BEGIN ... COMMIT)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- STEP 1: Preflight Assertions (Login Identity, Role Attributes & Membership)
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_sess_user text := session_user;
    v_curr_user text := current_user;
    v_mig_id oid;
    v_app_id oid;
    v_prv_id oid;
    v_own_id oid;
    v_count integer;
    v_count_a integer;
    v_count_b integer;
    r record;
BEGIN
    IF v_sess_user <> 'neondb_owner' OR v_curr_user <> 'neondb_owner' THEN
        RAISE EXCEPTION 'Script B must be initiated by "neondb_owner". Current session="%", current="%".',
            v_sess_user, v_curr_user;
    END IF;

    SELECT oid INTO v_mig_id FROM pg_roles WHERE rolname = 'examos_migrator';
    SELECT oid INTO v_app_id FROM pg_roles WHERE rolname = 'examos_app';
    SELECT oid INTO v_prv_id FROM pg_roles WHERE rolname = 'examos_provisioner';
    SELECT oid INTO v_own_id FROM pg_roles WHERE rolname = 'neondb_owner';

    -- Re-verify role attributes (LOGIN = true, unprivileged)
    FOR r IN (
        SELECT rolname, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolinherit, rolreplication, rolbypassrls
        FROM pg_roles
        WHERE rolname IN ('examos_app', 'examos_migrator', 'examos_provisioner')
    ) LOOP
        IF NOT r.rolcanlogin OR r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolinherit OR r.rolreplication OR r.rolbypassrls THEN
            RAISE EXCEPTION 'Role attribute violation on "%": invalid privileges detected.', r.rolname;
        END IF;
    END LOOP;

    -- Two-way membership audit:
    -- 1. examos_app: outbound must be 0, inbound must be exactly 1 (automatic creator-admin)
    SELECT count(*) INTO v_count FROM pg_auth_members WHERE member = v_app_id;
    IF v_count <> 0 THEN
        RAISE EXCEPTION 'Membership violation: examos_app has % outbound memberships (expected 0).', v_count;
    END IF;

    SELECT count(*) INTO v_count FROM pg_auth_members WHERE roleid = v_app_id;
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'Membership violation: examos_app has % inbound member edges (expected 1).', v_count;
    END IF;

    SELECT m.admin_option, m.inherit_option, m.set_option, mem.rolname AS member_name
    INTO r
    FROM pg_auth_members m
    JOIN pg_roles mem ON m.member = mem.oid
    WHERE m.roleid = v_app_id;

    IF r.member_name <> 'neondb_owner' OR r.admin_option <> true OR r.inherit_option <> false OR r.set_option <> false THEN
        RAISE EXCEPTION 'Membership violation on examos_app: unexpected options (member=%, admin=%, inherit=%, set=%).',
            r.member_name, r.admin_option, r.inherit_option, r.set_option;
    END IF;

    -- 2. examos_provisioner: outbound must be 0, inbound must be exactly 1 (automatic creator-admin)
    SELECT count(*) INTO v_count FROM pg_auth_members WHERE member = v_prv_id;
    IF v_count <> 0 THEN
        RAISE EXCEPTION 'Membership violation: examos_provisioner has % outbound memberships (expected 0).', v_count;
    END IF;

    SELECT count(*) INTO v_count FROM pg_auth_members WHERE roleid = v_prv_id;
    IF v_count <> 1 THEN
        RAISE EXCEPTION 'Membership violation: examos_provisioner has % inbound member edges (expected 1).', v_count;
    END IF;

    SELECT m.admin_option, m.inherit_option, m.set_option, mem.rolname AS member_name
    INTO r
    FROM pg_auth_members m
    JOIN pg_roles mem ON m.member = mem.oid
    WHERE m.roleid = v_prv_id;

    IF r.member_name <> 'neondb_owner' OR r.admin_option <> true OR r.inherit_option <> false OR r.set_option <> false THEN
        RAISE EXCEPTION 'Membership violation on examos_provisioner: unexpected options (member=%, admin=%, inherit=%, set=%).',
            r.member_name, r.admin_option, r.inherit_option, r.set_option;
    END IF;

    -- 3. examos_migrator: outbound must be 0
    SELECT count(*) INTO v_count FROM pg_auth_members WHERE member = v_mig_id;
    IF v_count <> 0 THEN
        RAISE EXCEPTION 'Membership violation: examos_migrator is a member of % parent roles (expected 0).', v_count;
    END IF;

    -- examos_migrator inbound: exactly the 2 expected records (Record A and Record B)
    SELECT count(*) INTO v_count FROM pg_auth_members WHERE roleid = v_mig_id;
    IF v_count <> 2 THEN
        RAISE EXCEPTION 'Membership violation: examos_migrator has % member rows (expected exactly 2).', v_count;
    END IF;

    -- Record A: Automatic creator-admin grant
    SELECT count(*) INTO v_count_a
    FROM pg_auth_members m
    JOIN pg_roles mem ON m.member = mem.oid
    WHERE m.roleid = v_mig_id
      AND mem.rolname = 'neondb_owner'
      AND m.admin_option = true
      AND m.inherit_option = false
      AND m.set_option = false;

    IF v_count_a <> 1 THEN
        RAISE EXCEPTION 'Membership violation: automatic creator-admin record for examos_migrator missing or invalid.';
    END IF;

    -- Record B: Explicit operational grant
    SELECT count(*) INTO v_count_b
    FROM pg_auth_members m
    JOIN pg_roles mem ON m.member = mem.oid
    JOIN pg_roles grt ON m.grantor = grt.oid
    WHERE m.roleid = v_mig_id
      AND mem.rolname = 'neondb_owner'
      AND grt.rolname = 'neondb_owner'
      AND m.admin_option = false
      AND m.inherit_option = false
      AND m.set_option = true;

    IF v_count_b <> 1 THEN
        RAISE EXCEPTION 'Membership violation: explicit operational record (SET TRUE, ADMIN FALSE, INHERIT FALSE, grantor=neondb_owner) missing or invalid.';
    END IF;

    RAISE NOTICE 'Step 1: Login identity, role attributes, and two-way membership preflight passed.';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 2: Preflight Default Privileges in pg_default_acl
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_mig_id oid;
    v_app_id oid;
    v_prv_id oid;
    v_pub_id oid;
    v_lab_id oid;
    r record;
BEGIN
    SELECT oid INTO v_mig_id FROM pg_roles WHERE rolname = 'examos_migrator';
    SELECT oid INTO v_app_id FROM pg_roles WHERE rolname = 'examos_app';
    SELECT oid INTO v_prv_id FROM pg_roles WHERE rolname = 'examos_provisioner';
    SELECT oid INTO v_pub_id FROM pg_namespace WHERE nspname = 'public';
    SELECT oid INTO v_lab_id FROM pg_namespace WHERE nspname = 'examos_lab';

    FOR r IN (
        SELECT 
            d.defaclnamespace,
            d.defaclobjtype,
            a.grantee,
            a.privilege_type
        FROM pg_default_acl d,
        LATERAL aclexplode(d.defaclacl) a
        WHERE d.defaclrole = v_mig_id
    ) LOOP
        IF r.grantee = 0 THEN
            RAISE EXCEPTION 'Default ACL leak: PUBLIC has % on defaclobjtype %.', r.privilege_type, r.defaclobjtype;
        END IF;

        IF r.grantee = v_prv_id THEN
            RAISE EXCEPTION 'Default ACL leak: examos_provisioner has % on defaclobjtype %.', r.privilege_type, r.defaclobjtype;
        END IF;

        IF r.grantee = v_app_id THEN
            -- Tables ('r')
            IF r.defaclobjtype = 'r' THEN
                IF r.defaclnamespace = 0 THEN
                    RAISE EXCEPTION 'Default ACL leak: examos_app has global table privilege %.', r.privilege_type;
                ELSIF r.defaclnamespace = v_pub_id THEN
                    RAISE EXCEPTION 'Default ACL leak: examos_app has public table default privilege %.', r.privilege_type;
                ELSIF r.defaclnamespace = v_lab_id THEN
                    IF r.privilege_type <> 'SELECT' THEN
                        RAISE EXCEPTION 'Default ACL leak: examos_app has non-SELECT table privilege % on examos_lab.', r.privilege_type;
                    END IF;
                ELSE
                    RAISE EXCEPTION 'Default ACL leak: examos_app has table privilege on unexpected namespace %.', r.defaclnamespace;
                END IF;
            END IF;

            -- Sequences ('S')
            IF r.defaclobjtype = 'S' THEN
                IF r.defaclnamespace = 0 THEN
                    RAISE EXCEPTION 'Default ACL leak: examos_app has global sequence privilege %.', r.privilege_type;
                ELSIF r.defaclnamespace = v_pub_id THEN
                    IF r.privilege_type NOT IN ('USAGE', 'SELECT') THEN
                        RAISE EXCEPTION 'Default ACL leak: examos_app has unauthorized sequence privilege % on public.', r.privilege_type;
                    END IF;
                ELSIF r.defaclnamespace = v_lab_id THEN
                    RAISE EXCEPTION 'Default ACL leak: examos_app has sequence privilege % on examos_lab (none permitted).', r.privilege_type;
                ELSE
                    RAISE EXCEPTION 'Default ACL leak: examos_app has sequence privilege on unexpected namespace %.', r.defaclnamespace;
                END IF;
            END IF;

            -- Functions ('f')
            IF r.defaclobjtype = 'f' THEN
                RAISE EXCEPTION 'Default ACL leak: examos_app has default function privilege %.', r.privilege_type;
            END IF;
        END IF;
    END LOOP;

    RAISE NOTICE 'Step 2: Tightened default privileges in pg_default_acl verified.';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 3: Switch Execution Role to Table Owner (examos_migrator)
-- ----------------------------------------------------------------------------
SET ROLE examos_migrator;

DO $$
BEGIN
    IF current_user <> 'examos_migrator' THEN
        RAISE EXCEPTION 'Failed to switch role to "examos_migrator". Current user is "%".', current_user;
    END IF;
    RAISE NOTICE 'Step 3: Successfully switched execution role to "examos_migrator".';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 4: Migration Preflight & Schema Integrity Verification
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_rev text;
    v_missing text;
BEGIN
    -- 1. Verify Alembic Version
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = 'alembic_version') THEN
        RAISE EXCEPTION 'Migration preflight failed: public.alembic_version table does not exist.';
    END IF;

    SELECT version_num INTO v_rev FROM public.alembic_version;
    IF v_rev IS NULL OR v_rev <> 'd1e2f3a4b5c6' THEN
        RAISE EXCEPTION 'Migration preflight failed: unexpected alembic_version "%" (expected head "d1e2f3a4b5c6").', v_rev;
    END IF;

    -- 2. Verify Reconciled Core Application Tables in Schema public
    SELECT string_agg(t, ', ') INTO v_missing
    FROM (
        SELECT unnest(ARRAY[
            'users',
            'topics',
            'questions',
            'question_options',
            'exams',
            'exam_questions',
            'exam_question_options',
            'attempts',
            'attempt_answers',
            'benchmark_runs'
        ]) AS t
    ) s
    WHERE NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = s.t);

    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'Migration preflight failed: missing tables in public: %', v_missing;
    END IF;

    -- 3. Verify Isolated Benchmark Tables in Schema examos_lab
    SELECT string_agg(t, ', ') INTO v_missing
    FROM (
        SELECT unnest(ARRAY[
            'lab_students_no_index',
            'lab_students_indexed',
            'lab_enrollments_no_index',
            'lab_enrollments_indexed'
        ]) AS t
    ) s
    WHERE NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'examos_lab' AND tablename = s.t);

    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'Migration preflight failed: missing tables in examos_lab: %', v_missing;
    END IF;

    RAISE NOTICE 'Step 4: Migration prerequisites and schema integrity verified (revision: %).', v_rev;
END $$;

-- ----------------------------------------------------------------------------
-- STEP 5: Security Definer Function Structural Preflight
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    fn_oid oid;
    fn_owner text;
    fn_secdef boolean;
    fn_args text;
    fn_nargs integer;
    fn_nargdefaults integer;
    fn_variadic oid;
    fn_modes text[];
    fn_names text[];
    fn_types oid[];
    fn_config text[];
    expected_names text[] := ARRAY[
        'p_email', 'p_password_hash', 'p_display_name',
        'status', 'id', 'email', 'display_name', 'role', 'is_active', 'created_at', 'updated_at'
    ];
    expected_modes text[] := ARRAY['i','i','i','t','t','t','t','t','t','t','t'];
    expected_args text := 'p_email text, p_password_hash text, p_display_name text DEFAULT ''Faculty Administrator''::text';
    expected_types oid[];
BEGIN
    fn_oid := to_regprocedure('public.provision_faculty_account(text,text,text)');
    IF fn_oid IS NULL THEN
        RAISE EXCEPTION 'Function preflight failed: public.provision_faculty_account(text,text,text) not found.';
    END IF;

    expected_types := ARRAY[
        'text'::regtype::oid, 'text'::regtype::oid, 'text'::regtype::oid,
        'text'::regtype::oid, 'uuid'::regtype::oid, 'varchar'::regtype::oid,
        'varchar'::regtype::oid, 'varchar'::regtype::oid, 'bool'::regtype::oid,
        'timestamptz'::regtype::oid, 'timestamptz'::regtype::oid
    ];

    SELECT 
        r.rolname, p.prosecdef, p.pronargs, p.pronargdefaults, p.provariadic,
        p.proargmodes::text[], p.proargnames, p.proallargtypes, p.proconfig,
        pg_get_function_arguments(p.oid)
    INTO 
        fn_owner, fn_secdef, fn_nargs, fn_nargdefaults, fn_variadic,
        fn_modes, fn_names, fn_types, fn_config, fn_args
    FROM pg_proc p
    JOIN pg_roles r ON p.proowner = r.oid
    WHERE p.oid = fn_oid;

    -- Assert core function attributes
    IF fn_owner <> 'examos_migrator' THEN
        RAISE EXCEPTION 'Function contract violation: owner is "%", expected "examos_migrator".', fn_owner;
    END IF;
    IF NOT fn_secdef THEN
        RAISE EXCEPTION 'Function contract violation: must be SECURITY DEFINER.';
    END IF;
    IF fn_nargs <> 3 OR fn_nargdefaults <> 1 OR fn_variadic <> 0 THEN
        RAISE EXCEPTION 'Function contract violation: nargs=%, nargdefaults=%, variadic=%.',
            fn_nargs, fn_nargdefaults, fn_variadic;
    END IF;

    -- Assert argument signature, argument modes, names, and types
    IF fn_args <> expected_args THEN
        RAISE EXCEPTION 'Function contract violation: signature "%" does not match "%".', fn_args, expected_args;
    END IF;
    IF fn_modes IS DISTINCT FROM expected_modes THEN
        RAISE EXCEPTION 'Function contract violation: proargmodes % does not match expected.', fn_modes;
    END IF;
    IF fn_names IS DISTINCT FROM expected_names THEN
        RAISE EXCEPTION 'Function contract violation: proargnames % does not match expected.', fn_names;
    END IF;
    IF fn_types IS DISTINCT FROM expected_types THEN
        RAISE EXCEPTION 'Function contract violation: proallargtypes % does not match expected.', fn_types;
    END IF;

    -- Assert password_hash is strictly absent from return columns
    IF 'password_hash' = ANY(fn_names[4:11]) THEN
        RAISE EXCEPTION 'CRITICAL SECURITY VIOLATION: password_hash found in return columns!';
    END IF;

    -- Assert fixed search path
    IF fn_config IS NULL OR NOT ('search_path=pg_catalog, pg_temp' = ANY(fn_config)) THEN
        RAISE EXCEPTION 'Function contract violation: search_path not pg_catalog, pg_temp.';
    END IF;

    RAISE NOTICE 'Step 5: Function structural contract preflight verified.';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 6: Revoke Blanket Permissions on Existing Objects
-- ----------------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, examos_app, examos_provisioner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, examos_app, examos_provisioner;
REVOKE ALL ON ALL TABLES IN SCHEMA examos_lab FROM PUBLIC, examos_app, examos_provisioner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA examos_lab FROM PUBLIC, examos_app, examos_provisioner;
REVOKE ALL ON FUNCTION public.provision_faculty_account(text, text, text) FROM PUBLIC, examos_app;

-- ----------------------------------------------------------------------------
-- STEP 7: Apply Reconciled Least-Privilege Table Grants to examos_app
-- ----------------------------------------------------------------------------
-- 1. users: SELECT, INSERT (Guarded by RLS student insert policy)
GRANT SELECT, INSERT ON TABLE public.users TO examos_app;

-- 2. topics: SELECT (Topic catalog)
GRANT SELECT ON TABLE public.topics TO examos_app;

-- 3. questions: SELECT, INSERT, UPDATE (Faculty question bank management)
GRANT SELECT, INSERT, UPDATE ON TABLE public.questions TO examos_app;

-- 4. question_options: SELECT, INSERT, UPDATE, DELETE (Authoring options)
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.question_options TO examos_app;

-- 5. exams: SELECT, INSERT, UPDATE (Exam lifecycle management)
GRANT SELECT, INSERT, UPDATE ON TABLE public.exams TO examos_app;

-- 6. exam_questions: SELECT, INSERT, UPDATE, DELETE (Published exam question snapshot)
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.exam_questions TO examos_app;

-- 7. exam_question_options: SELECT, INSERT, UPDATE, DELETE (Published exam option snapshot)
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.exam_question_options TO examos_app;

-- 8. attempts: SELECT, INSERT, UPDATE (Student attempt lifecycle and submission)
GRANT SELECT, INSERT, UPDATE ON TABLE public.attempts TO examos_app;

-- 9. attempt_answers: SELECT, INSERT, UPDATE (Student answer saving and revisions)
GRANT SELECT, INSERT, UPDATE ON TABLE public.attempt_answers TO examos_app;

-- 10. benchmark_runs: SELECT, INSERT (Telemetry for Database Performance Lab runs)
GRANT SELECT, INSERT ON TABLE public.benchmark_runs TO examos_app;

-- 11. alembic_version: SELECT ONLY (Read-only migration version check)
GRANT SELECT ON TABLE public.alembic_version TO examos_app;

-- 12. examos_lab tables: SELECT ONLY (Isolated read-only benchmark execution)
GRANT SELECT ON TABLE examos_lab.lab_students_no_index TO examos_app;
GRANT SELECT ON TABLE examos_lab.lab_students_indexed TO examos_app;
GRANT SELECT ON TABLE examos_lab.lab_enrollments_no_index TO examos_app;
GRANT SELECT ON TABLE examos_lab.lab_enrollments_indexed TO examos_app;

-- ----------------------------------------------------------------------------
-- STEP 8: Apply Sequence & Function Privileges
-- ----------------------------------------------------------------------------
-- Sequences: USAGE and SELECT only in schema public (never UPDATE)
-- Note: examos_lab sequences are NOT granted to examos_app (read-only lab execution)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO examos_app;

-- Faculty Bootstrap Function: EXECUTE to examos_provisioner only
GRANT EXECUTE ON FUNCTION public.provision_faculty_account(text, text, text) TO examos_provisioner;

-- ----------------------------------------------------------------------------
-- STEP 9: Row-Level Security Configuration & Verification on public.users
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    pol record;
    known_policies text[] := ARRAY[
        'users_app_select',
        'users_app_insert_base',
        'users_app_insert_student_guard',
        'users_migrator_all'
    ];
BEGIN
    -- 1. Fail closed if any unexpected policy exists on public.users
    FOR pol IN (
        SELECT policyname FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'users'
    ) LOOP
        IF NOT (pol.policyname = ANY(known_policies)) THEN
            RAISE EXCEPTION 'Fail-closed: unexpected RLS policy "%" found on public.users. Aborting.', pol.policyname;
        END IF;
    END LOOP;

    -- 2. Drop existing known policies for clean idempotent recreation
    EXECUTE 'DROP POLICY IF EXISTS users_app_select ON public.users;';
    EXECUTE 'DROP POLICY IF EXISTS users_app_insert_base ON public.users;';
    EXECUTE 'DROP POLICY IF EXISTS users_app_insert_student_guard ON public.users;';
    EXECUTE 'DROP POLICY IF EXISTS users_migrator_all ON public.users;';
END $$;

-- Enable RLS and explicitly ensure NO FORCE on public.users
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY;

-- Policy 1: Permissive SELECT for runtime role (documented staging visibility)
CREATE POLICY users_app_select
ON public.users
FOR SELECT
TO examos_app
USING (true);

-- Policy 2: Permissive Base INSERT for runtime role
CREATE POLICY users_app_insert_base
ON public.users
FOR INSERT
TO examos_app
WITH CHECK (true);

-- Policy 3: RESTRICTIVE Student Insert Guard (Enforces role = 'STUDENT')
CREATE POLICY users_app_insert_student_guard
ON public.users
AS RESTRICTIVE
FOR INSERT
TO examos_app
WITH CHECK (role = 'STUDENT');

-- Verify catalog attributes for public.users
DO $$
DECLARE
    v_rls_enabled boolean;
    v_rls_forced boolean;
BEGIN
    SELECT relrowsecurity, relforcerowsecurity
    INTO v_rls_enabled, v_rls_forced
    FROM pg_class
    WHERE oid = 'public.users'::regclass;

    IF NOT v_rls_enabled THEN
        RAISE EXCEPTION 'RLS verification failed: public.users does not have ROW LEVEL SECURITY enabled.';
    END IF;

    IF v_rls_forced THEN
        RAISE EXCEPTION 'RLS verification failed: public.users has FORCE ROW LEVEL SECURITY enabled (must be disabled).';
    END IF;

    RAISE NOTICE 'Step 9: Row-Level Security policies configured and non-FORCE verified on public.users.';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 10: Reset Execution Role
-- ----------------------------------------------------------------------------
RESET ROLE;

DO $$
BEGIN
    IF current_user <> 'neondb_owner' THEN
        RAISE EXCEPTION 'Failed to reset role to "neondb_owner". Current user is "%".', current_user;
    END IF;
    RAISE NOTICE 'Step 10: Reset execution role to "neondb_owner".';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 11: Final Least-Privilege Verification Post-Check
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    fn_oid oid := to_regprocedure('public.provision_faculty_account(text,text,text)');
    r record;
BEGIN
    -- 1. Verify alembic_version is strictly read-only for examos_app
    IF NOT has_table_privilege('examos_app', 'public.alembic_version', 'SELECT') THEN
        RAISE EXCEPTION 'Post-check failed: examos_app lacks SELECT on alembic_version.';
    END IF;

    IF has_table_privilege('examos_app', 'public.alembic_version', 'INSERT') OR
       has_table_privilege('examos_app', 'public.alembic_version', 'UPDATE') OR
       has_table_privilege('examos_app', 'public.alembic_version', 'DELETE') THEN
        RAISE EXCEPTION 'Post-check failed: examos_app has mutating privileges on alembic_version.';
    END IF;

    -- 2. Verify function execution privileges (PUBLIC: false, examos_app: false, examos_provisioner: true)
    IF has_function_privilege('public', fn_oid, 'EXECUTE') THEN
        RAISE EXCEPTION 'Post-check failed: pseudo-role public has EXECUTE on provision_faculty_account.';
    END IF;

    IF has_function_privilege('examos_app', fn_oid, 'EXECUTE') THEN
        RAISE EXCEPTION 'Post-check failed: examos_app has EXECUTE on provision_faculty_account.';
    END IF;

    IF NOT has_function_privilege('examos_provisioner', fn_oid, 'EXECUTE') THEN
        RAISE EXCEPTION 'Post-check failed: examos_provisioner lacks EXECUTE on provision_faculty_account.';
    END IF;

    -- 3. Verify examos_lab tables: SELECT granted, mutations denied
    IF NOT has_table_privilege('examos_app', 'examos_lab.lab_students_indexed', 'SELECT') THEN
        RAISE EXCEPTION 'Post-check failed: examos_app lacks SELECT on examos_lab.lab_students_indexed.';
    END IF;

    IF has_table_privilege('examos_app', 'examos_lab.lab_students_indexed', 'INSERT') OR
       has_table_privilege('examos_app', 'examos_lab.lab_students_indexed', 'UPDATE') OR
       has_table_privilege('examos_app', 'examos_lab.lab_students_indexed', 'DELETE') THEN
        RAISE EXCEPTION 'Post-check failed: examos_app has mutating privileges on examos_lab benchmark tables.';
    END IF;

    -- 4. Verify examos_lab sequences: examos_app must have NO privileges on any sequences in examos_lab
    FOR r IN (
        SELECT sequence_schema, sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = 'examos_lab'
    ) LOOP
        IF has_sequence_privilege('examos_app', format('%I.%I', r.sequence_schema, r.sequence_name), 'USAGE') OR
           has_sequence_privilege('examos_app', format('%I.%I', r.sequence_schema, r.sequence_name), 'SELECT') OR
           has_sequence_privilege('examos_app', format('%I.%I', r.sequence_schema, r.sequence_name), 'UPDATE') THEN
            RAISE EXCEPTION 'Post-check failed: examos_app has sequence privileges in examos_lab on %.', r.sequence_name;
        END IF;
    END LOOP;

    RAISE NOTICE 'Step 11: Final post-migration privilege verification passed.';
END $$;

COMMIT;
