import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.db.base import Base


def escape_url_for_config(url: str) -> str:
    """
    Escapes literal '%' characters as '%%' for Alembic ConfigParser interpolation.

    Alembic's ConfigParser interprets '%' as basic interpolation syntax. Escaping '%'
    as '%%' ensures that when Alembic or SQLAlchemy retrieves the value via
    config.get_main_option() or config.get_section(), the original unescaped URL
    with percent-encoded username or password characters is faithfully restored.
    """
    return url.replace("%", "%%")


def resolve_migration_url(
    config_obj: Any = None,
    *,
    cmd_opts: dict[str, str] | None = None,
    settings_obj: Any = None,
) -> str:
    """
    Resolves the authoritative database URL for Alembic migrations.

    Precedence and Enforcement Rules:
    1. Explicit Alembic -x url=... CLI override retains highest precedence as a deliberate operator override.
    2. In production (settings.is_production is True):
       - settings.MIGRATION_DATABASE_URL must be configured and non-empty.
       - Programmatically configured sqlalchemy.url and DATABASE_URL fallback are strictly prohibited.
       - Returns settings.MIGRATION_DATABASE_URL.
    3. In recognized development/test environments (settings.is_production is False):
       - Programmatically configured sqlalchemy.url on the Config object (e.g. test harness) is respected.
       - Otherwise, settings.MIGRATION_DATABASE_URL is preferred if non-empty.
       - Otherwise, falls back to settings.DATABASE_URL.
    4. If no valid URL is resolved, raises RuntimeError.

    Security & Safety Invariants:
    - Never print connection strings, credentials, or secrets in error messages.
    - Empty or whitespace-only migration URLs are rejected as absent.
    """
    current_settings = settings_obj if settings_obj is not None else settings

    # 0. Live connection passed programmatically via config.attributes
    if config_obj is not None and getattr(config_obj, "attributes", {}).get("connection") is not None:
        return "postgresql+psycopg://passed_connection"

    # 1. Explicit Alembic -x url=... CLI override retains documented operator precedence
    if cmd_opts and "url" in cmd_opts:
        raw_x_url = cmd_opts["url"]
        stripped_x_url = raw_x_url.strip() if isinstance(raw_x_url, str) else ""
        if not stripped_x_url:
            raise RuntimeError("Explicit Alembic '-x url' override must not be empty or whitespace-only.")
        return stripped_x_url

    raw_migration_url = getattr(current_settings, "MIGRATION_DATABASE_URL", None)
    migration_url = (raw_migration_url or "").strip() if isinstance(raw_migration_url, str) else ""

    # 2. Strict Production Enforcement: MIGRATION_DATABASE_URL is authoritative and mandatory.
    # Programmatic config URLs and application DATABASE_URL fallback cannot bypass this requirement.
    if getattr(current_settings, "is_production", False):
        if not migration_url:
            raise RuntimeError(
                "MIGRATION_DATABASE_URL must be explicitly configured for database migrations in production environments. "
                "Refusing to fall back to DATABASE_URL or programmatic config URL."
            )
        return migration_url

    # 3. Development / Test environments:
    # 3a. Programmatically configured sqlalchemy.url on the Config object (e.g. test harness)
    if config_obj is not None:
        config_url = config_obj.get_main_option("sqlalchemy.url")
        if config_url and config_url.strip():
            return config_url.strip()

    # 3b. Prefer settings.MIGRATION_DATABASE_URL if configured
    if migration_url:
        return migration_url

    # 3c. Fallback to settings.DATABASE_URL
    raw_fallback_url = getattr(current_settings, "DATABASE_URL", None)
    fallback_url = (raw_fallback_url or "").strip() if isinstance(raw_fallback_url, str) else ""
    if fallback_url:
        return fallback_url

    raise RuntimeError(
        "No database URL configured for migrations: both MIGRATION_DATABASE_URL and DATABASE_URL are absent or empty."
    )


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
if hasattr(context, "config"):
    config = context.config

    # Interpret the config file for Python logging.
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

    # Set target metadata for 'autogenerate' support
    target_metadata = Base.metadata

    # Resolve authoritative migration URL with strict production enforcement
    cmd_opts = context.get_x_argument(as_dictionary=True)
    resolved_url = resolve_migration_url(
        config,
        cmd_opts=cmd_opts,
        settings_obj=settings,
    )
    config.set_main_option("sqlalchemy.url", escape_url_for_config(resolved_url))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata
            )

            with context.begin_transaction():
                context.run_migrations()
    else:
        context.configure(
            connection=connectable, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if hasattr(context, "config"):
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
