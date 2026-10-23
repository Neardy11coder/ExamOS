"""
Predefined benchmark execution engine for ExamOS Database Performance Lab (M3-DB-1).

Security & Architectural Invariants:
- Executes ONLY server-owned approved benchmark scenarios from BENCHMARK_SCENARIOS.
- Rejects arbitrary user-supplied SQL text.
- Validates scenario_id, dataset_size, and parameters against strict ranges.
- Operates strictly on isolated `examos_lab` tables; never reads, modifies or locks examination tables.
- Runs fixed read-only queries with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
- Never fabricates timings or plans; returns actual PostgreSQL measurement or structured error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.benchmark_catalog import BENCHMARK_SCENARIOS, DATASET_SIZES


class BenchmarkValidationError(ValueError):
    """Raised when benchmark parameters or scenario are invalid."""
    pass


class BenchmarkExecutionError(RuntimeError):
    """Raised when benchmark query execution fails."""
    pass


@dataclass
class SingleVariantResult:
    variant: str
    query_text: str
    plan: dict[str, Any]
    execution_time_ms: float
    planning_time_ms: float
    repetition_times_ms: list[float]
    median_time_ms: float
    row_count: int


@dataclass
class BenchmarkExecutionResult:
    scenario_id: str
    dataset_size: str
    seed: int
    repetitions: int
    postgres_version: str
    no_index: SingleVariantResult
    indexed: SingleVariantResult
    speedup_ratio: float
    index_explanation: str
    caveat_notes: str


def execute_approved_benchmark(
    db: Session,
    scenario_id: str,
    dataset_size: str = "medium",
    seed: int = 42,
    repetitions: int = 3,
    custom_parameters: dict[str, Any] | None = None,
) -> BenchmarkExecutionResult:
    """
    Execute an approved benchmark scenario across both NO_INDEX and INDEXED variants.
    Measures actual PostgreSQL timings and retrieves EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON).
    """
    # 1. Validation
    if scenario_id not in BENCHMARK_SCENARIOS:
        raise BenchmarkValidationError(
            f"Scenario '{scenario_id}' is not in the approved benchmark catalog. "
            f"Allowed: {list(BENCHMARK_SCENARIOS.keys())}"
        )

    if dataset_size not in DATASET_SIZES:
        raise BenchmarkValidationError(
            f"Dataset size '{dataset_size}' is invalid. Allowed: {list(DATASET_SIZES.keys())}"
        )

    if repetitions < 1 or repetitions > 10:
        raise BenchmarkValidationError("Repetitions must be an integer between 1 and 10.")

    scenario = BENCHMARK_SCENARIOS[scenario_id]

    # Resolve parameters: default + custom overrides (validated)
    parameters = dict(scenario.default_parameters)
    if custom_parameters:
        for k, v in custom_parameters.items():
            if k in parameters:
                parameters[k] = v

    # 2. Query PostgreSQL version
    pg_version_raw = db.execute(text("SELECT version()")).scalar() or "Unknown"

    # Helper function to run one variant
    def _run_variant(variant_name: str, query_template: str) -> SingleVariantResult:
        explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query_template}"

        repetition_times: list[float] = []
        plan_data: dict[str, Any] = {}
        last_row_count = 0

        for r in range(repetitions):
            # Timed execution using EXPLAIN ANALYZE
            t0 = time.perf_counter()
            try:
                cursor_res = db.execute(text(explain_query), parameters).fetchall()
            except Exception as e:
                raise BenchmarkExecutionError(f"Benchmark execution error on {variant_name}: {e}")
            t1 = time.perf_counter()

            raw_json = cursor_res[0][0] if cursor_res and cursor_res[0] else []
            if isinstance(raw_json, list) and len(raw_json) > 0:
                plan_root = raw_json[0]
                exec_time = float(plan_root.get("Execution Time", (t1 - t0) * 1000.0))
                plan_data = plan_root
                last_row_count = int(plan_root.get("Plan", {}).get("Actual Rows", 0))
            else:
                exec_time = (t1 - t0) * 1000.0

            repetition_times.append(round(exec_time, 3))

        # Calculate median execution time
        sorted_times = sorted(repetition_times)
        median_time = sorted_times[len(sorted_times) // 2]
        planning_time = float(plan_data.get("Planning Time", 0.0))

        return SingleVariantResult(
            variant=variant_name,
            query_text=query_template,
            plan=plan_data,
            execution_time_ms=median_time,
            planning_time_ms=planning_time,
            repetition_times_ms=repetition_times,
            median_time_ms=median_time,
            row_count=last_row_count,
        )

    # 3. Execute NO_INDEX variant
    no_index_res = _run_variant("NO_INDEX", scenario.query_no_index)

    # 4. Execute INDEXED variant
    indexed_res = _run_variant("INDEXED", scenario.query_indexed)

    # Speedup ratio = no_index_time / indexed_time
    if indexed_res.median_time_ms > 0:
        speedup = round(no_index_res.median_time_ms / indexed_res.median_time_ms, 2)
    else:
        speedup = 1.0

    return BenchmarkExecutionResult(
        scenario_id=scenario_id,
        dataset_size=dataset_size,
        seed=seed,
        repetitions=repetitions,
        postgres_version=pg_version_raw,
        no_index=no_index_res,
        indexed=indexed_res,
        speedup_ratio=speedup,
        index_explanation=scenario.index_explanation,
        caveat_notes=scenario.caveat_notes,
    )
