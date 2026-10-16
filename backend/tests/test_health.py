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
