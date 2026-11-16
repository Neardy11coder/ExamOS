"""
Focused test suite for production-safe Alembic connection enforcement.

Verifies:
1. Development with MIGRATION_DATABASE_URL configured -> prefers MIGRATION_DATABASE_URL.
2. Development without MIGRATION_DATABASE_URL -> safely falls back to DATABASE_URL.
3. Production with MIGRATION_DATABASE_URL configured -> uses MIGRATION_DATABASE_URL.
4. Production without MIGRATION_DATABASE_URL -> raises RuntimeError before connecting.
5. Production with 'prod' alias -> raises RuntimeError when MIGRATION_DATABASE_URL is absent.
6. Explicit Alembic -x url=... override -> takes precedence in all environments.
7. Empty or whitespace-only migration URL -> treated as missing and rejected in production.
8. Empty or whitespace-only -x url override -> rejected with clear error.
9. Security: error messages NEVER disclose database credentials, passwords, or connection strings.
10. FastAPI startup independence: MIGRATION_DATABASE_URL is not required for application runtime.
"""
import importlib.util
from pathlib import Path
import pytest
from alembic.config import Config
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_application

# Dynamically import backend/alembic/env.py to access resolve_migration_url
# without colliding with third-party 'alembic' package in site-packages
_env_path = Path(__file__).resolve().parent.parent / "alembic" / "env.py"
_spec = importlib.util.spec_from_file_location("backend_alembic_env", _env_path)
_env_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_env_mod)
resolve_migration_url = _env_mod.resolve_migration_url
escape_url_for_config = _env_mod.escape_url_for_config


VALID_PROD_SECRET = "a" * 32
VALID_PROD_EMAIL = "admin@university.edu"
DEV_APP_URL = "postgresql+psycopg://examos_app:dev_app_pass@localhost:5433/examos"
DEV_MIGRATOR_URL = "postgresql+psycopg://examos_migrator:dev_mig_pass@localhost:5433/examos"
PROD_APP_URL = "postgresql+psycopg://examos_app:prod_app_pass@ep-xyz-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
PROD_MIGRATOR_URL = "postgresql+psycopg://examos_migrator:prod_mig_pass@ep-xyz.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"


def make_test_settings(**kwargs) -> Settings:
    """Helper to instantiate Settings with explicit kwargs, bypassing local .env file."""
    base_kwargs = {
        "_env_file": None,
        "DATABASE_URL": DEV_APP_URL,
        "APP_SECRET_KEY": "dev-placeholder-secret-key-32chars",
    }
    base_kwargs.update(kwargs)
    return Settings(**base_kwargs)


class TestAlembicConnectionEnforcement:
    """Production-safe Alembic migration connection enforcement tests."""

    def test_development_with_migration_url_configured(self):
        """In development, MIGRATION_DATABASE_URL is preferred when configured."""
        s = make_test_settings(
            APP_ENV="development",
            DATABASE_URL=DEV_APP_URL,
            MIGRATION_DATABASE_URL=DEV_MIGRATOR_URL,
        )
        cfg = Config()
        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == DEV_MIGRATOR_URL

    def test_development_without_migration_url_falls_back_to_database_url(self):
        """In development, missing MIGRATION_DATABASE_URL falls back to DATABASE_URL."""
        s = make_test_settings(
            APP_ENV="development",
            DATABASE_URL=DEV_APP_URL,
            MIGRATION_DATABASE_URL=None,
        )
        cfg = Config()
        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == DEV_APP_URL

    def test_production_with_migration_url_configured(self):
        """In production, configured MIGRATION_DATABASE_URL is used."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=PROD_MIGRATOR_URL,
        )
        cfg = Config()
        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == PROD_MIGRATOR_URL

    def test_production_without_migration_url_raises_runtime_error(self):
        """In production, missing MIGRATION_DATABASE_URL refuses to fall back to DATABASE_URL."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=None,
        )
        cfg = Config()
        with pytest.raises(RuntimeError) as exc_info:
            resolve_migration_url(cfg, settings_obj=s)

        error_message = str(exc_info.value)
        assert "MIGRATION_DATABASE_URL must be explicitly configured" in error_message
        assert "Refusing to fall back to DATABASE_URL" in error_message

    def test_production_prod_alias_without_migration_url_raises_runtime_error(self):
        """The 'prod' alias is recognized as production and refuses fallback."""
        s = make_test_settings(
            APP_ENV="prod",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=None,
        )
        cfg = Config()
        with pytest.raises(RuntimeError) as exc_info:
            resolve_migration_url(cfg, settings_obj=s)

        error_message = str(exc_info.value)
        assert "MIGRATION_DATABASE_URL must be explicitly configured" in error_message

    def test_explicit_x_argument_override_takes_precedence_in_production(self):
        """Explicit Alembic -x url=... override takes precedence even in production without MIGRATION_DATABASE_URL."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=None,
        )
        override_url = "postgresql+psycopg://override_user:override_pass@custom-host:5432/custom_db"
        cfg = Config()
        cmd_opts = {"url": override_url}
        resolved = resolve_migration_url(cfg, cmd_opts=cmd_opts, settings_obj=s)
        assert resolved == override_url

    def test_explicit_x_argument_override_takes_precedence_in_development(self):
        """Explicit Alembic -x url=... override takes precedence over both configured URLs in development."""
        s = make_test_settings(
            APP_ENV="development",
            DATABASE_URL=DEV_APP_URL,
            MIGRATION_DATABASE_URL=DEV_MIGRATOR_URL,
        )
        override_url = "postgresql+psycopg://override_user:override_pass@custom-host:5432/custom_db"
        cfg = Config()
        cmd_opts = {"url": override_url}
        resolved = resolve_migration_url(cfg, cmd_opts=cmd_opts, settings_obj=s)
        assert resolved == override_url

    def test_empty_or_whitespace_migration_url_rejected_in_production(self):
        """An empty or whitespace-only MIGRATION_DATABASE_URL is treated as absent and rejected in production."""
        for empty_val in ("", "   ", "\t\n"):
            s = make_test_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
                APP_SECRET_KEY=VALID_PROD_SECRET,
                DATABASE_URL=PROD_APP_URL,
                MIGRATION_DATABASE_URL=empty_val,
            )
            cfg = Config()
            with pytest.raises(RuntimeError) as exc_info:
                resolve_migration_url(cfg, settings_obj=s)
            assert "MIGRATION_DATABASE_URL must be explicitly configured" in str(exc_info.value)

    def test_empty_or_whitespace_x_argument_override_rejected(self):
        """An empty or whitespace-only -x url override raises RuntimeError."""
        s = make_test_settings(APP_ENV="development")
        cfg = Config()
        for empty_x in ("", "   ", "\t"):
            with pytest.raises(RuntimeError) as exc_info:
                resolve_migration_url(cfg, cmd_opts={"url": empty_x}, settings_obj=s)
            assert "Explicit Alembic '-x url' override must not be empty" in str(exc_info.value)

    def test_error_message_does_not_disclose_credentials_or_secrets(self):
        """Security: RuntimeError messages must never disclose connection strings, passwords, or usernames."""
        sensitive_password = "SUPER_SECRET_COMPLEX_PASSWORD_123!"
        sensitive_user = "secret_db_admin_role"
        sensitive_host = "db-internal.private-cloud.internal"
        sensitive_url = f"postgresql+psycopg://{sensitive_user}:{sensitive_password}@{sensitive_host}:5432/proddb"

        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=sensitive_url,
            MIGRATION_DATABASE_URL=None,
        )
        cfg = Config()
        with pytest.raises(RuntimeError) as exc_info:
            resolve_migration_url(cfg, settings_obj=s)

        error_message = str(exc_info.value)
        assert sensitive_password not in error_message
        assert sensitive_user not in error_message
        assert sensitive_host not in error_message
        assert "postgresql" not in error_message

    def test_fastapi_startup_does_not_require_migration_database_url(self):
        """Production validation for FastAPI does NOT require MIGRATION_DATABASE_URL."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=None,
        )
        # Production invariants pass without MIGRATION_DATABASE_URL
        assert s.validate_production_invariants() == s

    def test_programmatic_config_url_respected_in_test_environments(self):
        """Programmatic sqlalchemy.url set on Alembic Config (used by test suites) is respected."""
        s = make_test_settings(
            APP_ENV="development",
            DATABASE_URL=DEV_APP_URL,
            MIGRATION_DATABASE_URL=DEV_MIGRATOR_URL,
        )
        cfg = Config()
        test_isolated_url = "postgresql+psycopg://test_runner:pass@localhost:5433/examos_test"
        cfg.set_main_option("sqlalchemy.url", test_isolated_url)

        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == test_isolated_url

    def test_production_with_empty_programmatic_config_and_valid_migration_url(self):
        """In production with empty programmatic sqlalchemy.url, configured MIGRATION_DATABASE_URL is used."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=PROD_MIGRATOR_URL,
        )
        cfg = Config()
        cfg.set_main_option("sqlalchemy.url", "")
        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == PROD_MIGRATOR_URL

    def test_production_with_programmatic_config_but_missing_migration_url_fails(self):
        """In production, a programmatic sqlalchemy.url cannot bypass the MIGRATION_DATABASE_URL requirement."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=None,
        )
        cfg = Config()
        bypass_url = "postgresql+psycopg://bypass_role:secret_pass@db.example.com:5432/bypass_db"
        cfg.set_main_option("sqlalchemy.url", bypass_url)

        with pytest.raises(RuntimeError) as exc_info:
            resolve_migration_url(cfg, settings_obj=s)

        error_message = str(exc_info.value)
        assert "MIGRATION_DATABASE_URL must be explicitly configured" in error_message
        assert "Refusing to fall back to DATABASE_URL or programmatic config URL" in error_message
        assert "bypass_role" not in error_message
        assert "secret_pass" not in error_message

    def test_production_with_programmatic_config_and_valid_migration_url_uses_migration_url(self):
        """In production with programmatic sqlalchemy.url, MIGRATION_DATABASE_URL is authoritative and used."""
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=PROD_MIGRATOR_URL,
        )
        cfg = Config()
        cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg://bypass_role:pass@db.example.com:5432/bypass_db")

        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == PROD_MIGRATOR_URL

    def test_percent_encoded_credentials_round_trip(self):
        """Alembic Config escaping preserves percent-encoded credentials through ConfigParser round-trip."""
        raw_url = "postgresql+psycopg://user%40ss%25word@host.example/neondb?sslmode=require"
        cfg = Config()

        # Storing escaped form in Alembic Config
        escaped_url = escape_url_for_config(raw_url)
        assert "%%" in escaped_url
        cfg.set_main_option("sqlalchemy.url", escaped_url)

        # get_main_option returns the exact original URL via ConfigParser interpolation
        retrieved_url = cfg.get_main_option("sqlalchemy.url")
        assert retrieved_url == raw_url
        assert "%40" in retrieved_url
        assert "%25" in retrieved_url

        # Section dictionary (received by engine_from_config) also receives the exact original URL
        section = cfg.get_section(cfg.config_ini_section, {})
        assert section.get("sqlalchemy.url") == raw_url

    def test_resolve_migration_url_preserves_percent_encoded_credentials(self):
        """resolve_migration_url preserves percent-encoded credentials in MIGRATION_DATABASE_URL."""
        percent_url = "postgresql+psycopg://user%40ss%25word:p%25ss%231@ep-xyz.aws.neon.tech/neondb?sslmode=require"
        s = make_test_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
            DATABASE_URL=PROD_APP_URL,
            MIGRATION_DATABASE_URL=percent_url,
        )
        cfg = Config()
        resolved = resolve_migration_url(cfg, settings_obj=s)
        assert resolved == percent_url

        # End-to-end simulation of env.py config storage
        cfg.set_main_option("sqlalchemy.url", escape_url_for_config(resolved))
        assert cfg.get_main_option("sqlalchemy.url") == percent_url
        assert cfg.get_section(cfg.config_ini_section, {}).get("sqlalchemy.url") == percent_url

