#!/bin/sh
set -e

# 1. Validate required environment variables
for var in POSTGRES_USER MIGRATOR_DB_USER MIGRATOR_DB_PASSWORD APP_DB_USER APP_DB_PASSWORD TEST_DB_USER TEST_DB_PASSWORD; do
    eval val=\$$var
    if [ -z "$val" ]; then
        echo "ERROR: Required environment variable $var is unset or empty." >&2
        exit 1
    fi
done

echo "Initializing ExamOS databases and role-scoped permissions..."

# 2. Server-level initialization (connect to default examos database as admin)
psql -v ON_ERROR_STOP=1 \
     -v admin_user="$POSTGRES_USER" \
     -v migrator_user="$MIGRATOR_DB_USER" \
     -v migrator_pass="$MIGRATOR_DB_PASSWORD" \
     -v app_user="$APP_DB_USER" \
     -v app_pass="$APP_DB_PASSWORD" \
     -v test_user="$TEST_DB_USER" \
     -v test_pass="$TEST_DB_PASSWORD" \
     --username "$POSTGRES_USER" \
     --dbname "examos" <<-EOSQL

    -- Create migration role with safe identifier (%I) and literal (%L) quoting
    SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'migrator_user', :'migrator_pass')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'migrator_user')\gexec

    -- Create application role with safe identifier (%I) and literal (%L) quoting
    SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'app_user', :'app_pass')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user')\gexec

    -- Create test runner role with safe identifier (%I) and literal (%L) quoting
    SELECT format('CREATE ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'test_user', :'test_pass')
    WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'test_user')\gexec

    -- Create fixed test database owned by admin
    SELECT format('CREATE DATABASE examos_test OWNER %I', :'admin_user')
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'examos_test')\gexec

    -- Revoke public connection privileges from both databases
    REVOKE CONNECT ON DATABASE examos FROM PUBLIC;
    REVOKE CONNECT ON DATABASE examos_test FROM PUBLIC;

    -- Grant database connection strictly to authorized roles
    SELECT format('GRANT CONNECT ON DATABASE examos TO %I', :'migrator_user')\gexec
    SELECT format('GRANT CONNECT ON DATABASE examos TO %I', :'app_user')\gexec
    SELECT format('GRANT CONNECT ON DATABASE examos_test TO %I', :'test_user')\gexec
EOSQL

# 3. Configure development database: examos
psql -v ON_ERROR_STOP=1 \
     -v admin_user="$POSTGRES_USER" \
     -v migrator_user="$MIGRATOR_DB_USER" \
     -v app_user="$APP_DB_USER" \
     --username "$POSTGRES_USER" \
     --dbname "examos" <<-EOSQL

    -- Create isolated lab schema authorized to migrator
    SELECT format('CREATE SCHEMA IF NOT EXISTS examos_lab AUTHORIZATION %I', :'migrator_user')\gexec

    -- Grant schema creation and usage to migrator role
    SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'migrator_user')\gexec
    SELECT format('GRANT USAGE, CREATE ON SCHEMA examos_lab TO %I', :'migrator_user')\gexec

    -- Grant schema usage to runtime app role
    SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user')\gexec
    SELECT format('GRANT USAGE ON SCHEMA examos_lab TO %I', :'app_user')\gexec

    -- Explicitly grant privileges on any existing tables and sequences
    SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', :'migrator_user')\gexec
    SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA examos_lab TO %I', :'migrator_user')\gexec
    SELECT format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO %I', :'migrator_user')\gexec
    SELECT format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA examos_lab TO %I', :'migrator_user')\gexec

    SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'app_user')\gexec
    SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA examos_lab TO %I', :'app_user')\gexec
    SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_user')\gexec
    SELECT format('GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA examos_lab TO %I', :'app_user')\gexec

    -- Configure default privileges for objects created by migrator_user so app_user can read/write them
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'migrator_user', :'app_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'migrator_user', :'app_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'migrator_user', :'app_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'migrator_user', :'app_user')\gexec

    -- Configure default privileges for objects created by admin_user
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO %I', :'admin_user', :'migrator_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT ALL PRIVILEGES ON TABLES TO %I', :'admin_user', :'migrator_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO %I', :'admin_user', :'migrator_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT ALL PRIVILEGES ON SEQUENCES TO %I', :'admin_user', :'migrator_user')\gexec

    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'admin_user', :'app_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I', :'admin_user', :'app_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'admin_user', :'app_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I', :'admin_user', :'app_user')\gexec
EOSQL

# 4. Configure test database: examos_test
psql -v ON_ERROR_STOP=1 \
     -v admin_user="$POSTGRES_USER" \
     -v test_user="$TEST_DB_USER" \
     --username "$POSTGRES_USER" \
     --dbname "examos_test" <<-EOSQL

    -- Create isolated lab schema authorized to test runner
    SELECT format('CREATE SCHEMA IF NOT EXISTS examos_lab AUTHORIZATION %I', :'test_user')\gexec

    -- Grant schema usage and creation to test runner
    SELECT format('GRANT USAGE, CREATE ON SCHEMA public TO %I', :'test_user')\gexec
    SELECT format('GRANT USAGE, CREATE ON SCHEMA examos_lab TO %I', :'test_user')\gexec

    -- Explicitly grant privileges on any existing tables and sequences
    SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', :'test_user')\gexec
    SELECT format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA examos_lab TO %I', :'test_user')\gexec
    SELECT format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO %I', :'test_user')\gexec
    SELECT format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA examos_lab TO %I', :'test_user')\gexec

    -- Configure default privileges for objects created by admin_user
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO %I', :'admin_user', :'test_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT ALL PRIVILEGES ON TABLES TO %I', :'admin_user', :'test_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO %I', :'admin_user', :'test_user')\gexec
    SELECT format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA examos_lab GRANT ALL PRIVILEGES ON SEQUENCES TO %I', :'admin_user', :'test_user')\gexec
EOSQL

echo "ExamOS database initialization completed successfully."
