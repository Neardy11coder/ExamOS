"""
Database Performance Lab API endpoints (M3-DB-UI-1 / docs/04_API_CONTRACT.md § 7).

Restricted to FACULTY_ADMIN.
Allows faculty to:
- Browse server-approved benchmark scenarios and dataset sizes.
- Execute approved read-only benchmarks on isolated examos_lab tables.
- View recorded benchmark run history.
Enforces CSRF protection on POST execution.
Rejects arbitrary user SQL and validates all parameters against fixed bounds.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_faculty, validate_csrf
from app.models.benchmark import BenchmarkRun
from app.models.user import User
from app.schemas.database_lab import (
    BenchmarkCatalogResponse,
    BenchmarkExecutionResponse,
    BenchmarkRunHistoryItem,
    BenchmarkRunRequest,
    BenchmarkScenarioSummary,
    DatasetSizeOption,
    SingleVariantExecutionData,
)
from app.services.benchmark_catalog import BENCHMARK_SCENARIOS, DATASET_SIZES
from app.services.benchmark_service import (
    BenchmarkExecutionError,
    BenchmarkValidationError,
    execute_approved_benchmark,
)

router = APIRouter(prefix="/labs/db", tags=["database-lab"])


@router.get(
    "/benchmarks",
    response_model=BenchmarkCatalogResponse,
    status_code=status.HTTP_200_OK,
)
def get_benchmark_catalog(
    current_user: Annotated[User, Depends(require_faculty)],
) -> BenchmarkCatalogResponse:
    """List approved benchmark scenarios and dataset scales.

    Faculty/admin only.
    Returns scenarios with descriptions, learning objectives, table references, and default parameters.
    Does not expose arbitrary executable SQL.
    """
    scenarios: list[BenchmarkScenarioSummary] = [
        BenchmarkScenarioSummary(
            scenario_id=s.scenario_id,
            title=s.title,
            description=s.description,
            learning_objective=s.learning_objective,
            relevant_tables=s.relevant_tables,
            allowed_dataset_sizes=s.allowed_dataset_sizes,
            default_parameters=s.default_parameters,
            index_explanation=s.index_explanation,
            caveat_notes=s.caveat_notes,
        )
        for s in BENCHMARK_SCENARIOS.values()
    ]

    dataset_sizes: list[DatasetSizeOption] = [
        DatasetSizeOption(
            size_key=k,
            label=v["label"],
            student_count=v["student_count"],
            enrollments_per_student=v["enrollments_per_student"],
        )
        for k, v in DATASET_SIZES.items()
    ]

    return BenchmarkCatalogResponse(
        scenarios=scenarios,
        dataset_sizes=dataset_sizes,
    )


@router.post(
    "/benchmarks/run",
    response_model=BenchmarkExecutionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(validate_csrf)],
)
def run_benchmark(
    request: BenchmarkRunRequest,
    current_user: Annotated[User, Depends(require_faculty)],
    db: Annotated[Session, Depends(get_db)],
) -> BenchmarkExecutionResponse:
    """Execute an approved benchmark scenario against isolated examos_lab tables.

    Faculty/admin only. Enforces CSRF token check.
    Runs EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) on approved fixed queries.
    Persists an execution audit record into public.benchmark_runs.
    """
    try:
        result = execute_approved_benchmark(
            db=db,
            scenario_id=request.scenario_id,
            dataset_size=request.dataset_size,
            seed=request.seed,
            repetitions=request.repetitions,
            custom_parameters=request.custom_parameters,
        )
    except BenchmarkValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "BENCHMARK_VALIDATION_ERROR",
                    "message": str(e),
                }
            },
        )
    except BenchmarkExecutionError as e:
        # Record failed run in audit log before raising
        failed_run = BenchmarkRun(
            requested_by=current_user.id,
            scenario_code=request.scenario_id,
            dataset_size=request.dataset_size,
            seed=request.seed,
            variant="COMPARISON",
            postgres_version="Unknown",
            run_metadata={
                "repetitions": request.repetitions,
                "custom_parameters": request.custom_parameters or {},
            },
            plan_output=None,
            status="FAILED",
            error_summary=str(e),
        )
        db.add(failed_run)
        db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "BENCHMARK_EXECUTION_ERROR",
                    "message": "Benchmark query failed on the database lab engine.",
                }
            },
        )

    # Persist successful run record
    run_record = BenchmarkRun(
        requested_by=current_user.id,
        scenario_code=result.scenario_id,
        dataset_size=result.dataset_size,
        seed=result.seed,
        variant="COMPARISON",
        postgres_version=result.postgres_version,
        run_metadata={
            "repetitions": result.repetitions,
            "speedup_ratio": result.speedup_ratio,
            "no_index": {
                "median_time_ms": result.no_index.median_time_ms,
                "planning_time_ms": result.no_index.planning_time_ms,
                "repetition_times_ms": result.no_index.repetition_times_ms,
                "row_count": result.no_index.row_count,
            },
            "indexed": {
                "median_time_ms": result.indexed.median_time_ms,
                "planning_time_ms": result.indexed.planning_time_ms,
                "repetition_times_ms": result.indexed.repetition_times_ms,
                "row_count": result.indexed.row_count,
            },
        },
        plan_output={
            "no_index_plan": result.no_index.plan,
            "indexed_plan": result.indexed.plan,
        },
        status="SUCCEEDED",
        error_summary=None,
    )
    db.add(run_record)
    db.commit()
    db.refresh(run_record)

    return BenchmarkExecutionResponse(
        run_id=run_record.id,
        scenario_id=result.scenario_id,
        dataset_size=result.dataset_size,
        seed=result.seed,
        repetitions=result.repetitions,
        postgres_version=result.postgres_version,
        no_index=SingleVariantExecutionData(
            variant=result.no_index.variant,
            query_text=result.no_index.query_text,
            plan=result.no_index.plan,
            execution_time_ms=result.no_index.execution_time_ms,
            planning_time_ms=result.no_index.planning_time_ms,
            repetition_times_ms=result.no_index.repetition_times_ms,
            median_time_ms=result.no_index.median_time_ms,
            row_count=result.no_index.row_count,
        ),
        indexed=SingleVariantExecutionData(
            variant=result.indexed.variant,
            query_text=result.indexed.query_text,
            plan=result.indexed.plan,
            execution_time_ms=result.indexed.execution_time_ms,
            planning_time_ms=result.indexed.planning_time_ms,
            repetition_times_ms=result.indexed.repetition_times_ms,
            median_time_ms=result.indexed.median_time_ms,
            row_count=result.indexed.row_count,
        ),
        speedup_ratio=result.speedup_ratio,
        index_explanation=result.index_explanation,
        caveat_notes=result.caveat_notes,
        created_at=run_record.created_at,
    )


@router.get(
    "/benchmarks/runs",
    response_model=list[BenchmarkRunHistoryItem],
    status_code=status.HTTP_200_OK,
)
def get_benchmark_history(
    current_user: Annotated[User, Depends(require_faculty)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
) -> list[BenchmarkRunHistoryItem]:
    """Retrieve recent benchmark execution history.

    Faculty/admin only.
    Ordered by creation date descending.
    """
    stmt = (
        select(BenchmarkRun)
        .order_by(BenchmarkRun.created_at.desc())
        .limit(limit)
    )
    records = db.execute(stmt).scalars().all()

    items: list[BenchmarkRunHistoryItem] = []
    for r in records:
        meta = r.run_metadata or {}
        speedup = meta.get("speedup_ratio")
        no_idx_med = meta.get("no_index", {}).get("median_time_ms")
        idx_med = meta.get("indexed", {}).get("median_time_ms")

        items.append(
            BenchmarkRunHistoryItem(
                run_id=r.id,
                scenario_code=r.scenario_code,
                dataset_size=r.dataset_size,
                seed=r.seed,
                variant=r.variant,
                status=r.status,
                speedup_ratio=speedup,
                no_index_median_ms=no_idx_med,
                indexed_median_ms=idx_med,
                created_at=r.created_at,
            )
        )
    return items


@router.get(
    "/benchmarks/runs/{run_id}",
    response_model=BenchmarkExecutionResponse,
    status_code=status.HTTP_200_OK,
)
def get_benchmark_run_detail(
    run_id: uuid.UUID,
    current_user: Annotated[User, Depends(require_faculty)],
    db: Annotated[Session, Depends(get_db)],
) -> BenchmarkExecutionResponse:
    """Retrieve full details of a specific benchmark run, including stored plans and parameters.

    Faculty/admin only.
    """
    run_record = db.get(BenchmarkRun, run_id)
    if not run_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "RUN_NOT_FOUND", "message": "Benchmark run not found."}},
        )

    meta = run_record.run_metadata or {}
    no_idx_meta = meta.get("no_index", {})
    idx_meta = meta.get("indexed", {})
    plans = run_record.plan_output or {}

    scenario = BENCHMARK_SCENARIOS.get(run_record.scenario_code)
    explanation = scenario.index_explanation if scenario else "Scenario details unavailable."
    caveat = scenario.caveat_notes if scenario else "Scenario caveats unavailable."
    q_no_idx = scenario.query_no_index if scenario else "N/A"
    q_idx = scenario.query_indexed if scenario else "N/A"

    return BenchmarkExecutionResponse(
        run_id=run_record.id,
        scenario_id=run_record.scenario_code,
        dataset_size=run_record.dataset_size,
        seed=run_record.seed,
        repetitions=meta.get("repetitions", 1),
        postgres_version=run_record.postgres_version,
        no_index=SingleVariantExecutionData(
            variant="NO_INDEX",
            query_text=q_no_idx,
            plan=plans.get("no_index_plan", {}),
            execution_time_ms=no_idx_meta.get("median_time_ms", 0.0),
            planning_time_ms=no_idx_meta.get("planning_time_ms", 0.0),
            repetition_times_ms=no_idx_meta.get("repetition_times_ms", []),
            median_time_ms=no_idx_meta.get("median_time_ms", 0.0),
            row_count=no_idx_meta.get("row_count", 0),
        ),
        indexed=SingleVariantExecutionData(
            variant="INDEXED",
            query_text=q_idx,
            plan=plans.get("indexed_plan", {}),
            execution_time_ms=idx_meta.get("median_time_ms", 0.0),
            planning_time_ms=idx_meta.get("planning_time_ms", 0.0),
            repetition_times_ms=idx_meta.get("repetition_times_ms", []),
            median_time_ms=idx_meta.get("median_time_ms", 0.0),
            row_count=idx_meta.get("row_count", 0),
        ),
        speedup_ratio=meta.get("speedup_ratio", 1.0),
        index_explanation=explanation,
        caveat_notes=caveat,
        created_at=run_record.created_at,
    )
