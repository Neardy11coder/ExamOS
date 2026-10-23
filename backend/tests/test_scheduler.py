import pytest
from app.schemas.scheduler import (
    JobInput,
    ScheduleResult,
    SchedulingAlgorithm,
    TimelineSegmentKind,
)
from app.services.scheduler_service import (
    SchedulerValidationError,
    simulate,
    validate_scheduling_input,
)


# ==============================================================================
# Spec Reference Cases (docs/06_OS_SCHEDULING_SIMULATOR.md §7)
# ==============================================================================

def test_reference_case_a_fcfs_with_idle():
    """Case A from docs/06 §7:
    Job A: arrival=0, burst=3, priority=2
    Job B: arrival=5, burst=2, priority=1
    Timeline: A [0,3), IDLE [3,5), B [5,7)
    Window=7, total_burst=5, CPU util = 5/7 * 100 ≈ 71.4286%
    """
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=3, priority=2),
        JobInput(id="B", arrival_time=5, burst_time=2, priority=1),
    ]
    res = simulate(SchedulingAlgorithm.FCFS, jobs)

    # Invariants & Run Metrics
    assert res.algorithm == SchedulingAlgorithm.FCFS
    assert res.total_burst_time == 5
    assert res.earliest_arrival_time == 0
    assert res.latest_completion_time == 7
    assert res.measurement_window == 7
    assert abs(res.cpu_utilization_percent - 71.4286) < 0.01

    # Timeline segments
    assert len(res.timeline) == 3
    assert res.timeline[0].job_id == "A"
    assert res.timeline[0].start == 0
    assert res.timeline[0].end == 3
    assert res.timeline[0].kind == TimelineSegmentKind.EXECUTION

    assert res.timeline[1].job_id is None
    assert res.timeline[1].start == 3
    assert res.timeline[1].end == 5
    assert res.timeline[1].kind == TimelineSegmentKind.IDLE

    assert res.timeline[2].job_id == "B"
    assert res.timeline[2].start == 5
    assert res.timeline[2].end == 7
    assert res.timeline[2].kind == TimelineSegmentKind.EXECUTION

    # Per-job metrics
    job_a = next(j for j in res.jobs if j.job_id == "A")
    assert job_a.first_start_time == 0
    assert job_a.completion_time == 3
    assert job_a.turnaround_time == 3
    assert job_a.waiting_time == 0
    assert job_a.response_time == 0

    job_b = next(j for j in res.jobs if j.job_id == "B")
    assert job_b.first_start_time == 5
    assert job_b.completion_time == 7
    assert job_b.turnaround_time == 2
    assert job_b.waiting_time == 0
    assert job_b.response_time == 0


def test_reference_case_b_round_robin():
    """Case B from docs/06 §7:
    Quantum = 2
    Job A: arrival=0, burst=5
    Job B: arrival=1, burst=3
    Timeline: A [0,2), B [2,4), A [4,6), B [6,7), A [7,8)
    Job A: start=0, completion=8, tat=8, wt=3, rt=0
    Job B: start=2, completion=7, tat=6, wt=3, rt=1
    """
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=5),
        JobInput(id="B", arrival_time=1, burst_time=3),
    ]
    res = simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=2)

    assert res.total_burst_time == 8
    assert res.earliest_arrival_time == 0
    assert res.latest_completion_time == 8
    assert res.measurement_window == 8
    assert res.cpu_utilization_percent == 100.0

    expected_timeline = [
        ("A", 0, 2),
        ("B", 2, 4),
        ("A", 4, 6),
        ("B", 6, 7),
        ("A", 7, 8),
    ]
    assert len(res.timeline) == len(expected_timeline)
    for seg, (expected_id, exp_start, exp_end) in zip(res.timeline, expected_timeline):
        assert seg.job_id == expected_id
        assert seg.start == exp_start
        assert seg.end == exp_end

    job_a = next(j for j in res.jobs if j.job_id == "A")
    assert job_a.first_start_time == 0
    assert job_a.completion_time == 8
    assert job_a.turnaround_time == 8
    assert job_a.waiting_time == 3
    assert job_a.response_time == 0

    job_b = next(j for j in res.jobs if j.job_id == "B")
    assert job_b.first_start_time == 2
    assert job_b.completion_time == 7
    assert job_b.turnaround_time == 6
    assert job_b.waiting_time == 3
    assert job_b.response_time == 1

    assert res.average_waiting_time == 3.0
    assert res.average_turnaround_time == 7.0
    assert res.average_response_time == 0.5


def test_reference_case_c_non_preemptive_priority():
    """Case C from docs/06 §7:
    Job A: arrival=0, burst=4, priority=3
    Job B: arrival=1, burst=2, priority=1
    Job C: arrival=1, burst=1, priority=2
    Timeline: A [0,4), B [4,6), C [6,7)
    Metrics:
    A: start=0, completion=4, tat=4, wt=0, rt=0
    B: start=4, completion=6, tat=5, wt=3, rt=3
    C: start=6, completion=7, tat=6, wt=5, rt=5
    """
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=4, priority=3),
        JobInput(id="B", arrival_time=1, burst_time=2, priority=1),
        JobInput(id="C", arrival_time=1, burst_time=1, priority=2),
    ]
    res = simulate(SchedulingAlgorithm.PRIORITY, jobs)

    assert len(res.timeline) == 3
    assert [(s.job_id, s.start, s.end) for s in res.timeline] == [
        ("A", 0, 4),
        ("B", 4, 6),
        ("C", 6, 7),
    ]

    job_a = next(j for j in res.jobs if j.job_id == "A")
    assert (job_a.first_start_time, job_a.completion_time, job_a.turnaround_time, job_a.waiting_time, job_a.response_time) == (0, 4, 4, 0, 0)

    job_b = next(j for j in res.jobs if j.job_id == "B")
    assert (job_b.first_start_time, job_b.completion_time, job_b.turnaround_time, job_b.waiting_time, job_b.response_time) == (4, 6, 5, 3, 3)

    job_c = next(j for j in res.jobs if j.job_id == "C")
    assert (job_c.first_start_time, job_c.completion_time, job_c.turnaround_time, job_c.waiting_time, job_c.response_time) == (6, 7, 6, 5, 5)


# ==============================================================================
# SJF Tests (Non-preemptive)
# ==============================================================================

def test_sjf_non_preemptive():
    """SJF: shortest job first among available jobs.
    Job A: arrival=0, burst=5
    Job B: arrival=1, burst=2
    Job C: arrival=2, burst=1
    Job D: arrival=3, burst=4
    At t=0: only A is ready -> runs [0,5).
    At t=5: B (burst=2), C (burst=1), D (burst=4) are all ready.
    Shortest is C (burst=1) -> runs [5,6).
    At t=6: B (burst=2), D (burst=4) are ready.
    Shortest is B (burst=2) -> runs [6,8).
    At t=8: D (burst=4) -> runs [8,12).
    """
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=5),
        JobInput(id="B", arrival_time=1, burst_time=2),
        JobInput(id="C", arrival_time=2, burst_time=1),
        JobInput(id="D", arrival_time=3, burst_time=4),
    ]
    res = simulate(SchedulingAlgorithm.SJF, jobs)

    expected_timeline = [
        ("A", 0, 5),
        ("C", 5, 6),
        ("B", 6, 8),
        ("D", 8, 12),
    ]
    assert [(s.job_id, s.start, s.end) for s in res.timeline] == expected_timeline

    job_a = next(j for j in res.jobs if j.job_id == "A")
    assert (job_a.completion_time, job_a.turnaround_time, job_a.waiting_time, job_a.response_time) == (5, 5, 0, 0)

    job_c = next(j for j in res.jobs if j.job_id == "C")
    assert (job_c.completion_time, job_c.turnaround_time, job_c.waiting_time, job_c.response_time) == (6, 4, 3, 3)

    job_b = next(j for j in res.jobs if j.job_id == "B")
    assert (job_b.completion_time, job_b.turnaround_time, job_b.waiting_time, job_b.response_time) == (8, 7, 5, 5)

    job_d = next(j for j in res.jobs if j.job_id == "D")
    assert (job_d.completion_time, job_d.turnaround_time, job_d.waiting_time, job_d.response_time) == (12, 9, 5, 5)


def test_sjf_tie_breaking():
    """SJF tie breaking: equal burst time broken by arrival_time, then input_order.
    Job A: arrival=0, burst=2
    Job B: arrival=1, burst=3 (input_order 1)
    Job C: arrival=1, burst=3 (input_order 2)
    Job D: arrival=2, burst=3 (input_order 3)
    At t=0: A runs [0,2).
    At t=2: B (arr 1), C (arr 1), D (arr 2) are ready.
    All have burst 3. B and C arrive earlier than D.
    Between B and C, B has lower input_order -> B runs [2,5).
    Then C runs [5,8), then D runs [8,11).
    """
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=2),
        JobInput(id="B", arrival_time=1, burst_time=3),
        JobInput(id="C", arrival_time=1, burst_time=3),
        JobInput(id="D", arrival_time=2, burst_time=3),
    ]
    res = simulate(SchedulingAlgorithm.SJF, jobs)
    assert [(s.job_id, s.start, s.end) for s in res.timeline] == [
        ("A", 0, 2),
        ("B", 2, 5),
        ("C", 5, 8),
        ("D", 8, 11),
    ]


# ==============================================================================
# FCFS Tie-Breaking & Simultaneous Arrivals
# ==============================================================================

def test_fcfs_simultaneous_arrivals():
    """FCFS: simultaneous arrivals broken by input_order."""
    jobs = [
        JobInput(id="J1", arrival_time=2, burst_time=3),
        JobInput(id="J2", arrival_time=2, burst_time=1),
        JobInput(id="J3", arrival_time=2, burst_time=2),
    ]
    res = simulate(SchedulingAlgorithm.FCFS, jobs)

    # Initial idle period [0,2)
    assert [(s.job_id, s.start, s.end, s.kind.value) for s in res.timeline] == [
        (None, 0, 2, "IDLE"),
        ("J1", 2, 5, "EXECUTION"),
        ("J2", 5, 6, "EXECUTION"),
        ("J3", 6, 8, "EXECUTION"),
    ]


# ==============================================================================
# Priority Tie-Breaking & Same Priorities
# ==============================================================================

def test_priority_tie_breaking():
    """Priority: lower numeric priority first. Equal priority broken by arrival_time, then input_order."""
    jobs = [
        JobInput(id="P1", arrival_time=0, burst_time=3, priority=5),
        JobInput(id="P2", arrival_time=1, burst_time=2, priority=2),  # arr 1, prio 2, input 1
        JobInput(id="P3", arrival_time=2, burst_time=2, priority=2),  # arr 2, prio 2, input 2
        JobInput(id="P4", arrival_time=1, burst_time=2, priority=2),  # arr 1, prio 2, input 3
    ]
    res = simulate(SchedulingAlgorithm.PRIORITY, jobs)

    # P1 runs [0,3). At t=3, P2, P3, P4 are ready, all priority 2.
    # P2 and P4 arrive at t=1 (before P3 at t=2).
    # P2 vs P4: P2 has lower input_order (1 vs 3).
    # Sequence: P1 [0,3), P2 [3,5), P4 [5,7), P3 [7,9).
    assert [(s.job_id, s.start, s.end) for s in res.timeline] == [
        ("P1", 0, 3),
        ("P2", 3, 5),
        ("P4", 5, 7),
        ("P3", 7, 9),
    ]


# ==============================================================================
# Round Robin Quantum Boundary & Requeue Order
# ==============================================================================

def test_round_robin_boundary_arrival_order():
    """Round Robin: verify boundary condition.
    At a time-slice boundary, newly arriving jobs enter ready queue BEFORE the unfinished running job is re-enqueued.
    Job A: arrival=0, burst=4
    Job B: arrival=2, burst=2
    Quantum = 2
    t=0: A runs [0,2).
    t=2: A quantum expires (remaining=2). B arrives at t=2.
    Rule: B is enqueued first, then A is re-enqueued at tail.
    Queue at t=2: [B, A].
    t=2: B runs [2,4) and completes.
    t=4: A runs [4,6) and completes.
    Timeline: A [0,2), B [2,4), A [4,6)
    """
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=4),
        JobInput(id="B", arrival_time=2, burst_time=2),
    ]
    res = simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=2)
    assert [(s.job_id, s.start, s.end) for s in res.timeline] == [
        ("A", 0, 2),
        ("B", 2, 4),
        ("A", 4, 6),
    ]


def test_round_robin_single_job():
    """Round Robin with single job requiring multiple quanta."""
    jobs = [JobInput(id="Solo", arrival_time=0, burst_time=5)]
    res = simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=2)
    # Segments merge into [0,5) because it's contiguous execution of same job
    assert len(res.timeline) == 1
    assert res.timeline[0].job_id == "Solo"
    assert res.timeline[0].start == 0
    assert res.timeline[0].end == 5
    job = res.jobs[0]
    assert (job.first_start_time, job.completion_time, job.waiting_time, job.response_time) == (0, 5, 0, 0)


def test_round_robin_idle_interval():
    """Round Robin with an idle interval between job completion and next arrival."""
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=2),
        JobInput(id="B", arrival_time=5, burst_time=3),
    ]
    res = simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=2)
    assert [(s.job_id, s.start, s.end, s.kind.value) for s in res.timeline] == [
        ("A", 0, 2, "EXECUTION"),
        (None, 2, 5, "IDLE"),
        ("B", 5, 8, "EXECUTION"),
    ]


# ==============================================================================
# Invariant & Mathematical Correctness Tests (§6)
# ==============================================================================

@pytest.mark.parametrize("algo", [
    SchedulingAlgorithm.FCFS,
    SchedulingAlgorithm.SJF,
    SchedulingAlgorithm.PRIORITY,
    SchedulingAlgorithm.ROUND_ROBIN,
])
def test_all_invariants_across_algorithms(algo):
    """Verify invariants from docs/06 §6 across all 4 algorithms:
    - Every valid job executes exactly its burst time
    - A job does not execute before its arrival
    - No two execution segments overlap
    - Total busy time equals sum of burst times
    - Turnaround = completion - arrival
    - Waiting = turnaround - burst
    - Response = first_start - arrival >= 0
    - Non-negative, continuous timeline
    """
    jobs = [
        JobInput(id="P1", arrival_time=1, burst_time=4, priority=3),
        JobInput(id="P2", arrival_time=0, burst_time=2, priority=1),
        JobInput(id="P3", arrival_time=5, burst_time=3, priority=2),
    ]
    res = simulate(algo, jobs, quantum=2 if algo == SchedulingAlgorithm.ROUND_ROBIN else None)

    # 1. Total busy time equals sum of burst times
    busy_time = sum(s.end - s.start for s in res.timeline if s.kind == TimelineSegmentKind.EXECUTION)
    assert busy_time == res.total_burst_time == 9

    # 2. Timeline continuity and no overlapping segments
    for i in range(len(res.timeline) - 1):
        assert res.timeline[i].end == res.timeline[i + 1].start

    # 3. Every job executes exactly its burst time
    for job in jobs:
        job_time = sum(
            s.end - s.start
            for s in res.timeline
            if s.kind == TimelineSegmentKind.EXECUTION and s.job_id == job.id
        )
        assert job_time == job.burst_time

    # 4. Job metric mathematical identities
    for jm in res.jobs:
        assert jm.first_start_time >= jm.arrival_time
        assert jm.completion_time >= jm.first_start_time + jm.burst_time
        assert jm.turnaround_time == jm.completion_time - jm.arrival_time
        assert jm.waiting_time == jm.turnaround_time - jm.burst_time
        assert jm.response_time == jm.first_start_time - jm.arrival_time
        assert jm.waiting_time >= 0
        assert jm.response_time >= 0


# ==============================================================================
# Input Validation & Error Handling Tests
# ==============================================================================

def test_validation_empty_jobs():
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.FCFS, [])
    assert exc.value.field == "jobs"
    assert "empty" in exc.value.message.lower()


def test_validation_duplicate_job_ids():
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=2),
        JobInput(id="A", arrival_time=1, burst_time=3),
    ]
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.FCFS, jobs)
    assert "duplicate" in exc.value.message.lower()


def test_validation_missing_priority_for_priority_scheduling():
    jobs = [
        JobInput(id="A", arrival_time=0, burst_time=2, priority=None),
    ]
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.PRIORITY, jobs)
    assert "priority" in exc.value.message.lower()


def test_validation_missing_or_invalid_quantum():
    jobs = [JobInput(id="A", arrival_time=0, burst_time=2)]
    # Missing quantum
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=None)
    assert exc.value.field == "quantum"

    # Zero quantum
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=0)
    assert exc.value.field == "quantum"

    # Negative quantum
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=-2)
    assert exc.value.field == "quantum"

    # Boolean quantum
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.ROUND_ROBIN, jobs, quantum=True)  # type: ignore
    assert exc.value.field == "quantum"


def test_validation_exceeds_max_jobs():
    jobs = [JobInput(id=f"P{i}", arrival_time=0, burst_time=1) for i in range(10)]
    with pytest.raises(SchedulerValidationError) as exc:
        simulate(SchedulingAlgorithm.FCFS, jobs, max_jobs=5)
    assert exc.value.field == "jobs"
    assert "exceeds" in exc.value.message.lower()


def test_job_input_schema_rejects_negative_burst_or_arrival():
    with pytest.raises(Exception):
        JobInput(id="A", arrival_time=-1, burst_time=2)

    with pytest.raises(Exception):
        JobInput(id="A", arrival_time=0, burst_time=0)

    with pytest.raises(Exception):
        JobInput(id="A", arrival_time=0, burst_time=-5)

    with pytest.raises(Exception):
        JobInput(id="   ", arrival_time=0, burst_time=2)

    # Boolean rejected
    with pytest.raises(Exception):
        JobInput(id="A", arrival_time=True, burst_time=2)  # type: ignore
