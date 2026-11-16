"""
Unit and configuration tests for production security and environment hardening (Task 004A).

Verifies:
1. Environment normalization (case-insensitivity, whitespace, alias 'prod').
2. Cookie and CSRF security enforcement in production.
3. Seed faculty admin email validation (prohibiting .local in production).
4. Application secret key validation (minimum length, non-placeholder, zero leakage).
5. OpenAPI and Swagger UI endpoint disablement in production.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_application
from fastapi.testclient import TestClient

VALID_PROD_SECRET = "a" * 32
VALID_PROD_EMAIL = "admin@university.edu"
DUMMY_DB_URL = "postgresql+psycopg://user:pass@localhost:5432/testdb"


def make_settings(**kwargs) -> Settings:
    """Helper to instantiate Settings without reading workspace .env file."""
    base_kwargs = {
        "_env_file": None,
        "DATABASE_URL": DUMMY_DB_URL,
        "APP_SECRET_KEY": "dev-placeholder-key",
    }
    base_kwargs.update(kwargs)
    return Settings(**base_kwargs)


class TestEnvironmentNormalization:
    """Task 2: Consistent APP_ENV normalization."""

    def test_app_env_normalized_to_lowercase_and_stripped(self):
        s = make_settings(APP_ENV="  DEVELOPMENT  ")
        assert s.APP_ENV == "development"
        assert s.is_dev_or_test is True
        assert s.is_production is False

    def test_prod_alias_recognized_as_production(self):
        s = make_settings(
            APP_ENV="PROD",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
        )
        assert s.APP_ENV == "prod"
        assert s.is_production is True
        assert s.is_dev_or_test is False

    def test_production_recognized(self):
        s = make_settings(
            APP_ENV="Production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
        )
        assert s.APP_ENV == "production"
        assert s.is_production is True
        assert s.is_dev_or_test is False

    def test_staging_treated_as_non_dev_non_prod(self):
        s = make_settings(APP_ENV="staging")
        assert s.APP_ENV == "staging"
        assert s.is_production is False
        assert s.is_dev_or_test is False
        assert s.allow_local_email_domains is False

    def test_empty_app_env_rejected(self):
        """An explicitly empty string must be rejected; callers must omit APP_ENV to get the default."""
        with pytest.raises(ValidationError) as exc_info:
            make_settings(APP_ENV="")
        assert "APP_ENV must not be empty" in str(exc_info.value)

    def test_whitespace_only_app_env_rejected(self):
        """A whitespace-only APP_ENV must be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            make_settings(APP_ENV="   ")
        assert "APP_ENV must not be empty" in str(exc_info.value)

    def test_omitted_app_env_defaults_to_development(self):
        """When APP_ENV is not provided at all, Settings must default to 'development'."""
        s = Settings(
            _env_file=None,  # type: ignore[call-arg]
            DATABASE_URL=DUMMY_DB_URL,
            APP_SECRET_KEY="dev-key",
        )
        assert s.APP_ENV == "development"
        assert s.is_dev_or_test is True


class TestProductionCookieAndCsrfEnforcement:
    """Task 2: Cookie and CSRF configuration rules."""

    def test_production_rejects_insecure_cookie(self):
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=False,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
                APP_SECRET_KEY=VALID_PROD_SECRET,
            )
        assert "COOKIE_SECURE must be True in production environments" in str(exc_info.value)

    def test_production_rejects_disabled_csrf(self):
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=False,
                SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
                APP_SECRET_KEY=VALID_PROD_SECRET,
            )
        assert "CSRF_ENABLED must be True in production environments" in str(exc_info.value)

    def test_development_allows_insecure_cookie(self):
        s = make_settings(
            APP_ENV="development",
            COOKIE_SECURE=False,
            CSRF_ENABLED=True,
        )
        assert s.COOKIE_SECURE is False
        assert s.CSRF_ENABLED is True


class TestFacultyAdminConfiguration:
    """Task 3: Production faculty admin email rules."""

    def test_production_rejects_default_local_faculty_email(self):
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL="faculty@examos.local",
                APP_SECRET_KEY=VALID_PROD_SECRET,
            )
        assert "cannot use a '.local' domain in production" in str(exc_info.value)

    def test_production_rejects_blank_faculty_email(self):
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL="   ",
                APP_SECRET_KEY=VALID_PROD_SECRET,
            )
        assert "SEED_FACULTY_EMAIL must be configured" in str(exc_info.value)

    def test_production_rejects_invalid_email_syntax(self):
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL="invalid_no_at_domain",
                APP_SECRET_KEY=VALID_PROD_SECRET,
            )
        assert "SEED_FACULTY_EMAIL" in str(exc_info.value)
        assert "invalid" in str(exc_info.value)

    def test_production_accepts_valid_non_local_email(self):
        s = make_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL="faculty@institution.org",
            APP_SECRET_KEY=VALID_PROD_SECRET,
        )
        assert s.SEED_FACULTY_EMAIL == "faculty@institution.org"

    def test_development_allows_local_faculty_email(self):
        s = make_settings(
            APP_ENV="development",
            SEED_FACULTY_EMAIL="faculty@examos.local",
        )
        assert s.SEED_FACULTY_EMAIL == "faculty@examos.local"

    def test_production_normalizes_faculty_email_whitespace_and_case(self):
        """
        Leading/trailing whitespace and uppercase characters in SEED_FACULTY_EMAIL
        must be normalized (stripped + lowercased) BEFORE production validation,
        and the stored field value must reflect the normalized form.
        """
        s = make_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL="  Admin@University.EDU  ",
            APP_SECRET_KEY=VALID_PROD_SECRET,
        )
        assert s.SEED_FACULTY_EMAIL == "admin@university.edu"


class TestApplicationSecretValidation:
    """Task 4: Production application secret validation."""

    def test_production_rejects_short_secret(self):
        short_secret = "too_short_secret_under_32_chars"
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
                APP_SECRET_KEY=short_secret,
            )
        error_msg = str(exc_info.value)
        assert "must be at least 32 characters long" in error_msg
        # Assert secret itself is not leaked in error message
        assert short_secret not in error_msg

    def test_production_rejects_placeholder_secret(self):
        placeholder = "PLACEHOLDER_GENERATE_RANDOM_SECRET_KEY_64_CHARS_LONG_TEST"
        with pytest.raises(ValidationError) as exc_info:
            make_settings(
                APP_ENV="production",
                COOKIE_SECURE=True,
                CSRF_ENABLED=True,
                SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
                APP_SECRET_KEY=placeholder,
            )
        error_msg = str(exc_info.value)
        assert "contains an insecure placeholder" in error_msg
        # Assert placeholder key is not leaked in error message
        assert placeholder not in error_msg

    def test_production_accepts_strong_secret(self):
        strong_key = "e8f3b294a5c107e9d482bf16a09c2534e8f3b294a5c107e9d482bf16a09c2534"
        s = make_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=strong_key,
        )
        assert s.APP_SECRET_KEY == strong_key

    def test_development_allows_placeholder_secret(self):
        s = make_settings(
            APP_ENV="development",
            APP_SECRET_KEY="dev_placeholder",
        )
        assert s.APP_SECRET_KEY == "dev_placeholder"


class TestOpenApiDocumentationInProduction:
    """Task 5: Swagger /docs and OpenAPI /openapi.json disablement."""

    def test_production_disables_docs_and_openapi(self):
        prod_settings = make_settings(
            APP_ENV="production",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
        )
        prod_app = create_application(settings_override=prod_settings)
        client = TestClient(prod_app)

        docs_resp = client.get("/docs")
        assert docs_resp.status_code == 404

        openapi_resp = client.get("/openapi.json")
        assert openapi_resp.status_code == 404

    def test_prod_alias_disables_docs_and_openapi(self):
        prod_settings = make_settings(
            APP_ENV="prod",
            COOKIE_SECURE=True,
            CSRF_ENABLED=True,
            SEED_FACULTY_EMAIL=VALID_PROD_EMAIL,
            APP_SECRET_KEY=VALID_PROD_SECRET,
        )
        prod_app = create_application(settings_override=prod_settings)
        client = TestClient(prod_app)

        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

    def test_development_enables_docs_and_openapi(self):
        dev_settings = make_settings(
            APP_ENV="development",
        )
        dev_app = create_application(settings_override=dev_settings)
        client = TestClient(dev_app)

        docs_resp = client.get("/docs")
        assert docs_resp.status_code == 200

        openapi_resp = client.get("/openapi.json")
        assert openapi_resp.status_code == 200

