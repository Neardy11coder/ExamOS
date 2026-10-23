"""
Unit and integration tests for Database Performance Lab (M3-DB-1).

Tests:
- Schema and table isolation in `examos_lab` (paired with-index and without-index).
- Public `benchmark_runs` table exists and enforces constraints.
- Seed reproducibility and idempotency across multiple runs.
- Benchmark catalog scenarios completeness and validation.
- Safe read-only benchmark execution without SQL injection.
- Rejection of unauthorized/invalid scenario codes.
- Actual PostgreSQL EXPLAIN plans and execution timings measured honestly.
"""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.benchmark import BenchmarkRun
from app.services.benchmark_catalog import BENCHMARK_SCENARIOS, DATASET_SIZES
from app.services.benchmark_service import (
    BenchmarkExecutionError,
    BenchmarkScaleMismatchError,
    BenchmarkValidationError,
    execute_approved_benchmark,
)
from app.services.lab_data_service import (
    get_lab_dataset_status,
    inspect_active_lab_dataset,
    seed_lab_dataset,
)


# ==============================================================================
# 1. Schema & Table Isolation Tests
# ==============================================================================

def test_lab_schema_and_tables_exist(test_db_session: Session):
    """Verify examos_lab tables and public benchmark_runs table exist."""
    inspector = inspect(test_db_session.connection())

    schemas = inspector.get_schema_names()
    assert "examos_lab" in schemas

    lab_tables = inspector.get_table_names(schema="examos_lab")
    expected_tables = {
        "lab_students_no_index",
        "lab_students_indexed",
        "lab_enrollments_no_index",
        "lab_enrollments_indexed",
    }
    assert expected_tables.issubset(set(lab_tables))

    public_tables = inspector.get_table_names(schema="public")
    assert "benchmark_runs" in public_tables


def test_lab_indexes_configuration(test_db_session: Session):
    """Verify indexed variants have indexes and no-index variants only have primary keys."""
    inspector = inspect(test_db_session.connection())

    # No-index tables should only have PK indexes
    no_idx_students = inspector.get_indexes("lab_students_no_index", schema="examos_lab")
    assert len(no_idx_students) == 0  # PK is a constraint, not listed under get_indexes in pg

    # Indexed tables have specific performance indexes
    idx_students = inspector.get_indexes("lab_students_indexed", schema="examos_lab")
    idx_names = {idx["name"] for idx in idx_students}
    assert "ix_lab_students_student_number" in idx_names
    assert "ix_lab_students_department" in idx_names

    idx_enrollments = inspector.get_indexes("lab_enrollments_indexed", schema="examos_lab")
    enrollment_idx_names = {idx["name"] for idx in idx_enrollments}
    assert "ix_lab_enrollments_student_id" in enrollment_idx_names
    assert "ix_lab_enrollments_course_code" in enrollment_idx_names


# ==============================================================================
# 2. Deterministic Seeding & Idempotency Tests
# ==============================================================================

def test_lab_seeding_small_dataset(test_db_session: Session):
    """Seeding small dataset creates exactly 100 students and 400 enrollments in paired tables."""
    stats = seed_lab_dataset(test_db_session, size="small", seed=42)

    assert stats["student_count"] == 100
    assert stats["enrollment_count"] == 400

    status = get_lab_dataset_status(test_db_session)
    assert status["students_no_index"] == 100
    assert status["students_indexed"] == 100
    assert status["enrollments_no_index"] == 400
    assert status["enrollments_indexed"] == 400


def test_lab_seeding_idempotency(test_db_session: Session):
    """Repeated seeding with same seed produces identical counts without duplicates."""
    seed_lab_dataset(test_db_session, size="small", seed=42)
    stats2 = seed_lab_dataset(test_db_session, size="small", seed=42)

    assert stats2["student_count"] == 100
    status = get_lab_dataset_status(test_db_session)
    assert status["students_no_index"] == 100
    assert status["students_indexed"] == 100


def test_lab_seeding_content_parity(test_db_session: Session):
    """Verify paired tables have identical rows and values."""
    seed_lab_dataset(test_db_session, size="small", seed=42)

    res_no = test_db_session.execute(
        text("SELECT id, student_number, gpa FROM examos_lab.lab_students_no_index ORDER BY id")
    ).fetchall()
    res_idx = test_db_session.execute(
        text("SELECT id, student_number, gpa FROM examos_lab.lab_students_indexed ORDER BY id")
    ).fetchall()

    assert len(res_no) == len(res_idx) == 100
    for r1, r2 in zip(res_no, res_idx):
        assert r1 == r2


# ==============================================================================
# 3. Benchmark Catalog & Execution Tests
# ==============================================================================

def test_benchmark_catalog_scenarios():
    """Verify required scenarios: selective lookup, JOIN, and aggregation."""
    required = {"selective_lookup", "join_students_enrollments", "aggregation_department_gpa"}
    assert required.issubset(set(BENCHMARK_SCENARIOS.keys()))

    for scenario_id, sc in BENCHMARK_SCENARIOS.items():
        assert sc.learning_objective
        assert sc.query_no_index
        assert sc.query_indexed
        assert "examos_lab" in sc.query_no_index
        assert "examos_lab" in sc.query_indexed


def test_execute_approved_benchmark_selective_lookup(test_db_session: Session):
    """Run selective lookup benchmark; verify real execution times and query plan."""
    seed_lab_dataset(test_db_session, size="small", seed=42)

    result = execute_approved_benchmark(
        db=test_db_session,
        scenario_id="selective_lookup",
        dataset_size="small",
        seed=42,
        repetitions=2,
    )

    assert result.scenario_id == "selective_lookup"
    assert result.no_index.median_time_ms > 0
    assert result.indexed.median_time_ms > 0
    assert len(result.no_index.repetition_times_ms) == 2
    assert len(result.indexed.repetition_times_ms) == 2

    # Verify query plan contains Node Type
    assert "Plan" in result.no_index.plan
    assert "Node Type" in result.no_index.plan["Plan"]
    assert "Plan" in result.indexed.plan
    assert "Node Type" in result.indexed.plan["Plan"]


def test_execute_approved_benchmark_join(test_db_session: Session):
    """Run JOIN benchmark between students and enrollments."""
    seed_lab_dataset(test_db_session, size="small", seed=42)

    result = execute_approved_benchmark(
        db=test_db_session,
        scenario_id="join_students_enrollments",
        dataset_size="small",
        seed=42,
        repetitions=1,
    )

    assert result.scenario_id == "join_students_enrollments"
    assert result.no_index.row_count > 0
    assert result.indexed.row_count == result.no_index.row_count


def test_execute_approved_benchmark_aggregation(test_db_session: Session):
    """Run Grouped Aggregation benchmark."""
    seed_lab_dataset(test_db_session, size="small", seed=42)

    result = execute_approved_benchmark(
        db=test_db_session,
        scenario_id="aggregation_department_gpa",
        dataset_size="small",
        seed=42,
        repetitions=1,
    )

    assert result.scenario_id == "aggregation_department_gpa"
    assert result.no_index.median_time_ms > 0
    assert result.indexed.median_time_ms > 0


def test_benchmark_validation_rejects_unknown_scenario(test_db_session: Session):
    """Reject unknown scenario code."""
    with pytest.raises(BenchmarkValidationError) as exc:
        execute_approved_benchmark(
            db=test_db_session,
            scenario_id="malicious_arbitrary_query",
        )
    assert "not in the approved benchmark catalog" in str(exc.value)


def test_benchmark_validation_rejects_invalid_size(test_db_session: Session):
    """Reject invalid dataset size."""
    with pytest.raises(BenchmarkValidationError) as exc:
        execute_approved_benchmark(
            db=test_db_session,
            scenario_id="selective_lookup",
            dataset_size="enormous_invalid_size",
        )
    assert "Dataset size" in str(exc.value)


def test_inspect_active_lab_dataset_detection(test_db_session: Session):
    """Detects small scale and reports consistency accurately."""
    stats = seed_lab_dataset(test_db_session, size="small", seed=42)
    assert stats["analyzed"] is True

    status = inspect_active_lab_dataset(test_db_session)
    assert status["detected_scale"] == "small"
    assert status["is_consistent"] is True
    assert status["counts"]["students_indexed"] == 100
    assert status["counts"]["enrollments_indexed"] == 400


def test_benchmark_rejects_scale_mismatch(test_db_session: Session):
    """Rejects execution when requested scale does not match actual active database rows."""
    seed_lab_dataset(test_db_session, size="small", seed=42)

    with pytest.raises(BenchmarkScaleMismatchError) as exc:
        execute_approved_benchmark(
            db=test_db_session,
            scenario_id="selective_lookup",
            dataset_size="medium",  # Database only has small
        )
    assert "Active lab dataset scale mismatch" in str(exc.value)
    assert "requested 'medium', but the database currently contains 'small'" in str(exc.value)
