from pathlib import Path
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dynamically resolve project root: ExamOS/backend/app/core/config.py -> ExamOS
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application environment
    APP_ENV: str = "development"
    ALLOW_LOCAL_EMAIL_DOMAINS: bool | None = None

    # Application secret key for signing JWT tokens (HS256)
    # Production security note:
    # Minimum length (>= 32 chars) and placeholder rejection provide defense-in-depth,
    # but do not prove high entropy or cryptographic randomness.
    # Operators must generate a cryptographically secure random key for production via:
    #   openssl rand -hex 32
    # or:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    APP_SECRET_KEY: str

    @field_validator("APP_ENV", mode="before")
    @classmethod
    def normalize_app_env(cls, v: str | None) -> str:
        """
        Normalize APP_ENV: strip whitespace and convert to lowercase.
        Preserves default 'development' when omitted (None).
        Rejects explicitly empty or whitespace-only strings.
        """
        if v is None:
            return "development"
        if isinstance(v, str):
            v_stripped = v.strip().lower()
            if not v_stripped:
                raise ValueError("APP_ENV must not be empty or whitespace-only when provided.")
            return v_stripped
        return v

    @field_validator("SEED_FACULTY_EMAIL", mode="before")
    @classmethod
    def normalize_seed_faculty_email(cls, v: str | None) -> str:
        """
        Normalize SEED_FACULTY_EMAIL before validation.
        Converts to lowercase and strips leading/trailing whitespace, consistent with registration email normalization.
        """
        if v is None:
            return "faculty@examos.local"
        return v.strip().lower()

    @property
    def is_production(self) -> bool:
        """Whether the application is configured for a production environment ('production', 'prod')."""
        env = (self.APP_ENV or "").strip().lower()
        return env in ("production", "prod")

    @property
    def is_dev_or_test(self) -> bool:
        """Whether the application is running in recognized development or test environments."""
        env = (self.APP_ENV or "").strip().lower()
        return env in ("development", "dev", "test", "testing")

    @property
    def allow_local_email_domains(self) -> bool:
        """
        Whether '.local' email domains are permitted (e.g. faculty@examos.local).

        Security invariants:
        - Handled case-insensitively and whitespace-trimmed.
        - Production ('production', 'prod') NEVER permits local domains under any
          circumstances, strictly ignoring ALLOW_LOCAL_EMAIL_DOMAINS even if True.
        - Recognized dev/test environments ('development', 'dev', 'test', 'testing')
          permit local domains by default, and honor ALLOW_LOCAL_EMAIL_DOMAINS if set.
        - All unknown environments (including 'staging') default to rejecting local domains.
        """
        if self.is_production:
            return False

        if self.is_dev_or_test:
            if self.ALLOW_LOCAL_EMAIL_DOMAINS is not None:
                return bool(self.ALLOW_LOCAL_EMAIL_DOMAINS)
            return True

        return False

    # Database configuration
    DATABASE_URL: str
    MIGRATION_DATABASE_URL: str | None = None
    TEST_DATABASE_URL: str | None = None
    PROVISIONER_DATABASE_URL: str | None = None

    # CORS and security
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    AUTH_TOKEN_TTL_MINUTES: int = 480
    COOKIE_SECURE: bool = False
    CSRF_ENABLED: bool = True

    # Domain limits and defaults
    MAX_EXAM_DURATION_MINUTES: int = 240
    MAX_QUESTIONS_PER_EXAM: int = 100
    MAX_OPTIONS_PER_QUESTION: int = 6
    MAX_SCHEDULER_JOBS: int = 50
    DBLAB_MAX_DATASET_SIZE: str = "large"
    DBLAB_DEFAULT_REPETITIONS: int = 5
    ML_MODEL_PATH: str = "../ml/artifacts/distilbert_classifier"
    ML_FALLBACK_MODEL_PATH: str = "../ml/artifacts/topic_classifier.joblib"
    ML_CONFIDENCE_THRESHOLD: float = 0.55
    EXPIRED_ATTEMPT_SWEEP_SECONDS: int = 60

    # Initial operator bootstrap credentials
    SEED_FACULTY_EMAIL: str = "faculty@examos.local"
    SEED_FACULTY_PASSWORD: str | None = None

    @model_validator(mode="after")
    def validate_production_invariants(self) -> "Settings":
        """
        Enforces strict production security invariants when running in production ('production', 'prod'):
        1. COOKIE_SECURE must be True.
        2. CSRF_ENABLED must be True.
        3. SEED_FACULTY_EMAIL must be a non-empty, non-.local email address.
        4. APP_SECRET_KEY must not be a placeholder and must be at least 32 characters long.
        """
        if self.is_production:
            # Task 2: Production Cookie and CSRF Enforcement
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE must be True in production environments.")
            if not self.CSRF_ENABLED:
                raise ValueError("CSRF_ENABLED must be True in production environments.")

            # Task 3: Faculty Admin Configuration
            # Note: Normalization (strip and lowercase) was applied in normalize_seed_faculty_email
            faculty_email = self.SEED_FACULTY_EMAIL
            if not faculty_email:
                raise ValueError("SEED_FACULTY_EMAIL must be configured in production environments.")
            if "@" not in faculty_email:
                raise ValueError(f"SEED_FACULTY_EMAIL '{self.SEED_FACULTY_EMAIL}' is invalid.")
            domain = faculty_email.rsplit("@", 1)[1]
            if domain == "local" or domain.endswith(".local"):
                raise ValueError(
                    f"SEED_FACULTY_EMAIL cannot use a '.local' domain in production environments (got '{self.SEED_FACULTY_EMAIL}')."
                )
            try:
                import email_validator

                email_validator.validate_email(faculty_email, check_deliverability=False)
            except Exception as e:
                raise ValueError(
                    f"SEED_FACULTY_EMAIL '{self.SEED_FACULTY_EMAIL}' is invalid: {e}"
                ) from e

            # Task 4: Application Secret Validation
            secret = self.APP_SECRET_KEY or ""
            if len(secret) < 32:
                raise ValueError("APP_SECRET_KEY must be at least 32 characters long in production environments.")
            lower_secret = secret.lower()
            if any(
                placeholder in lower_secret
                for placeholder in ("placeholder", "changeme", "secret_key", "secretkey", "default")
            ):
                raise ValueError(
                    "APP_SECRET_KEY contains an insecure placeholder or default value; a strong random key is required in production."
                )

        return self


settings = Settings()
