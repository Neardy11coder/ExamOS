from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SchedulingAlgorithm(str, Enum):
    FCFS = "FCFS"
    ROUND_ROBIN = "ROUND_ROBIN"
    PRIORITY = "PRIORITY"
    SJF = "SJF"


class JobInput(BaseModel):
    id: str = Field(..., min_length=1, description="Unique non-empty job identifier")
    arrival_time: int = Field(..., ge=0, description="Job arrival time (integer >= 0)")
    burst_time: int = Field(..., ge=1, description="Job CPU burst time (integer >= 1)")
    priority: int | None = Field(default=None, description="Priority value for Priority Scheduling")

    model_config = ConfigDict(extra="forbid")

    @field_validator("id")
    @classmethod
    def validate_id_not_whitespace(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Job id cannot be empty or whitespace only.")
        return trimmed

    @field_validator("arrival_time", "burst_time", "priority", mode="before")
    @classmethod
    def reject_bool_and_non_int(cls, v: any) -> any:
        # In Python, bool is a subclass of int. We must explicitly reject bool.
        if isinstance(v, bool):
            raise ValueError("Value must be an integer, not a boolean.")
        if v is not None and not isinstance(v, int):
            raise ValueError("Value must be an integer.")
        return v


class TimelineSegmentKind(str, Enum):
    EXECUTION = "EXECUTION"
    IDLE = "IDLE"


class TimelineSegment(BaseModel):
    job_id: str | None = Field(default=None, description="Job identifier, or null if IDLE")
    start: int = Field(..., ge=0, description="Start time of segment (inclusive)")
    end: int = Field(..., ge=0, description="End time of segment (exclusive)")
    kind: TimelineSegmentKind = Field(default=TimelineSegmentKind.EXECUTION, description="Segment kind")

    model_config = ConfigDict(extra="forbid")


class JobMetrics(BaseModel):
    job_id: str = Field(..., description="Job identifier")
    arrival_time: int = Field(..., ge=0, description="Arrival time")
    burst_time: int = Field(..., ge=1, description="Burst duration")
    priority: int | None = Field(default=None, description="Priority value if provided")
    first_start_time: int = Field(..., ge=0, description="First instant the job receives the CPU")
    completion_time: int = Field(..., ge=0, description="Instant the job finishes its burst")
    turnaround_time: int = Field(..., ge=0, description="Turnaround time (completion - arrival)")
    waiting_time: int = Field(..., ge=0, description="Waiting time (turnaround - burst)")
    response_time: int = Field(..., ge=0, description="Response time (first_start - arrival)")

    model_config = ConfigDict(extra="forbid")


class ScheduleResult(BaseModel):
    algorithm: SchedulingAlgorithm = Field(..., description="Executed scheduling algorithm")
    quantum: int | None = Field(default=None, description="Time quantum used for Round Robin")
    jobs: list[JobMetrics] = Field(..., description="Per-job scheduling metrics")
    timeline: list[TimelineSegment] = Field(..., description="Chronological timeline segments")
    total_burst_time: int = Field(..., ge=0, description="Sum of all job burst times")
    earliest_arrival_time: int = Field(..., ge=0, description="Earliest job arrival time")
    latest_completion_time: int = Field(..., ge=0, description="Latest job completion time")
    measurement_window: int = Field(..., ge=0, description="latest_completion_time - earliest_arrival_time")
    cpu_utilization_percent: float = Field(..., ge=0.0, le=100.0, description="CPU utilization percentage")
    average_waiting_time: float = Field(..., ge=0.0, description="Arithmetic mean of waiting times")
    average_turnaround_time: float = Field(..., ge=0.0, description="Arithmetic mean of turnaround times")
    average_response_time: float = Field(..., ge=0.0, description="Arithmetic mean of response times")
    throughput: float = Field(..., ge=0.0, description="Jobs completed per unit time in measurement window")

    model_config = ConfigDict(extra="forbid")


class SchedulerRunRequest(BaseModel):
    algorithm: SchedulingAlgorithm = Field(..., description="Scheduling algorithm to simulate")
    quantum: int | None = Field(default=None, description="Required for ROUND_ROBIN (integer >= 1)")
    jobs: list[JobInput] = Field(..., description="List of jobs to simulate")

    model_config = ConfigDict(extra="forbid")

    @field_validator("quantum", mode="before")
    @classmethod
    def reject_bool_quantum(cls, v: any) -> any:
        if isinstance(v, bool):
            raise ValueError("quantum must be an integer, not a boolean.")
        if v is not None and not isinstance(v, int):
            raise ValueError("quantum must be an integer.")
        return v
