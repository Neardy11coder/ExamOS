from collections.abc import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.main import app


def pytest_configure(config: pytest.Config) -> None:
    """
    Protective test startup guard.
    Fails immediately if TEST_DATABASE_URL is absent, points to any database
    other than 'examos_test', or connects with any username other than 'examos_test_runner'.
    Tests are strictly prevented from falling back to DATABASE_URL.
    """
    if not settings.TEST_DATABASE_URL:
        raise RuntimeError(
            "FATAL CONFIG ERROR: TEST_DATABASE_URL is absent or empty. "
            "Tests will not execute without an explicit test database configuration."
        )

    test_url = make_url(str(settings.TEST_DATABASE_URL))
    dev_url = make_url(str(settings.DATABASE_URL))

    if str(test_url) == str(dev_url):
        raise RuntimeError(
            "FATAL CONFIG ERROR: TEST_DATABASE_URL is identical to DATABASE_URL. "
            "Tests aborted immediately to protect development data."
        )

    if test_url.database != "examos_test":
        raise RuntimeError(
            f"FATAL CONFIG ERROR: TEST_DATABASE_URL must target database 'examos_test', "
            f"got '{test_url.database}'. Test execution refused."
        )

    if test_url.username != "examos_test_runner":
        raise RuntimeError(
            f"FATAL CONFIG ERROR: TEST_DATABASE_URL must authenticate as 'examos_test_runner', "
            f"got '{test_url.username}'. Test execution refused."
        )


@pytest.fixture(scope="session")
def test_db_engine() -> Generator[Engine, None, None]:
    """Provides a SQLAlchemy Engine connected strictly to the test database."""
    engine = create_engine(
        str(settings.TEST_DATABASE_URL),
        pool_pre_ping=True,
    )
    # Verify reachability
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_db_session(test_db_engine: Engine) -> Generator[Session, None, None]:
    """
    Provides a transactional session on the test database.
    Rolls back any changes upon test completion.

    Uses join_transaction_mode="create_savepoint" so that service-layer
    calls to db.commit() are demoted to SAVEPOINT/RELEASE SAVEPOINT operations
    rather than committing the outer connection-level transaction.  The outer
    transaction.rollback() at teardown therefore cleanly undoes every insert,
    update, and delete made during the test, preventing inter-test data leakage.
    """
    connection = test_db_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        autocommit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(test_db_session: Session) -> Generator[TestClient, None, None]:
    """
    TestClient with get_db dependency overridden to strictly use the test database session.
    """
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield test_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
