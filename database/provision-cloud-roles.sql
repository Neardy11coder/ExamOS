-- ============================================================================
-- ExamOS M8 — Script A: Cloud Database Roles & Schema Provisioning
-- Target: Neon PostgreSQL 16.16 (AWS Singapore, database: neondb)
-- Role executing this script: neondb_owner (Administrative Super-Role)
-- Mode: Transactional & Idempotent (BEGIN ... COMMIT)
-- ============================================================================

BEGIN;

-- ----------------------------------------------------------------------------
-- STEP 1: Preflight Identity Assertions
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    IF session_user <> 'neondb_owner' OR current_user <> 'neondb_owner' THEN
        RAISE EXCEPTION 'Script A must be executed by "neondb_owner". Current session="%", current="%".',
            session_user, current_user;
    END IF;

    IF current_database() <> 'neondb' THEN
        RAISE EXCEPTION 'Script A must be executed against database "neondb". Current database="%".',
            current_database();
    END IF;

    RAISE NOTICE 'Step 1: Preflight verified login identity "neondb_owner" on database "neondb".';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 2: Create Core Login Roles
-- ----------------------------------------------------------------------------
DO $$
BEGIN
    -- 1. examos_migrator (Dedicated migration role)
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'examos_migrator') THEN
        CREATE ROLE examos_migrator WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS;
        RAISE NOTICE 'Created role: examos_migrator';
    ELSE
        ALTER ROLE examos_migrator WITH
            LOGIN
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
        RAISE NOTICE 'Hardened existing role: examos_migrator';
    END IF;

    -- 2. examos_app (Runtime application role)
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'examos_app') THEN
        CREATE ROLE examos_app WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS;
        RAISE NOTICE 'Created role: examos_app';
    ELSE
        ALTER ROLE examos_app WITH
            LOGIN
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
        RAISE NOTICE 'Hardened existing role: examos_app';
    END IF;

    -- 3. examos_provisioner (Isolated faculty bootstrapping role)
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'examos_provisioner') THEN
        CREATE ROLE examos_provisioner WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT
            NOREPLICATION
            NOBYPASSRLS;
        RAISE NOTICE 'Created role: examos_provisioner';
    ELSE
        ALTER ROLE examos_provisioner WITH
            LOGIN
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
        RAISE NOTICE 'Hardened existing role: examos_provisioner';
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- STEP 3: Explicit Database CONNECT Grants
-- ----------------------------------------------------------------------------
GRANT CONNECT ON DATABASE neondb TO examos_migrator, examos_app, examos_provisioner;

DO $$
BEGIN
    RAISE NOTICE 'Step 3: Explicit database CONNECT granted to all three functional roles.';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 4: Membership Management & Two-Way Graph Audit
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    v_mig_id oid;
    v_app_id oid;
    v_prv_id oid;
    v_own_id oid;
    v_count integer;
    v_count_a integer;
    v_count_b integer;
    r record;
BEGIN
    SELECT oid INTO v_mig_id FROM pg_roles WHERE rolname = 'examos_migrator';
    SELECT oid INTO v_app_id FROM pg_roles WHERE rolname = 'examos_app';
    SELECT oid INTO v_prv_id FROM pg_roles WHERE rolname = 'examos_provisioner';
    SELECT oid INTO v_own_id FROM pg_roles WHERE rolname = 'neondb_owner';

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

    -- Pre-grant inbound for examos_migrator: 1 on fresh run (Record A), 2 on rerun (Record A + Record B)
    SELECT count(*) INTO v_count FROM pg_auth_members WHERE roleid = v_mig_id;
    IF v_count NOT IN (1, 2) THEN
        RAISE EXCEPTION 'Membership violation: examos_migrator has % member rows prior to grant (expected 1 or 2).', v_count;
    END IF;

    -- Record A (automatic creator-admin) must be present
    SELECT count(*) INTO v_count_a
    FROM pg_auth_members m
    JOIN pg_roles mem ON m.member = mem.oid
    WHERE m.roleid = v_mig_id
      AND mem.rolname = 'neondb_owner'
      AND m.admin_option = true
      AND m.inherit_option = false
      AND m.set_option = false;

    IF v_count_a <> 1 THEN
        RAISE EXCEPTION 'Pre-grant violation: automatic creator-admin record for examos_migrator missing or invalid.';
    END IF;

    -- On rerun (count = 2), Record B (explicit operational grant) must be present
    IF v_count = 2 THEN
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
            RAISE EXCEPTION 'Pre-grant rerun violation: explicit operational record for examos_migrator missing or invalid.';
        END IF;
    END IF;
END $$;

-- Explicitly establish operational membership: neondb_owner -> examos_migrator with SET TRUE, INHERIT FALSE, ADMIN FALSE
GRANT examos_migrator TO neondb_owner WITH ADMIN FALSE, INHERIT FALSE, SET TRUE;

DO $$
DECLARE
    v_mig_id oid;
    v_count integer;
    v_count_a integer;
    v_count_b integer;
BEGIN
    SELECT oid INTO v_mig_id FROM pg_roles WHERE rolname = 'examos_migrator';

    -- Post-grant audit: examos_migrator must have precisely the 2 expected records
    SELECT count(*) INTO v_count FROM pg_auth_members WHERE roleid = v_mig_id;
    IF v_count <> 2 THEN
        RAISE EXCEPTION 'Post-grant violation: examos_migrator has % members (expected exactly 2).', v_count;
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
        RAISE EXCEPTION 'Post-grant violation: automatic creator-admin record for examos_migrator missing or invalid.';
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
        RAISE EXCEPTION 'Post-grant violation: explicit operational record (SET TRUE, ADMIN FALSE, INHERIT FALSE, grantor=neondb_owner) missing or invalid.';
    END IF;

    RAISE NOTICE 'Step 4: Two-way role membership audit passed (creator-admin and explicit operational edges verified).';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 5: Schema Ownership & Creation
-- ----------------------------------------------------------------------------
-- Public schema: Preserve existing owner (neondb_owner), grant USAGE and CREATE to examos_migrator
GRANT USAGE, CREATE ON SCHEMA public TO examos_migrator;
GRANT USAGE ON SCHEMA public TO examos_app, examos_provisioner;

-- Examos_lab schema: Establish authorization to examos_migrator
DO $$
DECLARE
    v_schema_owner text;
    v_obj_count integer;
    v_unrecognized_count integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'examos_lab') THEN
        CREATE SCHEMA examos_lab AUTHORIZATION examos_migrator;
        RAISE NOTICE 'Created schema "examos_lab" with authorization "examos_migrator".';
    ELSE
        SELECT r.rolname INTO v_schema_owner
        FROM pg_namespace n
        JOIN pg_roles r ON n.nspowner = r.oid
        WHERE n.nspname = 'examos_lab';

        IF v_schema_owner NOT IN ('examos_migrator', 'neondb_owner') THEN
            RAISE EXCEPTION 'Fail-closed: schema "examos_lab" is owned by unrecognized role "%".', v_schema_owner;
        END IF;

        IF v_schema_owner = 'neondb_owner' THEN
            ALTER SCHEMA examos_lab OWNER TO examos_migrator;
            RAISE NOTICE 'Transferred schema "examos_lab" ownership from "neondb_owner" to "examos_migrator".';
        END IF;

        -- Audit existing relations: reject unknown tables
        SELECT count(*) INTO v_obj_count
        FROM pg_class c
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'examos_lab' AND c.relkind IN ('r', 'v', 'm', 'p');

        IF v_obj_count > 0 THEN
            SELECT count(*) INTO v_unrecognized_count
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'examos_lab' 
              AND c.relkind IN ('r', 'v', 'm', 'p')
              AND c.relname NOT IN (
                  'lab_students_no_index',
                  'lab_students_indexed',
                  'lab_enrollments_no_index',
                  'lab_enrollments_indexed'
              );

            IF v_unrecognized_count > 0 THEN
                RAISE EXCEPTION 'Fail-closed: found % unrecognized objects in schema "examos_lab". Aborting.', v_unrecognized_count;
            END IF;
            RAISE NOTICE 'Validated schema "examos_lab" (% recognized benchmark relations).', v_obj_count;
        ELSE
            RAISE NOTICE 'Validated schema "examos_lab" (0 objects).';
        END IF;
    END IF;
END $$;

GRANT USAGE ON SCHEMA examos_lab TO examos_app;

-- ----------------------------------------------------------------------------
-- STEP 6: Switch Role to examos_migrator to Configure Default Privileges
-- ----------------------------------------------------------------------------
SET ROLE examos_migrator;

DO $$
BEGIN
    IF current_user <> 'examos_migrator' THEN
        RAISE EXCEPTION 'Failed to switch role to "examos_migrator" for default privileges. Current user is "%".', current_user;
    END IF;
    RAISE NOTICE 'Step 6: Switched execution role to "examos_migrator" to alter default privileges.';
END $$;

-- Global default privilege revokes for examos_migrator
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator
    REVOKE ALL ON TABLES FROM PUBLIC, examos_app, examos_provisioner;
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator
    REVOKE ALL ON SEQUENCES FROM PUBLIC, examos_app, examos_provisioner;
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, examos_app, examos_provisioner;

-- Schema public default privileges
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC, examos_app, examos_provisioner;
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC, examos_app, examos_provisioner;
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, examos_app, examos_provisioner;

ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO examos_app;

-- Schema examos_lab default privileges
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA examos_lab
    REVOKE ALL ON TABLES FROM PUBLIC, examos_app, examos_provisioner;
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA examos_lab
    REVOKE ALL ON SEQUENCES FROM PUBLIC, examos_app, examos_provisioner;
ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA examos_lab
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC, examos_app, examos_provisioner;

ALTER DEFAULT PRIVILEGES FOR ROLE examos_migrator IN SCHEMA examos_lab
    GRANT SELECT ON TABLES TO examos_app;

-- ----------------------------------------------------------------------------
-- STEP 7: Reset Role to neondb_owner and Verify Role Context
-- ----------------------------------------------------------------------------
RESET ROLE;

DO $$
BEGIN
    IF current_user <> 'neondb_owner' THEN
        RAISE EXCEPTION 'Failed to reset role to "neondb_owner". Current user is "%".', current_user;
    END IF;
    RAISE NOTICE 'Step 7: Reset execution role to "neondb_owner".';
END $$;

-- ----------------------------------------------------------------------------
-- STEP 8: Tightened Default Privilege Catalog Audit (aclexplode)
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
        -- 1. PUBLIC (grantee = 0) must have NO default privileges anywhere
        IF r.grantee = 0 THEN
            RAISE EXCEPTION 'Default ACL leak: PUBLIC has % on objtype % (namespace %).',
                r.privilege_type, r.defaclobjtype, r.defaclnamespace;
        END IF;

        -- 2. examos_provisioner must have NO default privileges anywhere
        IF r.grantee = v_prv_id THEN
            RAISE EXCEPTION 'Default ACL leak: examos_provisioner has % on objtype % (namespace %).',
                r.privilege_type, r.defaclobjtype, r.defaclnamespace;
        END IF;

        -- 3. examos_app audit
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
                RAISE EXCEPTION 'Default ACL leak: examos_app has function privilege % (namespace %).', r.privilege_type, r.defaclobjtype;
            END IF;
        END IF;
    END LOOP;

    RAISE NOTICE 'Step 8: Tightened default privilege catalog audit passed (tables, sequences, functions).';
END $$;

COMMIT;
