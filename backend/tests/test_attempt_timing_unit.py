"""
Deterministic unit tests for Phase 1B backend attempt timing and expiry ordering.

These tests verify pure remaining-seconds calculations and lock-then-clock
ordering in `app.services.attempt_service` without requiring a live PostgreSQL
connection, complementing the PostgreSQL integration tests in
`tests/test_attempt_lifecycle.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest

from app.models.attempt import Attempt
from app.models.exam import Exam
from app.services import attempt_service


class _ScalarResult:
    def __init__(self, items: list[object]):
        self._items = items

    def first(self):
        return self._items[0] if self._items else None

    def all(self):
        return list(self._items)


class _FakeSession:
    """Minimal SQLAlchemy Session stub recording FOR UPDATE lock and clock ordering."""

    def __init__(self, attempt: Attempt, exam: Exam | None = None):
        self.attempt = attempt
        self.exam = exam
        self.events: list[str] = []
        self.committed = False
        self.refreshed = False

    def scalars(self, stmt, *args, **kwargs):
        has_for_update = getattr(stmt, "_for_update_arg", None) is not None
        if has_for_update:
            self.events.append("for_update_lock")
            return _ScalarResult([self.attempt])
        return _ScalarResult([self.attempt])

    def get(self, model, ident):
        if model is Exam and self.exam is not None and ident == self.exam.id:
            return self.exam
        return None

    def commit(self):
        self.events.append("commit")
        self.committed = True

    def refresh(self, obj):
        self.events.append("refresh")
        self.refreshed = True


def _make_attempt(
    *,
    status: str = "IN_PROGRESS",
    deadline_at: datetime | None = None,
) -> tuple[Attempt, Exam]:
    exam_id = uuid.uuid4()
    started = datetime(2026, 11, 26, 10, 0, 0, tzinfo=timezone.utc)
    deadline = deadline_at or (started + timedelta(minutes=30))

    exam = Exam(
        id=exam_id,
        title="Unit Test Exam",
        instructions="Pick one.",
        duration_minutes=30,
        status="PUBLISHED",
        creator_id=uuid.uuid4(),
    )
    exam.questions = []

    att = Attempt(
        id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        exam_id=exam_id,
        status=status,
        started_at=started,
        deadline_at=deadline,
        finalized_at=None if status == "IN_PROGRESS" else deadline,
        score=None if status == "IN_PROGRESS" else Decimal("0.00"),
    )
    att.exam = exam
    att.answers = []
    return att, exam


def test_remaining_seconds_0_8s_returns_positive_value():
    deadline = datetime(2026, 11, 26, 10, 30, 0, tzinfo=timezone.utc)
    now = deadline - timedelta(milliseconds=800)
    assert (
        attempt_service._calculate_remaining_seconds(
            status="IN_PROGRESS",
            deadline_at=deadline,
            now=now,
        )
        == 1
    )


def test_remaining_seconds_exact_zero_returns_zero():
    deadline = datetime(2026, 11, 26, 10, 30, 0, tzinfo=timezone.utc)
    assert (
        attempt_service._calculate_remaining_seconds(
            status="IN_PROGRESS",
            deadline_at=deadline,
            now=deadline,
        )
        == 0
    )


def test_remaining_seconds_past_deadline_returns_zero():
    deadline = datetime(2026, 11, 26, 10, 30, 0, tzinfo=timezone.utc)
    assert (
        attempt_service._calculate_remaining_seconds(
            status="IN_PROGRESS",
            deadline_at=deadline,
            now=deadline + timedelta(seconds=12, milliseconds=400),
        )
        == 0
    )


def test_serialize_attempt_detail_reports_positive_at_0_8s(monkeypatch: pytest.MonkeyPatch):
    att, exam = _make_attempt()
    db = _FakeSession(att, exam=exam)
    monkeypatch.setattr(
        attempt_service,
        "_get_db_now",
        lambda _db: att.deadline_at - timedelta(milliseconds=800),
    )

    detail = attempt_service._serialize_attempt_detail(db, att)  # type: ignore[arg-type]
    assert detail.status == "IN_PROGRESS"
    assert detail.remaining_seconds == 1


def test_decision_time_equal_to_deadline_finalizes_as_expired(monkeypatch: pytest.MonkeyPatch):
    att, exam = _make_attempt()
    db = _FakeSession(att, exam=exam)
    monkeypatch.setattr(attempt_service, "_get_db_now", lambda _db: att.deadline_at)

    result = attempt_service._check_and_finalize_if_expired(db, att)  # type: ignore[arg-type]
    assert result.status == "EXPIRED"
    assert result.finalized_at == att.deadline_at
    assert result.score == Decimal("0.00")
    assert db.committed is True


def test_attempt_before_deadline_remains_in_progress(monkeypatch: pytest.MonkeyPatch):
    att, exam = _make_attempt()
    db = _FakeSession(att, exam=exam)
    monkeypatch.setattr(
        attempt_service,
        "_get_db_now",
        lambda _db: att.deadline_at - timedelta(milliseconds=800),
    )

    result = attempt_service._check_and_finalize_if_expired(db, att)  # type: ignore[arg-type]
    assert result.status == "IN_PROGRESS"
    assert result.finalized_at is None
    assert db.committed is False


def test_expiry_finalization_acquires_lock_before_clock(monkeypatch: pytest.MonkeyPatch):
    att, exam = _make_attempt()
    db = _FakeSession(att, exam=exam)

    def tracked_clock(_db):
        db.events.append("clock_timestamp")
        return att.deadline_at + timedelta(seconds=3)

    monkeypatch.setattr(attempt_service, "_get_db_now", tracked_clock)

    result = attempt_service._check_and_finalize_if_expired(db, att)  # type: ignore[arg-type]
    assert result.status == "EXPIRED"
    assert db.events[0] == "for_update_lock"
    assert db.events[1] == "clock_timestamp"
    assert result.finalized_at == att.deadline_at + timedelta(seconds=3)


def test_list_exam_attempts_uses_post_lock_clock_not_pre_scan_timestamp(
    monkeypatch: pytest.MonkeyPatch,
):
    att, exam = _make_attempt()
    db = _FakeSession(att, exam=exam)

    pre_scan_now = att.deadline_at + timedelta(seconds=1)
    post_lock_now = att.deadline_at + timedelta(seconds=25)
    clock_values = iter([pre_scan_now, post_lock_now])

    def tracked_clock(_db):
        db.events.append("clock_timestamp")
        return next(clock_values)

    monkeypatch.setattr(attempt_service, "_get_db_now", tracked_clock)

    items = attempt_service.list_exam_attempts(db, exam_id=exam.id)  # type: ignore[arg-type]
    assert len(items) == 1
    assert items[0].status == "EXPIRED"
    assert items[0].finalized_at == post_lock_now
    assert db.events[:3] == ["clock_timestamp", "for_update_lock", "clock_timestamp"]
