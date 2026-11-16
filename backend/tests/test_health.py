from fastapi import status
from fastapi.testclient import TestClient


def test_health_endpoint_healthy(client: TestClient) -> None:
    """Verify that /api/v1/health returns 200 OK and connected database status."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "ok"
    assert data["app_env"] == "development"
    assert data["database"] == "connected"


def test_health_endpoint_contract(client: TestClient) -> None:
    """Verify exact response payload structure of /api/v1/health."""
    response = client.get("/api/v1/health")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert set(data.keys()) == {"status", "app_env", "database"}


def test_health_endpoint_database_error_redaction(client: TestClient) -> None:
    """
    Verify that database exceptions with sensitive connection details
    are never returned to the client and return generic 503 instead.
    """
    from unittest.mock import MagicMock
    from app.db.session import get_db
    from app.main import app

    sensitive_detail = (
        'connection to server at "10.142.0.12", port 5432 failed: '
        'password authentication failed for user "super_secret_pg_admin"'
    )

    def mock_failing_get_db():
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception(sensitive_detail)
        yield mock_session

    app.dependency_overrides[get_db] = mock_failing_get_db
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

        # Assert zero leakage of sensitive internal details
        assert "super_secret_pg_admin" not in response.text
        assert "10.142.0.12" not in response.text
        assert "password" not in response.text

        # Assert contract-compliant generic error structure
        payload = response.json()
        assert "error" in payload
        assert payload["error"]["code"] == "HTTP_ERROR"
        assert payload["error"]["message"] == "Database service unavailable"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_health_endpoint_log_redaction(client: TestClient) -> None:
    """
    Regression: a database exception containing sensitive connection details
    must NOT appear in log output or in the HTTP response body.

    Verifies:
    - The logger.warning is called with only the exception class name and
      a safe diagnostic code (DB_HEALTH_UNAVAILABLE), not the raw exception string.
    - The mocked warning call arguments do NOT contain the host IP, username,
      password, or any part of the original connection string.
    - HTTP response body does NOT contain any sensitive credential fragments.
    """
    from unittest.mock import MagicMock, patch
    from app.db.session import get_db
    from app.main import app

    sensitive_host = "10.142.0.99"
    sensitive_user = "db_root_superuser"
    sensitive_pass = "ultra_secret_password_xyz"
    sensitive_detail = (
        f'connection to server at "{sensitive_host}", port 5432 failed: '
        f'password authentication failed for user "{sensitive_user}"; '
        f'password="{sensitive_pass}"'
    )

    def mock_failing_get_db():
        mock_session = MagicMock()
        mock_session.execute.side_effect = Exception(sensitive_detail)
        yield mock_session

    app.dependency_overrides[get_db] = mock_failing_get_db
    try:
        with patch("app.api.v1.endpoints.health.logger") as mock_logger:
            response = client.get("/api/v1/health")

            assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

            # --- Verify logger.warning was called exactly once ---
            assert mock_logger.warning.call_count == 1, (
                f"Expected logger.warning to be called once; got {mock_logger.warning.call_count}"
            )

            # Reconstruct what was logged: format string + all args
            call_args = mock_logger.warning.call_args
            format_str = call_args[0][0] if call_args[0] else ""
            format_args = call_args[0][1:] if len(call_args[0]) > 1 else ()
            logged_text = format_str % format_args

            # --- Log redaction: sensitive fragments must NEVER appear ---
            assert sensitive_host not in logged_text, "Host IP leaked into log message"
            assert sensitive_user not in logged_text, "Username leaked into log message"
            assert sensitive_pass not in logged_text, "Password leaked into log message"
            assert sensitive_detail not in logged_text, "Full connection string leaked"

            # --- Log content: safe diagnostic tokens MUST appear ---
            assert "DB_HEALTH_UNAVAILABLE" in logged_text, "Diagnostic code missing"
            assert "Exception" in logged_text, "Exception class name missing from log"
    finally:
        app.dependency_overrides.pop(get_db, None)

    # --- HTTP response redaction: no sensitive data in body ---
    response_text = response.text
    assert sensitive_host not in response_text, "Host IP leaked in HTTP response"
    assert sensitive_user not in response_text, "Username leaked in HTTP response"
    assert sensitive_pass not in response_text, "Password leaked in HTTP response"
