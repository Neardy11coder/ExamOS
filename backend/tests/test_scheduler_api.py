"""
Integration tests for POST /api/v1/scheduler/simulate endpoint (M2-OS-UI-1).

Verifies:
- Faculty access granted and simulation produces correct schedule and metrics.
- Student access rejected with 403.
- Unauthenticated access rejected with 401.
- CSRF missing/mismatch rejected with 403.
- Invalid simulation inputs rejected with 422 and structured field error.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_cookies_and_headers, create_test_user


def test_scheduler_endpoint_success_fcfs(client: TestClient, test_db_session: Session):
    """Faculty can run simulation successfully."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    payload = {
        "algorithm": "FCFS",
        "jobs": [
            {"id": "A", "arrival_time": 0, "burst_time": 3, "priority": 2},
            {"id": "B", "arrival_time": 5, "burst_time": 2, "priority": 1},
        ],
    }

    resp = client.post(
        "/api/v1/scheduler/simulate",
        json=payload,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["algorithm"] == "FCFS"
    assert data["total_burst_time"] == 5
    assert data["measurement_window"] == 7
    assert len(data["jobs"]) == 2
    assert len(data["timeline"]) == 3
    assert data["timeline"][1]["kind"] == "IDLE"
    assert data["timeline"][1]["job_id"] is None


def test_scheduler_endpoint_success_round_robin(client: TestClient, test_db_session: Session):
    """Faculty can run Round Robin with quantum."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    payload = {
        "algorithm": "ROUND_ROBIN",
        "quantum": 2,
        "jobs": [
            {"id": "A", "arrival_time": 0, "burst_time": 5},
            {"id": "B", "arrival_time": 1, "burst_time": 3},
        ],
    }

    resp = client.post(
        "/api/v1/scheduler/simulate",
        json=payload,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["algorithm"] == "ROUND_ROBIN"
    assert data["quantum"] == 2
    assert data["latest_completion_time"] == 8
    assert data["cpu_utilization_percent"] == 100.0


def test_scheduler_endpoint_student_forbidden(client: TestClient, test_db_session: Session):
    """Students cannot access the OS scheduling simulator."""
    student = create_test_user(test_db_session, role="STUDENT")
    cookies, headers = auth_cookies_and_headers(student)

    payload = {
        "algorithm": "FCFS",
        "jobs": [{"id": "A", "arrival_time": 0, "burst_time": 1}],
    }

    resp = client.post(
        "/api/v1/scheduler/simulate",
        json=payload,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 403


def test_scheduler_endpoint_unauthenticated(client: TestClient):
    """Unauthenticated request without cookies returns 401 or 403 (unauthenticated)."""
    payload = {
        "algorithm": "FCFS",
        "jobs": [{"id": "A", "arrival_time": 0, "burst_time": 1}],
    }

    resp = client.post("/api/v1/scheduler/simulate", json=payload)
    assert resp.status_code in (401, 403)


def test_scheduler_endpoint_csrf_missing(client: TestClient, test_db_session: Session):
    """State-changing request without CSRF header rejected with 403."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, _ = auth_cookies_and_headers(faculty)

    payload = {
        "algorithm": "FCFS",
        "jobs": [{"id": "A", "arrival_time": 0, "burst_time": 1}],
    }

    resp = client.post(
        "/api/v1/scheduler/simulate",
        json=payload,
        cookies=cookies,
        # No X-CSRF-Token header
    )
    assert resp.status_code == 403


def test_scheduler_endpoint_validation_error(client: TestClient, test_db_session: Session):
    """Invalid input (e.g. Round Robin missing quantum) returns 422 with structured error."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    payload = {
        "algorithm": "ROUND_ROBIN",
        "quantum": None,
        "jobs": [{"id": "A", "arrival_time": 0, "burst_time": 2}],
    }

    resp = client.post(
        "/api/v1/scheduler/simulate",
        json=payload,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["code"] == "SCHEDULER_VALIDATION_ERROR"
    assert data["error"]["field"] == "quantum"
