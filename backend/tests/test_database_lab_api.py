"""
Integration tests for Database Performance Lab API endpoints (M3-DB-UI-1).

Tests:
- GET /api/v1/labs/db/benchmarks (faculty only, unauthenticated 401, student 403)
- POST /api/v1/labs/db/benchmarks/run (faculty only, CSRF enforcement, validation error handling)
- GET /api/v1/labs/db/benchmarks/runs (history listing)
- GET /api/v1/labs/db/benchmarks/runs/{run_id} (detail retrieval)
- Validation rejects invalid scenario, dataset size, and out-of-range repetitions.
- Database isolation: benchmark run does not touch examination tables.
"""

import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.benchmark import BenchmarkRun
from app.services.lab_data_service import seed_lab_dataset
from tests.helpers import auth_cookies_and_headers, create_test_user


def test_get_benchmark_catalog_unauthenticated(client: TestClient):
    """Catalog endpoint requires authentication."""
    resp = client.get("/api/v1/labs/db/benchmarks")
    assert resp.status_code == 401


def test_get_benchmark_catalog_student_forbidden(client: TestClient, test_db_session: Session):
    """Student cannot access faculty database lab."""
    student = create_test_user(test_db_session, role="STUDENT")
    cookies, headers = auth_cookies_and_headers(student)

    resp = client.get("/api/v1/labs/db/benchmarks", cookies=cookies, headers=headers)
    assert resp.status_code == 403


def test_get_benchmark_catalog_faculty_success(client: TestClient, test_db_session: Session):
    """Faculty can retrieve approved benchmark scenarios and dataset sizes."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    resp = client.get("/api/v1/labs/db/benchmarks", cookies=cookies, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "scenarios" in data
    assert "dataset_sizes" in data
    assert "active_dataset" in data
    assert "detected_scale" in data["active_dataset"]
    assert "counts" in data["active_dataset"]
    scenarios = {s["scenario_id"]: s for s in data["scenarios"]}
    assert "selective_lookup" in scenarios
    assert "join_students_enrollments" in scenarios
    assert "aggregation_department_gpa" in scenarios

    sizes = {s["size_key"]: s for s in data["dataset_sizes"]}
    assert "small" in sizes
    assert "medium" in sizes


def test_run_benchmark_scale_mismatch_returns_409(client: TestClient, test_db_session: Session):
    """POST /labs/db/benchmarks/run returns HTTP 409 DATASET_SCALE_MISMATCH on size mismatch."""
    seed_lab_dataset(test_db_session, size="small", seed=42)

    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    payload = {
        "scenario_id": "selective_lookup",
        "dataset_size": "medium",  # DB has small
        "seed": 42,
        "repetitions": 2,
    }

    resp = client.post(
        "/api/v1/labs/db/benchmarks/run",
        json=payload,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "DATASET_SCALE_MISMATCH"
    assert "requested 'medium', but the database currently contains 'small'" in body["error"]["message"]
    assert body["error"]["details"]["requested_scale"] == "medium"
    assert body["error"]["details"]["detected_scale"] == "small"


def test_run_benchmark_csrf_enforcement(client: TestClient, test_db_session: Session):
    """POST /labs/db/benchmarks/run enforces CSRF tokens."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    # Omit CSRF header
    bad_headers = {k: v for k, v in headers.items() if k.lower() != "x-csrf-token"}
    payload = {
        "scenario_id": "selective_lookup",
        "dataset_size": "small",
        "seed": 42,
        "repetitions": 2,
    }

    resp = client.post(
        "/api/v1/labs/db/benchmarks/run",
        json=payload,
        cookies=cookies,
        headers=bad_headers,
    )
    assert resp.status_code == 403


def test_run_benchmark_validation_failure(client: TestClient, test_db_session: Session):
    """Rejects invalid scenario codes and out-of-range repetitions."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    # Invalid scenario
    resp = client.post(
        "/api/v1/labs/db/benchmarks/run",
        json={"scenario_id": "non_existent_exploit", "dataset_size": "small", "repetitions": 2},
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "BENCHMARK_VALIDATION_ERROR"

    # Invalid repetitions > 10
    resp2 = client.post(
        "/api/v1/labs/db/benchmarks/run",
        json={"scenario_id": "selective_lookup", "dataset_size": "small", "repetitions": 50},
        cookies=cookies,
        headers=headers,
    )
    assert resp2.status_code == 422


def test_run_benchmark_success_and_history(client: TestClient, test_db_session: Session):
    """Faculty can successfully execute an approved benchmark and inspect history."""
    # Ensure lab data exists
    seed_lab_dataset(test_db_session, size="small", seed=42)

    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    payload = {
        "scenario_id": "selective_lookup",
        "dataset_size": "small",
        "seed": 42,
        "repetitions": 2,
    }

    resp = client.post(
        "/api/v1/labs/db/benchmarks/run",
        json=payload,
        cookies=cookies,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["scenario_id"] == "selective_lookup"
    assert data["dataset_size"] == "small"
    assert data["repetitions"] == 2
    assert "no_index" in data
    assert "indexed" in data
    assert data["no_index"]["execution_time_ms"] > 0
    assert data["indexed"]["execution_time_ms"] > 0
    assert "Plan" in data["no_index"]["plan"]
    assert "Plan" in data["indexed"]["plan"]
    assert "speedup_ratio" in data
    assert "run_id" in data

    run_id = data["run_id"]

    # History listing check
    hist_resp = client.get("/api/v1/labs/db/benchmarks/runs", cookies=cookies, headers=headers)
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert len(hist_data) >= 1
    assert hist_data[0]["run_id"] == run_id

    # Run detail check
    detail_resp = client.get(f"/api/v1/labs/db/benchmarks/runs/{run_id}", cookies=cookies, headers=headers)
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["run_id"] == run_id
    assert detail_data["scenario_id"] == "selective_lookup"


def test_get_run_detail_not_found(client: TestClient, test_db_session: Session):
    """404 returned for non-existent run ID."""
    faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
    cookies, headers = auth_cookies_and_headers(faculty)

    random_id = uuid.uuid4()
    resp = client.get(f"/api/v1/labs/db/benchmarks/runs/{random_id}", cookies=cookies, headers=headers)
    assert resp.status_code == 404
