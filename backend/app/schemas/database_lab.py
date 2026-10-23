"""
Pydantic schemas for Database Performance Lab (M3-DB-UI-1 / docs/04_API_CONTRACT.md § 7).

Defines request/response data structures for:
- Listing benchmark catalog scenarios
- Executing approved benchmarks
- Inspecting benchmark run results and history
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BenchmarkScenarioSummary(BaseModel):
    scenario_id: str = Field(..., description="Unique scenario identifier in the catalog")
    title: str = Field(..., description="Human-readable title")
    description: str = Field(..., description="Scenario description")
    learning_objective: str = Field(..., description="Educational goal of this scenario")
    relevant_tables: list[str] = Field(..., description="Tables accessed in examos_lab")
    allowed_dataset_sizes: list[str] = Field(..., description="Supported dataset sizes")
    default_parameters: dict[str, Any] = Field(default_factory=dict, description="Default parameters")
    index_explanation: str = Field(..., description="Why indexing impacts this scenario")
    caveat_notes: str = Field(..., description="Edge cases, small table effects, or planner notes")

    model_config = ConfigDict(extra="forbid")


class DatasetSizeOption(BaseModel):
    size_key: str = Field(..., description="Key identifier (e.g., small, medium, large)")
    label: str = Field(..., description="Display label with approximate row counts")
    student_count: int = Field(..., description="Number of student records")
    enrollments_per_student: int = Field(..., description="Enrollments generated per student")

    model_config = ConfigDict(extra="forbid")


class ActiveDatasetStatus(BaseModel):
    detected_scale: str = Field(..., description="Detected scale: small, medium, large, inconsistent, or empty")
    is_consistent: bool = Field(..., description="True if paired tables have matching row counts")
    counts: dict[str, int] = Field(..., description="Actual row counts across all 4 lab tables")
    description: str = Field(..., description="Human-readable description of active dataset state")

    model_config = ConfigDict(extra="forbid")


class BenchmarkCatalogResponse(BaseModel):
    scenarios: list[BenchmarkScenarioSummary] = Field(..., description="Approved benchmark scenarios")
    dataset_sizes: list[DatasetSizeOption] = Field(..., description="Available dataset sizes")
    active_dataset: ActiveDatasetStatus = Field(..., description="Actual active dataset state in examos_lab")

    model_config = ConfigDict(extra="forbid")


class BenchmarkRunRequest(BaseModel):
    scenario_id: str = Field(..., description="Approved scenario identifier from catalog")
    dataset_size: str = Field(default="medium", description="Dataset size: small, medium, large")
    seed: int = Field(default=42, ge=0, le=2147483647, description="Deterministic seed for reproducibility")
    repetitions: int = Field(default=3, ge=1, le=10, description="Measurement repetitions (1 to 10)")
    custom_parameters: dict[str, Any] | None = Field(
        default=None,
        description="Optional parameter overrides matching scenario default keys",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("seed", "repetitions", mode="before")
    @classmethod
    def reject_bool(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError("Value must be an integer, not a boolean.")
        if v is not None and not isinstance(v, int):
            raise ValueError("Value must be an integer.")
        return v


class SingleVariantExecutionData(BaseModel):
    variant: str = Field(..., description="Variant name: NO_INDEX or INDEXED")
    query_text: str = Field(..., description="Server-owned query template executed")
    plan: dict[str, Any] = Field(default_factory=dict, description="Parsed PostgreSQL EXPLAIN JSON plan")
    execution_time_ms: float = Field(..., ge=0.0, description="Median execution time in milliseconds")
    planning_time_ms: float = Field(..., ge=0.0, description="Planning time in milliseconds")
    repetition_times_ms: list[float] = Field(default_factory=list, description="All repetition execution times")
    median_time_ms: float = Field(..., ge=0.0, description="Median execution time in milliseconds")
    row_count: int = Field(..., ge=0, description="Actual rows returned/processed")

    model_config = ConfigDict(extra="forbid")


class BenchmarkExecutionResponse(BaseModel):
    run_id: uuid.UUID = Field(..., description="Unique ID of persisted benchmark run")
    scenario_id: str = Field(..., description="Executed scenario identifier")
    dataset_size: str = Field(..., description="Dataset size scale")
    seed: int = Field(..., description="Random seed used")
    repetitions: int = Field(..., description="Repetitions executed")
    postgres_version: str = Field(..., description="PostgreSQL engine version")
    no_index: SingleVariantExecutionData = Field(..., description="Results without index")
    indexed: SingleVariantExecutionData = Field(..., description="Results with index")
    speedup_ratio: float = Field(..., ge=0.0, description="Ratio of no_index_time / indexed_time")
    index_explanation: str = Field(..., description="Educational explanation of index effect")
    caveat_notes: str = Field(..., description="Caveats and planner behavior notes")
    created_at: datetime = Field(..., description="Timestamp of execution")

    model_config = ConfigDict(extra="forbid")


class BenchmarkRunHistoryItem(BaseModel):
    run_id: uuid.UUID = Field(..., description="Run identifier")
    scenario_code: str = Field(..., description="Scenario code")
    dataset_size: str = Field(..., description="Dataset size")
    seed: int = Field(..., description="Seed")
    variant: str = Field(..., description="Variant: COMPARISON, etc.")
    status: str = Field(..., description="Execution status")
    speedup_ratio: float | None = Field(default=None, description="Measured speedup ratio if succeeded")
    no_index_median_ms: float | None = Field(default=None, description="No index median time")
    indexed_median_ms: float | None = Field(default=None, description="Indexed median time")
    created_at: datetime = Field(..., description="Execution timestamp")

    model_config = ConfigDict(extra="forbid")
