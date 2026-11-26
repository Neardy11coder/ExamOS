"""PostgreSQL integration tests for attempt-finalization concurrency.

These tests use independent database connections to exercise real row-lock waits.
They intentionally run against the guarded ``examos_test`` database fixture only.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
import uuid

from sqlalchemy import delete, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.models.attempt import Attempt
from app.models.exam import Exam
from app.models.user import User
from app.services import attempt_service


def _wait_until_blocked(
    engine: Engine,
    *,
    waiting_pid: int,
    blocking_pid: int,
    timeout_seconds: float = 5.0,
) -> bool:
    """Wait until PostgreSQL reports that waiting_pid is blocked by blocking_pid."""
    deadline = monotonic() + timeout_seconds
    with engine.connect() as observer:
        while monotonic() < deadline:
            blockers = observer.scalar(
                text("SELECT pg_blocking_pids(:pid)"),
                {"pid": waiting_pid},
            ) or []
            if blocking_pid in blockers:
                return True
            sleep(0.02)
    return False


def _wait_until_database_deadline(
    connection,
    deadline_at,
    timeout_seconds: float = 8.0,
) -> bool:
    """Wait using PostgreSQL time while the caller continues holding its row lock."""
    timeout = monotonic() + timeout_seconds
    while monotonic() < timeout:
        now = connection.scalar(text("SELECT clock_timestamp()"))
        if now >= deadline_at:
            return True
        sleep(0.02)
    return False


def test_expiry_decision_uses_clock_after_waiting_for_attempt_row_lock(test_db_engine: Engine):
    """A finalizer blocked before the deadline must expire after the lock is released past it.

    Connection A locks the attempt while it is still active. Connection B enters the
    real finalization service and is observed waiting on A in pg_blocking_pids(). The
    deadline then passes while A retains the lock. Once A releases it, B must acquire
    the row, read clock_timestamp(), and finalize as EXPIRED.
    """
    assert test_db_engine.dialect.name == "postgresql"

    student_id = uuid.uuid4()
    exam_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    student_email = f"lock-race-{uuid.uuid4().hex}@examos.local"

    # Commit setup rows so the two worker connections can see the attempt.
    with Session(test_db_engine) as setup_session:
        with setup_session.begin():
            setup_now = setup_session.scalar(text("SELECT clock_timestamp()"))
            assert setup_now is not None
            deadline_at = setup_now + timedelta(seconds=5)

            student = User(
                id=student_id,
                email=student_email,
                display_name="Attempt lock race test student",
                password_hash="test-only-unused-password-hash",
                role="STUDENT",
                is_active=True,
            )
            exam = Exam(
                id=exam_id,
                creator_id=student_id,
                title=f"Attempt lock race {uuid.uuid4().hex[:8]}",
                instructions="Concurrency integration test.",
                duration_minutes=1,
                status="PUBLISHED",
            )
            attempt = Attempt(
                id=attempt_id,
                student_id=student_id,
                exam_id=exam_id,
                status="IN_PROGRESS",
                started_at=setup_now - timedelta(seconds=30),
                deadline_at=deadline_at,
                finalized_at=None,
                score=None,
            )
            setup_session.add_all([student, exam, attempt])

    lock_connection = test_db_engine.connect()
    lock_transaction = lock_connection.begin()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="attempt-finalizer")
    worker_ready = Event()
    worker_pid: list[int] = []
    future = None

    try:
        blocking_pid = lock_connection.scalar(text("SELECT pg_backend_pid()"))
        locked_id = lock_connection.scalar(
            text("SELECT id FROM public.attempts WHERE id = :attempt_id FOR UPDATE"),
            {"attempt_id": attempt_id},
        )
        assert locked_id == attempt_id

        def finalize_from_second_connection() -> tuple[str, object, object]:
            with Session(test_db_engine) as worker_session:
                pid = worker_session.scalar(text("SELECT pg_backend_pid()"))
                assert pid is not None
                worker_pid.append(pid)
                worker_ready.set()

                # Only id/status are read before the service reloads the locked row.
                stale_attempt = Attempt(id=attempt_id, status="IN_PROGRESS")
                finalized = attempt_service._check_and_finalize_if_expired(
                    worker_session,
                    stale_attempt,
                )
                return finalized.status, finalized.finalized_at, finalized.score

        future = executor.submit(finalize_from_second_connection)
        assert worker_ready.wait(timeout=3), "Second connection did not start."
        assert worker_pid, "Second connection did not report its PostgreSQL backend PID."

        waiting_pid = worker_pid[0]
        assert _wait_until_blocked(
            test_db_engine,
            waiting_pid=waiting_pid,
            blocking_pid=blocking_pid,
            timeout_seconds=3.0,
        ), "Second connection was not observed waiting on the first connection's row lock."

        # Confirm the worker is queued while the attempt is still before its deadline.
        queued_at = lock_connection.scalar(text("SELECT clock_timestamp()"))
        assert queued_at < deadline_at, (
            "The second connection did not reach the row-lock wait before the deadline; "
            "increase the test deadline or investigate test-environment load."
        )

        # Keep A's FOR UPDATE lock until PostgreSQL's clock has crossed the deadline.
        assert _wait_until_database_deadline(
            lock_connection,
            deadline_at,
        ), "PostgreSQL time did not reach the attempt deadline within the timeout."

        # Releasing A allows B to acquire the row; B must then read a fresh DB timestamp.
        lock_transaction.commit()
        lock_transaction = None

        status, finalized_at, score = future.result(timeout=10)
        assert status == "EXPIRED"
        assert finalized_at is not None and finalized_at >= deadline_at
        assert score is not None

        with Session(test_db_engine) as verify_session:
            persisted = verify_session.get(Attempt, attempt_id)
            assert persisted is not None
            assert persisted.status == "EXPIRED"
            assert persisted.finalized_at is not None
            assert persisted.finalized_at >= persisted.deadline_at
            assert persisted.score is not None
    finally:
        # Always release Connection A before joining the worker, including on assertion failure.
        if lock_transaction is not None and lock_transaction.is_active:
            lock_transaction.rollback()
        lock_connection.close()
        executor.shutdown(wait=True, cancel_futures=True)

        # Remove only the uniquely identified rows created by this test.
        with test_db_engine.begin() as cleanup:
            cleanup.execute(delete(Attempt).where(Attempt.id == attempt_id))
            cleanup.execute(delete(Exam).where(Exam.id == exam_id))
            cleanup.execute(delete(User).where(User.id == student_id))
