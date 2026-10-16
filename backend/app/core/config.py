from pathlib import Path
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
    APP_SECRET_KEY: str

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
        env = (self.APP_ENV or "").strip().lower()

        # Hard boundary: Production never allows local domains under any circumstances
        if env in ("production", "prod"):
            return False

        # Recognized dev/test environments
        if env in ("development", "dev", "test", "testing"):
            if self.ALLOW_LOCAL_EMAIL_DOMAINS is not None:
                return bool(self.ALLOW_LOCAL_EMAIL_DOMAINS)
            return True

        # Unknown environments (including staging) default to rejecting local domains
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
    ML_MODEL_PATH: str = "../ml/artifacts/topic_classifier.joblib"
    ML_CONFIDENCE_THRESHOLD: float = 0.55
    EXPIRED_ATTEMPT_SWEEP_SECONDS: int = 60

    # Initial operator bootstrap credentials
    SEED_FACULTY_EMAIL: str = "faculty@examos.local"
    SEED_FACULTY_PASSWORD: str | None = None


settings = Settings()
