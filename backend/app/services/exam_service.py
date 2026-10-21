"""
Service functions for Exam draft authoring, question attachment, and atomic publication.

Docs:
- docs/04_API_CONTRACT.md §3 Faculty examination and question management
- docs/03_DATABASE_DESIGN.md §§3.5-3.7
- docs/01_REQUIREMENTS.md FR-EXAM-001 to FR-EXAM-010, OD-08
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.config import settings
from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
from app.models.question import Question
from app.schemas.exam import ExamQuestionReorderItem


class ExamServiceError(Exception):
    """Base exception for exam service errors."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def create_exam(
    db: Session,
    *,
    creator_id: UUID,
    title: str,
    instructions: str = "",
    duration_minutes: int,
) -> Exam:
    """
    Creates a new DRAFT examination.
    """
    clean_title = title.strip()
    if not clean_title:
        raise ExamServiceError("EMPTY_TITLE", "Exam title cannot be empty.")

    if duration_minutes <= 0 or duration_minutes > settings.MAX_EXAM_DURATION_MINUTES:
        raise ExamServiceError(
            "INVALID_DURATION",
            f"Duration must be between 1 and {settings.MAX_EXAM_DURATION_MINUTES} minutes.",
        )

    exam = Exam(
        creator_id=creator_id,
        title=clean_title,
        instructions=instructions or "",
        duration_minutes=duration_minutes,
        status="DRAFT",
    )
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


def list_exams(
    db: Session,
    *,
    creator_id: UUID | None = None,
) -> list[Exam]:
    """
    Lists all exams (or filtered by creator) with question count and total marks calculable.
    """
    query = (
        select(Exam)
        .options(
            selectinload(Exam.questions),
        )
        .order_by(Exam.created_at.desc())
    )
    if creator_id is not None:
        query = query.filter(Exam.creator_id == creator_id)

    return list(db.scalars(query).all())


def get_exam(db: Session, exam_id: UUID) -> Exam | None:
    """
    Retrieves a single exam by UUID with questions, options, and source questions joined.
    """
    stmt = (
        select(Exam)
        .options(
            selectinload(Exam.questions).selectinload(ExamQuestion.options),
            selectinload(Exam.questions).joinedload(ExamQuestion.source_question),
        )
        .filter(Exam.id == exam_id)
    )
    return db.scalars(stmt).first()


def update_draft_exam(
    db: Session,
    *,
    exam: Exam,
    actor_id: UUID,
    title: str | None = None,
    instructions: str | None = None,
    duration_minutes: int | None = None,
) -> Exam:
    """
    Updates title, instructions, or duration of a DRAFT exam only.
    Rejects modification if the exam is PUBLISHED or UNPUBLISHED.
    """
    if exam.creator_id != actor_id:
        raise ExamServiceError(
            "FORBIDDEN",
            "Faculty members cannot modify another faculty member's examinations.",
            status_code=403,
        )

    if exam.status != "DRAFT":
        raise ExamServiceError(
            "EXAM_IMMUTABLE",
            "Published or unpublished examinations cannot be modified. "
            "Create a new draft examination to revise assessment content.",
            status_code=409,
        )

    if title is not None:
        clean_title = title.strip()
        if not clean_title:
            raise ExamServiceError("EMPTY_TITLE", "Exam title cannot be empty.")
        exam.title = clean_title

    if instructions is not None:
        exam.instructions = instructions

    if duration_minutes is not None:
        if duration_minutes <= 0 or duration_minutes > settings.MAX_EXAM_DURATION_MINUTES:
            raise ExamServiceError(
                "INVALID_DURATION",
                f"Duration must be between 1 and {settings.MAX_EXAM_DURATION_MINUTES} minutes.",
            )
        exam.duration_minutes = duration_minutes

    exam.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exam)
    return exam


def attach_question_to_draft(
    db: Session,
    *,
    exam: Exam,
    actor_id: UUID,
    question_id: UUID,
    marks: Decimal,
    display_order: int | None = None,
) -> ExamQuestion:
    """
    Attaches a question from the question bank to a DRAFT examination.
    """
    if exam.creator_id != actor_id:
        raise ExamServiceError(
            "FORBIDDEN",
            "Faculty members cannot modify another faculty member's examinations.",
            status_code=403,
        )

    if exam.status != "DRAFT":
        raise ExamServiceError(
            "EXAM_IMMUTABLE",
            "Questions can only be added to DRAFT examinations.",
            status_code=409,
        )

    if marks <= Decimal("0.00"):
        raise ExamServiceError("INVALID_MARKS", "Marks must be greater than zero.")

    # Validate source question
    source_q = db.get(Question, question_id)
    if source_q is None:
        raise ExamServiceError("QUESTION_NOT_FOUND", "Source question does not exist.", status_code=404)

    if source_q.archived_at is not None:
        raise ExamServiceError(
            "ARCHIVED_QUESTION_INELIGIBLE",
            "Archived questions cannot be attached to an examination.",
        )

    # Check question limit
    if len(exam.questions) >= settings.MAX_QUESTIONS_PER_EXAM:
        raise ExamServiceError(
            "TOO_MANY_QUESTIONS",
            f"An examination cannot have more than {settings.MAX_QUESTIONS_PER_EXAM} questions.",
        )

    # Check duplicate question in exam
    for eq in exam.questions:
        if eq.source_question_id == question_id:
            raise ExamServiceError(
                "DUPLICATE_QUESTION_IN_EXAM",
                "This question is already attached to the examination.",
                status_code=409,
            )

    # Compute or validate display_order
    existing_orders = {eq.display_order for eq in exam.questions}
    if display_order is None:
        order = max(existing_orders, default=0) + 1
    else:
        if display_order < 1:
            raise ExamServiceError("INVALID_DISPLAY_ORDER", "Display order must be >= 1.")
        if display_order in existing_orders:
            raise ExamServiceError(
                "DUPLICATE_DISPLAY_ORDER",
                f"Display order {display_order} is already in use in this examination.",
                status_code=409,
            )
        order = display_order

    eq = ExamQuestion(
        exam_id=exam.id,
        source_question_id=source_q.id,
        prompt_snapshot=source_q.prompt,
        topic_code_snapshot=source_q.topic.code if source_q.topic else None,
        topic_name_snapshot=source_q.topic.name if source_q.topic else None,
        marks=marks,
        display_order=order,
    )
    db.add(eq)
    exam.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(eq)
    db.refresh(exam)
    return eq


def set_draft_questions(
    db: Session,
    *,
    exam: Exam,
    actor_id: UUID,
    items: list[ExamQuestionReorderItem],
) -> list[ExamQuestion]:
    """
    Replaces and reorders all attached questions in a DRAFT examination.
    """
    if exam.creator_id != actor_id:
        raise ExamServiceError(
            "FORBIDDEN",
            "Faculty members cannot modify another faculty member's examinations.",
            status_code=403,
        )

    if exam.status != "DRAFT":
        raise ExamServiceError(
            "EXAM_IMMUTABLE",
            "Questions can only be modified in DRAFT examinations.",
            status_code=409,
        )

    if len(items) > settings.MAX_QUESTIONS_PER_EXAM:
        raise ExamServiceError(
            "TOO_MANY_QUESTIONS",
            f"An examination cannot have more than {settings.MAX_QUESTIONS_PER_EXAM} questions.",
        )

    # Validate items
    question_ids = [item.question_id for item in items]
    if len(question_ids) != len(set(question_ids)):
        raise ExamServiceError(
            "DUPLICATE_QUESTION_IN_EXAM",
            "Duplicate questions found in the request list.",
            status_code=409,
        )

    orders = [item.display_order for item in items]
    if len(orders) != len(set(orders)):
        raise ExamServiceError(
            "DUPLICATE_DISPLAY_ORDER",
            "Duplicate display orders found in the request list.",
            status_code=409,
        )

    # Validate each question exists and is not archived
    source_questions: dict[UUID, Question] = {}
    for item in items:
        if item.marks <= Decimal("0.00"):
            raise ExamServiceError("INVALID_MARKS", "Marks must be greater than zero.")
        if item.display_order < 1:
            raise ExamServiceError("INVALID_DISPLAY_ORDER", "Display order must be >= 1.")

        sq = db.get(Question, item.question_id)
        if sq is None:
            raise ExamServiceError(
                "QUESTION_NOT_FOUND",
                f"Source question {item.question_id} not found.",
                status_code=404,
            )
        if sq.archived_at is not None:
            raise ExamServiceError(
                "ARCHIVED_QUESTION_INELIGIBLE",
                f"Source question {item.question_id} is archived and cannot be used.",
            )
        source_questions[item.question_id] = sq

    # Clear existing questions
    for eq in list(exam.questions):
        db.delete(eq)
    db.flush()

    # Insert replacement questions
    created: list[ExamQuestion] = []
    for item in items:
        sq = source_questions[item.question_id]
        new_eq = ExamQuestion(
            exam_id=exam.id,
            source_question_id=sq.id,
            prompt_snapshot=sq.prompt,
            topic_code_snapshot=sq.topic.code if sq.topic else None,
            topic_name_snapshot=sq.topic.name if sq.topic else None,
            marks=item.marks,
            display_order=item.display_order,
        )
        db.add(new_eq)
        created.append(new_eq)

    exam.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exam)
    return created


def remove_question_from_draft(
    db: Session,
    *,
    exam: Exam,
    actor_id: UUID,
    question_id: UUID,
) -> None:
    """
    Removes a question from a DRAFT examination.
    Accepts either ExamQuestion.id or Question.id.
    """
    if exam.creator_id != actor_id:
        raise ExamServiceError(
            "FORBIDDEN",
            "Faculty members cannot modify another faculty member's examinations.",
            status_code=403,
        )

    if exam.status != "DRAFT":
        raise ExamServiceError(
            "EXAM_IMMUTABLE",
            "Questions can only be removed from DRAFT examinations.",
            status_code=409,
        )

    target_eq = None
    for eq in exam.questions:
        if eq.id == question_id or eq.source_question_id == question_id:
            target_eq = eq
            break

    if target_eq is None:
        raise ExamServiceError(
            "QUESTION_NOT_IN_EXAM",
            "The specified question is not attached to this examination.",
            status_code=404,
        )

    db.delete(target_eq)
    exam.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exam)


def publish_exam(
    db: Session,
    *,
    exam_id: UUID,
    actor_id: UUID,
) -> Exam:
    """
    Publishes an examination atomically in a single database transaction.

    Concurrency and atomicity:
    - Locks the exam row using SELECT ... FOR UPDATE.
    - Idempotent: repeated publish on an already PUBLISHED exam returns current state.
    - Rejects publishing an UNPUBLISHED exam (409 conflict).
    - Rejects publishing an exam with no questions (400).
    - Validates source question options: 2..6 options, exactly 1 correct, non-empty text.
    - Rejects archived or missing source questions.
    - Materializes frozen ExamQuestion and ExamQuestionOption snapshot rows.
    - Transitions exam to PUBLISHED status and records published_at timestamp.
    - Commits atomically; rolls back completely on any error.
    """
    with db.begin_nested():
        # 1. Acquire row lock on Exam
        stmt = (
            select(Exam)
            .options(
                selectinload(Exam.questions).selectinload(ExamQuestion.options),
                selectinload(Exam.questions).joinedload(ExamQuestion.source_question),
            )
            .filter(Exam.id == exam_id)
            .with_for_update()
        )
        exam = db.scalars(stmt).first()
        if exam is None:
            raise ExamServiceError("EXAM_NOT_FOUND", "Examination not found.", status_code=404)

        # 2. Ownership check
        if exam.creator_id != actor_id:
            raise ExamServiceError(
                "FORBIDDEN",
                "Faculty members cannot publish another faculty member's examinations.",
                status_code=403,
            )

        # 3. Status checks
        if exam.status == "PUBLISHED":
            # Idempotent return of already-published exam
            return exam

        if exam.status == "UNPUBLISHED":
            raise ExamServiceError(
                "EXAM_ALREADY_UNPUBLISHED",
                "An unpublished examination cannot be republished. "
                "Create a new draft examination to revise assessment content.",
                status_code=409,
            )

        if exam.status != "DRAFT":
            raise ExamServiceError(
                "INVALID_EXAM_STATUS",
                f"Cannot publish examination with status '{exam.status}'.",
                status_code=409,
            )

        # 4. Validate exam fields
        if not exam.title or not exam.title.strip():
            raise ExamServiceError("EMPTY_TITLE", "Examination title cannot be empty.")
        if exam.duration_minutes <= 0 or exam.duration_minutes > settings.MAX_EXAM_DURATION_MINUTES:
            raise ExamServiceError(
                "INVALID_DURATION",
                f"Duration must be between 1 and {settings.MAX_EXAM_DURATION_MINUTES} minutes.",
            )

        # 5. Validate question attachments
        attached_questions = exam.questions
        if not attached_questions:
            raise ExamServiceError(
                "EMPTY_EXAM",
                "An examination must contain at least one question to be published.",
            )
        if len(attached_questions) > settings.MAX_QUESTIONS_PER_EXAM:
            raise ExamServiceError(
                "TOO_MANY_QUESTIONS",
                f"An examination cannot have more than {settings.MAX_QUESTIONS_PER_EXAM} questions.",
            )

        display_orders = [eq.display_order for eq in attached_questions]
        if len(display_orders) != len(set(display_orders)):
            raise ExamServiceError(
                "DUPLICATE_DISPLAY_ORDER",
                "Duplicate display orders found among examination questions.",
            )

        # 6. Validate each source question & options, and materialize snapshots
        now = datetime.now(timezone.utc)

        for eq in attached_questions:
            if eq.marks <= Decimal("0.00"):
                raise ExamServiceError("INVALID_MARKS", "Question marks must be greater than zero.")
            if eq.display_order < 1:
                raise ExamServiceError("INVALID_DISPLAY_ORDER", "Display order must be >= 1.")

            if eq.source_question_id is None:
                raise ExamServiceError(
                    "INVALID_QUESTION_REFERENCE",
                    "Examination question lacks source question reference.",
                )

            # Re-fetch source question to ensure current bank validation
            sq_stmt = (
                select(Question)
                .options(
                    joinedload(Question.options),
                    joinedload(Question.topic),
                )
                .filter(Question.id == eq.source_question_id)
            )
            sq = db.scalars(sq_stmt).unique().first()
            if sq is None:
                raise ExamServiceError(
                    "SOURCE_QUESTION_NOT_FOUND",
                    f"Source question {eq.source_question_id} not found.",
                )
            if sq.archived_at is not None:
                raise ExamServiceError(
                    "ARCHIVED_QUESTION_INELIGIBLE",
                    f"Question '{sq.prompt[:40]}...' is archived and cannot be published.",
                )

            # Validate options
            sq_options = sq.options
            if len(sq_options) < 2:
                raise ExamServiceError(
                    "TOO_FEW_OPTIONS",
                    f"Question '{sq.prompt[:40]}...' has fewer than 2 options.",
                )
            if len(sq_options) > settings.MAX_OPTIONS_PER_QUESTION:
                raise ExamServiceError(
                    "TOO_MANY_OPTIONS",
                    f"Question '{sq.prompt[:40]}...' exceeds maximum allowed options.",
                )

            correct_count = sum(1 for opt in sq_options if opt.is_correct)
            if correct_count != 1:
                raise ExamServiceError(
                    "SINGLE_CORRECT_REQUIRED",
                    f"Question '{sq.prompt[:40]}...' must have exactly one correct option.",
                )

            for opt in sq_options:
                if not opt.option_text or not opt.option_text.strip():
                    raise ExamServiceError(
                        "EMPTY_OPTION_TEXT",
                        f"Question '{sq.prompt[:40]}...' has empty option text.",
                    )

            # Freeze question snapshot fields
            eq.prompt_snapshot = sq.prompt
            eq.topic_code_snapshot = sq.topic.code if sq.topic else None
            eq.topic_name_snapshot = sq.topic.name if sq.topic else None

            # Remove any prior snapshot options (if re-publishing)
            for existing_opt in list(eq.options):
                db.delete(existing_opt)
            db.flush()

            # Materialize frozen options
            for opt in sq_options:
                eqo = ExamQuestionOption(
                    exam_question_id=eq.id,
                    option_text_snapshot=opt.option_text,
                    display_order=opt.display_order,
                    is_correct=opt.is_correct,
                )
                db.add(eqo)

        # 7. Transition exam status
        exam.status = "PUBLISHED"
        exam.published_at = now
        exam.updated_at = now

    db.commit()
    db.refresh(exam)
    return exam


def unpublish_exam(
    db: Session,
    *,
    exam_id: UUID,
    actor_id: UUID,
) -> Exam:
    """
    Unpublishes an examination.
    Blocks new attempt starts; existing attempts and snapshots remain intact.
    """
    stmt = select(Exam).filter(Exam.id == exam_id).with_for_update()
    exam = db.scalars(stmt).first()
    if exam is None:
        raise ExamServiceError("EXAM_NOT_FOUND", "Examination not found.", status_code=404)

    if exam.creator_id != actor_id:
        raise ExamServiceError(
            "FORBIDDEN",
            "Faculty members cannot unpublish another faculty member's examinations.",
            status_code=403,
        )

    if exam.status == "UNPUBLISHED":
        return exam

    if exam.status != "PUBLISHED":
        raise ExamServiceError(
            "INVALID_EXAM_STATUS",
            "Only published examinations can be unpublished.",
            status_code=409,
        )

    exam.status = "UNPUBLISHED"
    exam.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exam)
    return exam
