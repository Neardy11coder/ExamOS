"""Pure educational OS CPU scheduling simulation engine for ExamOS.

Implements FCFS, Round Robin, non-preemptive Priority, and non-preemptive SJF
scheduling algorithms over abstract jobs without reading or modifying database tables.
"""

from dataclasses import dataclass
from typing import Sequence

from app.core.config import settings
from app.schemas.scheduler import (
    JobInput,
    JobMetrics,
    ScheduleResult,
    SchedulingAlgorithm,
    TimelineSegment,
    TimelineSegmentKind,
)


class SchedulerValidationError(ValueError):
    """Raised when input jobs or configuration violate scheduler rules."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        self.field = field


@dataclass
class _InternalJob:
    id: str
    arrival_time: int
    burst_time: int
    priority: int | None
    input_order: int
    remaining_burst: int
    first_start_time: int | None = None
    completion_time: int | None = None


def validate_scheduling_input(
    algorithm: SchedulingAlgorithm | str,
    jobs: Sequence[JobInput] | Sequence[dict],
    quantum: int | None = None,
    max_jobs: int | None = None,
) -> tuple[SchedulingAlgorithm, list[JobInput], int | None]:
    """Validate scheduler input jobs, algorithm, and quantum.

    Raises:
        SchedulerValidationError: with field-level identification if any rule is violated.
    """
    if max_jobs is None:
        max_jobs = settings.MAX_SCHEDULER_JOBS

    # Validate algorithm
    if isinstance(algorithm, str):
        try:
            algo_enum = SchedulingAlgorithm(algorithm)
        except ValueError:
            raise SchedulerValidationError(
                f"Invalid scheduling algorithm: {algorithm}. Must be one of {[a.value for a in SchedulingAlgorithm]}",
                field="algorithm",
            )
    elif isinstance(algorithm, SchedulingAlgorithm):
        algo_enum = algorithm
    else:
        raise SchedulerValidationError("Algorithm must be specified", field="algorithm")

    # Validate jobs list
    if not jobs:
        raise SchedulerValidationError("Job set cannot be empty.", field="jobs")

    if len(jobs) > max_jobs:
        raise SchedulerValidationError(
            f"Job count ({len(jobs)}) exceeds maximum configured limit of {max_jobs}.",
            field="jobs",
        )

    # Validate individual jobs and check duplicates
    validated_jobs: list[JobInput] = []
    seen_ids: set[str] = set()

    for idx, raw_job in enumerate(jobs):
        field_prefix = f"jobs[{idx}]"
        if isinstance(raw_job, JobInput):
            job = raw_job
        elif isinstance(raw_job, dict):
            try:
                job = JobInput(**raw_job)
            except Exception as e:
                raise SchedulerValidationError(f"Invalid job at index {idx}: {e}", field=field_prefix)
        else:
            raise SchedulerValidationError(f"Job at index {idx} must be a JobInput or dict", field=field_prefix)

        # Check unique identifier
        if job.id in seen_ids:
            raise SchedulerValidationError(
                f"Duplicate job identifier '{job.id}' found.",
                field=f"{field_prefix}.id",
            )
        seen_ids.add(job.id)

        # Priority check for Priority scheduling
        if algo_enum == SchedulingAlgorithm.PRIORITY:
            if job.priority is None:
                raise SchedulerValidationError(
                    f"Job '{job.id}' requires a priority value for Priority Scheduling.",
                    field=f"{field_prefix}.priority",
                )

        validated_jobs.append(job)

    # Validate quantum for Round Robin
    if algo_enum == SchedulingAlgorithm.ROUND_ROBIN:
        if quantum is None:
            raise SchedulerValidationError(
                "Round Robin scheduling requires a quantum value.",
                field="quantum",
            )
        if isinstance(quantum, bool) or not isinstance(quantum, int):
            raise SchedulerValidationError(
                "Round Robin quantum must be an integer.",
                field="quantum",
            )
        if quantum < 1:
            raise SchedulerValidationError(
                "Round Robin quantum must be an integer >= 1.",
                field="quantum",
            )

    return algo_enum, validated_jobs, quantum


def _append_segment(
    timeline: list[TimelineSegment],
    job_id: str | None,
    start: int,
    end: int,
    kind: TimelineSegmentKind,
) -> None:
    """Append a segment or merge with previous segment if contiguous and identical."""
    if start == end:
        return
    if timeline and timeline[-1].job_id == job_id and timeline[-1].kind == kind and timeline[-1].end == start:
        timeline[-1] = TimelineSegment(
            job_id=job_id,
            start=timeline[-1].start,
            end=end,
            kind=kind,
        )
    else:
        timeline.append(TimelineSegment(job_id=job_id, start=start, end=end, kind=kind))


def _compute_metrics(
    algorithm: SchedulingAlgorithm,
    quantum: int | None,
    internal_jobs: list[_InternalJob],
    timeline: list[TimelineSegment],
) -> ScheduleResult:
    """Calculate per-job and aggregate metrics according to requirements."""
    job_metrics_list: list[JobMetrics] = []
    total_burst_time = sum(j.burst_time for j in internal_jobs)
    earliest_arrival_time = min(j.arrival_time for j in internal_jobs)
    latest_completion_time = max(j.completion_time for j in internal_jobs) if internal_jobs else earliest_arrival_time

    measurement_window = latest_completion_time - earliest_arrival_time

    for j in internal_jobs:
        first_start = j.first_start_time if j.first_start_time is not None else 0
        comp = j.completion_time if j.completion_time is not None else 0
        tat = comp - j.arrival_time
        wt = tat - j.burst_time
        rt = first_start - j.arrival_time

        job_metrics_list.append(
            JobMetrics(
                job_id=j.id,
                arrival_time=j.arrival_time,
                burst_time=j.burst_time,
                priority=j.priority,
                first_start_time=first_start,
                completion_time=comp,
                turnaround_time=tat,
                waiting_time=wt,
                response_time=rt,
            )
        )

    num_jobs = len(job_metrics_list)
    avg_wt = sum(m.waiting_time for m in job_metrics_list) / num_jobs if num_jobs > 0 else 0.0
    avg_tat = sum(m.turnaround_time for m in job_metrics_list) / num_jobs if num_jobs > 0 else 0.0
    avg_rt = sum(m.response_time for m in job_metrics_list) / num_jobs if num_jobs > 0 else 0.0

    if measurement_window > 0:
        cpu_util = (total_burst_time / measurement_window) * 100.0
        throughput = num_jobs / measurement_window
    else:
        cpu_util = 0.0
        throughput = 0.0

    return ScheduleResult(
        algorithm=algorithm,
        quantum=quantum,
        jobs=job_metrics_list,
        timeline=timeline,
        total_burst_time=total_burst_time,
        earliest_arrival_time=earliest_arrival_time,
        latest_completion_time=latest_completion_time,
        measurement_window=measurement_window,
        cpu_utilization_percent=round(cpu_util, 4),
        average_waiting_time=round(avg_wt, 4),
        average_turnaround_time=round(avg_tat, 4),
        average_response_time=round(avg_rt, 4),
        throughput=round(throughput, 4),
    )


def _simulate_fcfs(internal_jobs: list[_InternalJob]) -> list[TimelineSegment]:
    """FCFS: Non-preemptive. Earliest arrival first; tie-break by input_order."""
    timeline: list[TimelineSegment] = []
    # Sort unadmitted jobs by arrival_time, then input_order
    unadmitted = sorted(internal_jobs, key=lambda j: (j.arrival_time, j.input_order))
    current_time = 0

    ready_queue: list[_InternalJob] = []

    while unadmitted or ready_queue:
        # Move all jobs arriving <= current_time to ready queue
        while unadmitted and unadmitted[0].arrival_time <= current_time:
            ready_queue.append(unadmitted.pop(0))

        if not ready_queue:
            # CPU idle until next job arrives
            next_arrival = unadmitted[0].arrival_time
            _append_segment(timeline, None, current_time, next_arrival, TimelineSegmentKind.IDLE)
            current_time = next_arrival
            continue

        # Ready queue is maintained in FCFS order (earliest arrival, then input_order)
        # Note: sorting ready queue ensures deterministic tie-breaking
        ready_queue.sort(key=lambda j: (j.arrival_time, j.input_order))
        job = ready_queue.pop(0)

        job.first_start_time = current_time
        start_time = current_time
        current_time += job.burst_time
        job.completion_time = current_time
        job.remaining_burst = 0
        _append_segment(timeline, job.id, start_time, current_time, TimelineSegmentKind.EXECUTION)

    return timeline


def _simulate_sjf(internal_jobs: list[_InternalJob]) -> list[TimelineSegment]:
    """SJF: Non-preemptive. Shortest burst first; tie-break by arrival_time, then input_order."""
    timeline: list[TimelineSegment] = []
    unadmitted = sorted(internal_jobs, key=lambda j: (j.arrival_time, j.input_order))
    current_time = 0
    ready_pool: list[_InternalJob] = []

    while unadmitted or ready_pool:
        while unadmitted and unadmitted[0].arrival_time <= current_time:
            ready_pool.append(unadmitted.pop(0))

        if not ready_pool:
            next_arrival = unadmitted[0].arrival_time
            _append_segment(timeline, None, current_time, next_arrival, TimelineSegmentKind.IDLE)
            current_time = next_arrival
            continue

        # Shortest burst first; tie-break: arrival_time, then input_order
        ready_pool.sort(key=lambda j: (j.burst_time, j.arrival_time, j.input_order))
        job = ready_pool.pop(0)

        job.first_start_time = current_time
        start_time = current_time
        current_time += job.burst_time
        job.completion_time = current_time
        job.remaining_burst = 0
        _append_segment(timeline, job.id, start_time, current_time, TimelineSegmentKind.EXECUTION)

    return timeline


def _simulate_priority(internal_jobs: list[_InternalJob]) -> list[TimelineSegment]:
    """Priority: Non-preemptive. Lowest numeric priority value first; tie-break: arrival_time, input_order."""
    timeline: list[TimelineSegment] = []
    unadmitted = sorted(internal_jobs, key=lambda j: (j.arrival_time, j.input_order))
    current_time = 0
    ready_pool: list[_InternalJob] = []

    while unadmitted or ready_pool:
        while unadmitted and unadmitted[0].arrival_time <= current_time:
            ready_pool.append(unadmitted.pop(0))

        if not ready_pool:
            next_arrival = unadmitted[0].arrival_time
            _append_segment(timeline, None, current_time, next_arrival, TimelineSegmentKind.IDLE)
            current_time = next_arrival
            continue

        # Priority: lowest numeric priority first; tie-break: arrival_time, input_order
        ready_pool.sort(key=lambda j: (j.priority if j.priority is not None else 0, j.arrival_time, j.input_order))
        job = ready_pool.pop(0)

        job.first_start_time = current_time
        start_time = current_time
        current_time += job.burst_time
        job.completion_time = current_time
        job.remaining_burst = 0
        _append_segment(timeline, job.id, start_time, current_time, TimelineSegmentKind.EXECUTION)

    return timeline


def _simulate_round_robin(internal_jobs: list[_InternalJob], quantum: int) -> list[TimelineSegment]:
    """Round Robin: Preemptive with integer quantum.

    Boundary rule (docs/06 §3 & §7):
    At a time-slice boundary, first enqueue all jobs arriving at that exact time
    in ascending input_order, then enqueue the unfinished running job at the tail.
    If the running job completes exactly at the boundary, it is not re-enqueued.
    When no job is ready, record an idle interval until the next arrival.
    """
    timeline: list[TimelineSegment] = []
    unadmitted = sorted(internal_jobs, key=lambda j: (j.arrival_time, j.input_order))
    current_time = 0
    ready_queue: list[_InternalJob] = []

    while unadmitted or ready_queue:
        # Check newly arrived jobs at current_time
        while unadmitted and unadmitted[0].arrival_time <= current_time:
            ready_queue.append(unadmitted.pop(0))

        if not ready_queue:
            next_arrival = unadmitted[0].arrival_time
            _append_segment(timeline, None, current_time, next_arrival, TimelineSegmentKind.IDLE)
            current_time = next_arrival
            continue

        job = ready_queue.pop(0)
        if job.first_start_time is None:
            job.first_start_time = current_time

        run_duration = min(quantum, job.remaining_burst)
        start_time = current_time
        current_time += run_duration
        job.remaining_burst -= run_duration

        _append_segment(timeline, job.id, start_time, current_time, TimelineSegmentKind.EXECUTION)

        # At the time-slice boundary (current_time):
        # 1. Admit all jobs arriving strictly between start_time and current_time
        # (in unadmitted, their arrival_time <= current_time) in ascending input_order.
        while unadmitted and unadmitted[0].arrival_time <= current_time:
            ready_queue.append(unadmitted.pop(0))

        # 2. If the running job finished, record its completion. Otherwise, re-enqueue at tail.
        if job.remaining_burst == 0:
            job.completion_time = current_time
        else:
            ready_queue.append(job)

    return timeline


def simulate(
    algorithm: SchedulingAlgorithm | str,
    jobs: Sequence[JobInput] | Sequence[dict],
    quantum: int | None = None,
    max_jobs: int | None = None,
) -> ScheduleResult:
    """Pure scheduling engine entrypoint.

    Simulates the requested algorithm over the provided jobs.
    Does not access DB, session, or HTTP request context.
    """
    algo_enum, validated_jobs, validated_quantum = validate_scheduling_input(
        algorithm=algorithm,
        jobs=jobs,
        quantum=quantum,
        max_jobs=max_jobs,
    )

    # Construct internal job representations preserving input_order
    internal_jobs = [
        _InternalJob(
            id=j.id,
            arrival_time=j.arrival_time,
            burst_time=j.burst_time,
            priority=j.priority,
            input_order=idx,
            remaining_burst=j.burst_time,
        )
        for idx, j in enumerate(validated_jobs)
    ]

    if algo_enum == SchedulingAlgorithm.FCFS:
        timeline = _simulate_fcfs(internal_jobs)
    elif algo_enum == SchedulingAlgorithm.SJF:
        timeline = _simulate_sjf(internal_jobs)
    elif algo_enum == SchedulingAlgorithm.PRIORITY:
        timeline = _simulate_priority(internal_jobs)
    elif algo_enum == SchedulingAlgorithm.ROUND_ROBIN:
        assert validated_quantum is not None
        timeline = _simulate_round_robin(internal_jobs, validated_quantum)
    else:
        raise SchedulerValidationError(f"Unsupported algorithm: {algo_enum}", field="algorithm")

    # Restore internal_jobs to original input order for metrics reporting
    internal_jobs_by_id = {j.id: j for j in internal_jobs}
    ordered_internal_jobs = [internal_jobs_by_id[j.id] for j in validated_jobs]

    return _compute_metrics(
        algorithm=algo_enum,
        quantum=validated_quantum,
        internal_jobs=ordered_internal_jobs,
        timeline=timeline,
    )
