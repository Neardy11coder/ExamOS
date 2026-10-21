"""
Service functions for student examination lifecycle, durable answer persistence,
deadline enforcement, and finalization.

Docs:
- docs/04_API_CONTRACT.md §4 Student exam catalogue and attempt API
- docs/04_API_CONTRACT.md §5 Faculty results and attempt list
- docs/03_DATABASE_DESIGN.md §§3.8-3.9
- docs/01_REQUIREMENTS.md FR-STUD, FR-ATTEMPT, FR-TIME, FR-SAVE, FR-SUBMIT, FR-EXPIRE, FR-RESULT
- docs/01_REQUIREMENTS.md Appendix A (Normative consistency rules A.1, A.2, A.3)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.attempt import Attempt, AttemptAnswer
from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
from app.models.user import User
from app.schemas.attempt import (
    AnswerSaveRequest,
    AnswerSaveResponse,
    AttemptDetailRead,
    AttemptExamInfo,
    AttemptResultResponse,
    AvailableExamItem,
    FacultyAttemptListItem,
    ResultOptionRead,
    ResultQuestionItem,
    StudentAnswerState,
    StudentOptionRead,
    StudentQuestionRead,
    SubmitAttemptRequest,
    SubmitAttemptResponse,
)


class AttemptServiceError(Exception):
    """Base exception for attempt service operations."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class AttemptRevisionConflictError(AttemptServiceError):
    """Raised when an answer save encounters an optimistic concurrency revision mismatch."""

    def __init__(self, code: str, message: str, canonical_state: dict):
        super().__init__(code=code, message=message, status_code=409, details=canonical_state)
        self.canonical_state = canonical_state


def _get_db_now(db: Session) -> datetime:
    """Obtains authoritative timestamp from PostgreSQL clock_timestamp()."""
    now = db.scalar(select(sa.func.clock_timestamp()))
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now


def _compute_attempt_score(db: Session, attempt: Attempt) -> Decimal:
    """
    Computes total score for an attempt from persisted answers.
    Per FR-SUBMIT-004: sum of marks of questions whose persisted selected option
    is the correct option in exam_question_options.
    """
    total = Decimal("0.00")
    for ans in attempt.answers:
        if ans.selected_option_id is not None:
            # Check if option is correct
            opt = db.get(ExamQuestionOption, ans.selected_option_id)
            if opt is not None and opt.is_correct:
                q = db.get(ExamQuestion, ans.exam_question_id)
                if q is not None:
                    total += q.marks
    return total


def _check_and_finalize_if_expired(db: Session, attempt: Attempt, now: datetime | None = None) -> Attempt:
    """
    Performs lazy finalization (FR-EXPIRE-001, Appendix A.2):
    If attempt is IN_PROGRESS and current server/db time is past deadline (now >= deadline_at),
    atomically finalize as EXPIRED with computed score and commit.
    """
    if attempt.status != "IN_PROGRESS":
        return attempt

    decision_time = now or _get_db_now(db)
    # Exclusive deadline boundary per Appendix A.2: request timely only if decision_time < deadline_at
    if decision_time >= attempt.deadline_at:
        # Lock attempt row to serialize finalization
        locked = db.scalars(
            select(Attempt)
            .filter(Attempt.id == attempt.id)
            .with_for_update()
        ).first()

        if locked and locked.status == "IN_PROGRESS":
            score = _compute_attempt_score(db, locked)
            locked.status = "EXPIRED"
            locked.score = score
            locked.finalized_at = decision_time
            locked.updated_at = decision_time
            db.commit()
            db.refresh(locked)
            return locked

    return attempt


def _serialize_attempt_detail(db: Session, attempt: Attempt) -> AttemptDetailRead:
    """
    Serializes full student attempt workspace view.
    Confidentiality: Omits is_correct from question options while attempt is active.
    """
    now = _get_db_now(db)
    remaining_secs = max(0, int((attempt.deadline_at - now).total_seconds()))
    if attempt.status in ("SUBMITTED", "EXPIRED"):
        remaining_secs = 0

    exam = db.get(Exam, attempt.exam_id)
    assert exam is not None

    total_marks = sum((q.marks for q in exam.questions), Decimal("0.00"))
    exam_info = AttemptExamInfo(
        id=exam.id,
        title=exam.title,
        instructions=exam.instructions or "",
        duration_minutes=exam.duration_minutes,
        total_marks=total_marks,
    )

    # Map answers by exam_question_id
    answers_by_qid = {ans.exam_question_id: ans for ans in attempt.answers}

    sorted_questions = sorted(exam.questions, key=lambda q: q.display_order)
    questions_data: list[StudentQuestionRead] = []

    for eq in sorted_questions:
        sorted_opts = sorted(eq.options, key=lambda o: o.display_order)
        # Never send is_correct during active attempt!
        student_opts = [
            StudentOptionRead(
                id=o.id,
                text=o.option_text_snapshot,
                display_order=o.display_order,
            )
            for o in sorted_opts
        ]

        ans = answers_by_qid.get(eq.id)
        ans_state = StudentAnswerState(
            selected_option_id=ans.selected_option_id if ans else None,
            marked_for_review=ans.marked_for_review if ans else False,
            revision=ans.revision if ans else 0,
        )

        questions_data.append(
            StudentQuestionRead(
                exam_question_id=eq.id,
                prompt=eq.prompt_snapshot,
                marks=eq.marks,
                display_order=eq.display_order,
                options=student_opts,
                answer=ans_state,
            )
        )

    return AttemptDetailRead(
        attempt_id=attempt.id,
        status=attempt.status,
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        remaining_seconds=remaining_secs,
        exam=exam_info,
        questions=questions_data,
    )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------

def list_available_exams(
    db: Session,
    *,
    student_id: UUID,
) -> list[AvailableExamItem]:
    """
    Lists published exams available to the student (GET /exams/available).
    Returns summary metadata and whether student already has an attempt.
    """
    exams_stmt = (
        select(Exam)
        .options(
            selectinload(Exam.questions),
        )
        .filter(Exam.status == "PUBLISHED")
        .order_by(Exam.created_at.desc())
    )
    published_exams = list(db.scalars(exams_stmt).all())
    if not published_exams:
        return []

    exam_ids = [e.id for e in published_exams]
    attempts_stmt = select(Attempt).filter(
        Attempt.student_id == student_id,
        Attempt.exam_id.in_(exam_ids),
    )
    attempts = list(db.scalars(attempts_stmt).all())
    attempt_by_exam_id = {att.exam_id: att for att in attempts}

    results: list[AvailableExamItem] = []
    for exam in published_exams:
        total_marks = sum((q.marks for q in exam.questions), Decimal("0.00"))
        att = attempt_by_exam_id.get(exam.id)
        if att is not None:
            # Run lazy expiry check if active
            att = _check_and_finalize_if_expired(db, att)

        results.append(
            AvailableExamItem(
                id=exam.id,
                title=exam.title,
                instructions=exam.instructions or "",
                duration_minutes=exam.duration_minutes,
                question_count=len(exam.questions),
                total_marks=total_marks,
                has_attempt=att is not None,
                attempt_id=att.id if att else None,
                attempt_status=att.status if att else None,
            )
        )

    return results


def start_attempt(
    db: Session,
    *,
    exam_id: UUID,
    student_id: UUID,
) -> AttemptDetailRead:
    """
    Starts an examination attempt (POST /exams/{exam_id}/attempts/start).
    Idempotent: if student already has an attempt for this exam, returns existing attempt.
    Atomically creates IN_PROGRESS attempt, computes deadline, and pre-populates answer rows.
    """
    # 1. Check if attempt already exists (idempotency check)
    existing_stmt = (
        select(Attempt)
        .options(
            selectinload(Attempt.answers),
            joinedload(Attempt.exam).selectinload(Exam.questions).selectinload(ExamQuestion.options),
        )
        .filter(Attempt.student_id == student_id, Attempt.exam_id == exam_id)
    )
    existing_attempt = db.scalars(existing_stmt).first()
    if existing_attempt is not None:
        existing_attempt = _check_and_finalize_if_expired(db, existing_attempt)
        return _serialize_attempt_detail(db, existing_attempt)

    # 2. Validate exam eligibility
    exam_stmt = (
        select(Exam)
        .options(
            selectinload(Exam.questions).selectinload(ExamQuestion.options),
        )
        .filter(Exam.id == exam_id)
    )
    exam = db.scalars(exam_stmt).first()
    if exam is None:
        raise AttemptServiceError("EXAM_NOT_FOUND", "Examination not found.", status_code=404)

    if exam.status != "PUBLISHED":
        raise AttemptServiceError(
            "EXAM_NOT_AVAILABLE",
            f"Cannot start attempt: examination status is '{exam.status}'.",
            status_code=400,
        )

    if not exam.questions:
        raise AttemptServiceError(
            "EMPTY_EXAM",
            "Examination contains no questions.",
            status_code=400,
        )

    now = _get_db_now(db)
    deadline_at = now + timedelta(minutes=exam.duration_minutes)

    # 3. Create attempt and answer rows atomically
    attempt = Attempt(
        student_id=student_id,
        exam_id=exam.id,
        status="IN_PROGRESS",
        started_at=now,
        deadline_at=deadline_at,
        last_seen_at=now,
    )
    db.add(attempt)
    db.flush()

    for eq in exam.questions:
        ans = AttemptAnswer(
            attempt_id=attempt.id,
            exam_id=exam.id,
            exam_question_id=eq.id,
            selected_option_id=None,
            marked_for_review=False,
            revision=0,
            updated_at=now,
        )
        db.add(ans)

    try:
        db.commit()
    except IntegrityError:
        # Race condition: concurrent start request by same student
        db.rollback()
        concurrent_attempt = db.scalars(existing_stmt).first()
        if concurrent_attempt is not None:
            concurrent_attempt = _check_and_finalize_if_expired(db, concurrent_attempt)
            return _serialize_attempt_detail(db, concurrent_attempt)
        raise AttemptServiceError("START_FAILED", "Failed to start attempt due to concurrent conflict.", status_code=409)

    db.refresh(attempt)
    return _serialize_attempt_detail(db, attempt)


def get_attempt(
    db: Session,
    *,
    attempt_id: UUID,
    student_id: UUID,
) -> AttemptDetailRead:
    """
    Retrieves the student's active or existing attempt (GET /attempts/{attempt_id}).
    Enforces student ownership and performs lazy expiry.
    """
    stmt = (
        select(Attempt)
        .options(
            selectinload(Attempt.answers),
            joinedload(Attempt.exam).selectinload(Exam.questions).selectinload(ExamQuestion.options),
        )
        .filter(Attempt.id == attempt_id)
    )
    attempt = db.scalars(stmt).first()
    if attempt is None:
        raise AttemptServiceError("ATTEMPT_NOT_FOUND", "Attempt not found.", status_code=404)

    if attempt.student_id != student_id:
        raise AttemptServiceError(
            "FORBIDDEN",
            "Students may only access their own examination attempts.",
            status_code=403,
        )

    attempt = _check_and_finalize_if_expired(db, attempt)
    return _serialize_attempt_detail(db, attempt)


def save_answer(
    db: Session,
    *,
    attempt_id: UUID,
    student_id: UUID,
    exam_question_id: UUID,
    payload: AnswerSaveRequest,
) -> AnswerSaveResponse:
    """
    Durable answer update (PUT /attempts/{attempt_id}/answers/{exam_question_id}).
    - Locks attempt row first, answers second.
    - Enforces ownership, active status, and exclusive deadline.
    - Validates question and option membership against frozen snapshots.
    - Uses optimistic revision check: expected_revision == current_revision.
    """
    # 1. Lock attempt row
    stmt = (
        select(Attempt)
        .filter(Attempt.id == attempt_id)
        .with_for_update()
    )
    attempt = db.scalars(stmt).first()
    if attempt is None:
        raise AttemptServiceError("ATTEMPT_NOT_FOUND", "Attempt not found.", status_code=404)

    if attempt.student_id != student_id:
        raise AttemptServiceError(
            "FORBIDDEN",
            "Students may only save answers to their own examination attempts.",
            status_code=403,
        )

    now = _get_db_now(db)

    # 2. Server-authoritative deadline check
    if now >= attempt.deadline_at:
        # Finalize as EXPIRED if not already finalized
        if attempt.status == "IN_PROGRESS":
            score = _compute_attempt_score(db, attempt)
            attempt.status = "EXPIRED"
            attempt.score = score
            attempt.finalized_at = now
            attempt.updated_at = now
            db.commit()
        raise AttemptServiceError(
            "ATTEMPT_EXPIRED",
            "This attempt has expired and can no longer be changed.",
            status_code=409,
            details={"attempt_status": "EXPIRED"},
        )

    if attempt.status != "IN_PROGRESS":
        raise AttemptServiceError(
            "ATTEMPT_NOT_ACTIVE",
            f"Cannot modify answer: attempt is in terminal status '{attempt.status}'.",
            status_code=409,
            details={"attempt_status": attempt.status},
        )

    # 3. Validate frozen question membership
    eq = db.get(ExamQuestion, exam_question_id)
    if eq is None or eq.exam_id != attempt.exam_id:
        raise AttemptServiceError(
            "INVALID_QUESTION",
            "Specified question does not belong to this examination attempt.",
            status_code=400,
        )

    # 4. Validate selected option membership if provided
    if payload.selected_option_id is not None:
        opt = db.get(ExamQuestionOption, payload.selected_option_id)
        if opt is None or opt.exam_question_id != exam_question_id:
            raise AttemptServiceError(
                "INVALID_OPTION",
                "Selected option does not belong to the specified examination question.",
                status_code=400,
            )

    # 5. Lock answer row
    ans_stmt = (
        select(AttemptAnswer)
        .filter(
            AttemptAnswer.attempt_id == attempt_id,
            AttemptAnswer.exam_question_id == exam_question_id,
        )
        .with_for_update()
    )
    ans = db.scalars(ans_stmt).first()
    if ans is None:
        raise AttemptServiceError(
            "ANSWER_NOT_FOUND",
            "Answer record not found for this question.",
            status_code=404,
        )

    # 6. Optimistic concurrency check
    if ans.revision != payload.expected_revision:
        raise AttemptRevisionConflictError(
            code="ANSWER_REVISION_CONFLICT",
            message="Stale answer revision. The answer has already been updated.",
            canonical_state={
                "selected_option_id": str(ans.selected_option_id) if ans.selected_option_id else None,
                "marked_for_review": ans.marked_for_review,
                "revision": ans.revision,
                "saved_at": ans.updated_at.isoformat(),
            },
        )

    # 7. Apply update and increment revision
    ans.selected_option_id = payload.selected_option_id
    ans.marked_for_review = payload.marked_for_review
    ans.revision += 1
    ans.updated_at = now
    attempt.last_seen_at = now

    db.commit()
    db.refresh(ans)

    return AnswerSaveResponse(
        selected_option_id=ans.selected_option_id,
        marked_for_review=ans.marked_for_review,
        revision=ans.revision,
        saved_at=ans.updated_at,
    )


def submit_attempt(
    db: Session,
    *,
    attempt_id: UUID,
    student_id: UUID,
    payload: SubmitAttemptRequest | None = None,
) -> SubmitAttemptResponse:
    """
    Submits an examination attempt (POST /attempts/{attempt_id}/submit).
    - Locks attempt row.
    - Idempotent: repeated submit requests on terminal attempts return existing outcome.
    - Decides terminal status based on authoritative server/db time:
      now < deadline_at -> SUBMITTED
      now >= deadline_at -> EXPIRED
    - Scores atomically and commits.
    """
    stmt = (
        select(Attempt)
        .options(
            selectinload(Attempt.answers),
            selectinload(Attempt.exam).selectinload(Exam.questions),
        )
        .filter(Attempt.id == attempt_id)
        .with_for_update()
    )
    attempt = db.scalars(stmt).first()
    if attempt is None:
        raise AttemptServiceError("ATTEMPT_NOT_FOUND", "Attempt not found.", status_code=404)

    if attempt.student_id != student_id:
        raise AttemptServiceError(
            "FORBIDDEN",
            "Students may only submit their own examination attempts.",
            status_code=403,
        )

    total_marks = sum((q.marks for q in attempt.exam.questions), Decimal("0.00"))

    # If already terminal, return existing outcome idempotently
    if attempt.status in ("SUBMITTED", "EXPIRED"):
        return SubmitAttemptResponse(
            attempt_id=attempt.id,
            status=attempt.status,
            score=attempt.score or Decimal("0.00"),
            total_marks=total_marks,
            finalized_at=attempt.finalized_at or attempt.updated_at,
        )

    now = _get_db_now(db)
    # Exclusive deadline boundary per Appendix A.2
    if now < attempt.deadline_at:
        terminal_status = "SUBMITTED"
    else:
        terminal_status = "EXPIRED"

    score = _compute_attempt_score(db, attempt)

    attempt.status = terminal_status
    attempt.score = score
    attempt.finalized_at = now
    attempt.updated_at = now

    db.commit()
    db.refresh(attempt)

    return SubmitAttemptResponse(
        attempt_id=attempt.id,
        status=attempt.status,
        score=attempt.score,
        total_marks=total_marks,
        finalized_at=attempt.finalized_at,
    )


def get_attempt_result(
    db: Session,
    *,
    attempt_id: UUID,
    user_id: UUID,
    user_role: str,
) -> AttemptResultResponse:
    """
    Retrieves finalized attempt results (GET /attempts/{attempt_id}/result).
    Accessible to student owner or faculty.
    Per OD-04: Reveals student selection, correctness, and correct options post-finalization.
    """
    stmt = (
        select(Attempt)
        .options(
            selectinload(Attempt.answers),
            joinedload(Attempt.exam).selectinload(Exam.questions).selectinload(ExamQuestion.options),
        )
        .filter(Attempt.id == attempt_id)
    )
    attempt = db.scalars(stmt).first()
    if attempt is None:
        raise AttemptServiceError("ATTEMPT_NOT_FOUND", "Attempt not found.", status_code=404)

    # Permission check: own student or faculty
    if user_role == "STUDENT" and attempt.student_id != user_id:
        raise AttemptServiceError(
            "FORBIDDEN",
            "Students may only access results for their own attempts.",
            status_code=403,
        )

    # Lazy finalization check
    attempt = _check_and_finalize_if_expired(db, attempt)

    if attempt.status not in ("SUBMITTED", "EXPIRED"):
        raise AttemptServiceError(
            "RESULT_NOT_AVAILABLE",
            "Results are only available after the attempt has been finalized.",
            status_code=400,
        )

    exam = attempt.exam
    total_marks = sum((q.marks for q in exam.questions), Decimal("0.00"))
    score = attempt.score or Decimal("0.00")
    percentage = (score / total_marks * Decimal("100.00")) if total_marks > Decimal("0.00") else Decimal("0.00")

    answers_by_qid = {ans.exam_question_id: ans for ans in attempt.answers}
    sorted_questions = sorted(exam.questions, key=lambda q: q.display_order)

    questions_results: list[ResultQuestionItem] = []
    for eq in sorted_questions:
        ans = answers_by_qid.get(eq.id)
        selected_opt_id = ans.selected_option_id if ans else None

        # Check if student's answer was correct
        correct_opt = next((o for o in eq.options if o.is_correct), None)
        is_correct = (
            selected_opt_id is not None
            and correct_opt is not None
            and selected_opt_id == correct_opt.id
        )

        sorted_opts = sorted(eq.options, key=lambda o: o.display_order)
        # Disclose correct option flag post-finalization per OD-04
        opts_results = [
            ResultOptionRead(
                id=o.id,
                text=o.option_text_snapshot,
                display_order=o.display_order,
                is_correct=o.is_correct,
            )
            for o in sorted_opts
        ]

        questions_results.append(
            ResultQuestionItem(
                exam_question_id=eq.id,
                prompt=eq.prompt_snapshot,
                marks=eq.marks,
                display_order=eq.display_order,
                topic_code=eq.topic_code_snapshot,
                topic_name=eq.topic_name_snapshot,
                student_selected_option_id=selected_opt_id,
                is_correct=is_correct,
                options=opts_results,
            )
        )

    return AttemptResultResponse(
        attempt_id=attempt.id,
        exam_id=exam.id,
        exam_title=exam.title,
        status=attempt.status,
        score=score,
        total_marks=total_marks,
        percentage=round(percentage, 2),
        started_at=attempt.started_at,
        deadline_at=attempt.deadline_at,
        finalized_at=attempt.finalized_at or attempt.updated_at,
        questions=questions_results,
    )


def list_exam_attempts(
    db: Session,
    *,
    exam_id: UUID,
) -> list[FacultyAttemptListItem]:
    """
    Lists all attempts for an exam (GET /exams/{exam_id}/attempts) for faculty.
    Runs lazy expiry on overdue in-progress attempts before returning.
    """
    exam = db.get(Exam, exam_id)
    if exam is None:
        raise AttemptServiceError("EXAM_NOT_FOUND", "Examination not found.", status_code=404)

    total_marks = sum((q.marks for q in exam.questions), Decimal("0.00"))

    # Sweep / lazy expire any overdue attempts for this exam
    now = _get_db_now(db)
    overdue_stmt = select(Attempt).filter(
        Attempt.exam_id == exam_id,
        Attempt.status == "IN_PROGRESS",
        Attempt.deadline_at <= now,
    )
    overdue_attempts = list(db.scalars(overdue_stmt).all())
    for att in overdue_attempts:
        _check_and_finalize_if_expired(db, att, now=now)

    # Load all attempts with student joined
    stmt = (
        select(Attempt)
        .options(
            joinedload(Attempt.student),
        )
        .filter(Attempt.exam_id == exam_id)
        .order_by(Attempt.started_at.desc())
    )
    attempts = list(db.scalars(stmt).all())

    return [
        FacultyAttemptListItem(
            id=att.id,
            student_id=att.student_id,
            student_email=att.student.email if att.student else "",
            student_display_name=att.student.display_name if att.student else "",
            status=att.status,
            started_at=att.started_at,
            deadline_at=att.deadline_at,
            finalized_at=att.finalized_at,
            score=att.score,
            total_marks=total_marks,
        )
        for att in attempts
    ]
