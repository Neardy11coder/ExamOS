"""
Service functions for Question Bank authoring, options management, and soft archiving.

Docs:
- docs/04_API_CONTRACT.md §3 Question bank endpoints
- docs/03_DATABASE_DESIGN.md §§3.3-3.4
- docs/01_REQUIREMENTS.md FR-QUESTION-001 to FR-QUESTION-009
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.question import Question, QuestionOption
from app.models.topic import Topic
from app.schemas.question import QuestionOptionCreate


class QuestionServiceError(Exception):
    """Base exception for question service errors."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def create_question(
    db: Session,
    *,
    author_id: UUID,
    prompt: str,
    topic_id: UUID | None = None,
    options_data: list[QuestionOptionCreate],
) -> Question:
    """
    Creates a new MCQ question and its options in the question bank.

    Validates:
    - prompt non-empty after trim.
    - topic exists and is active (if provided).
    - 2 <= options count <= settings.MAX_OPTIONS_PER_QUESTION (6).
    - exactly one correct option.
    - stable sequential display_order >= 1.
    """
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise QuestionServiceError("EMPTY_PROMPT", "Question prompt cannot be empty.")

    if topic_id is not None:
        topic = db.get(Topic, topic_id)
        if topic is None or not topic.is_active:
            raise QuestionServiceError(
                "INVALID_TOPIC", "The referenced topic does not exist or is inactive."
            )

    if len(options_data) < 2:
        raise QuestionServiceError(
            "TOO_FEW_OPTIONS", "A question must have at least 2 options."
        )
    if len(options_data) > settings.MAX_OPTIONS_PER_QUESTION:
        raise QuestionServiceError(
            "TOO_MANY_OPTIONS",
            f"A question cannot have more than {settings.MAX_OPTIONS_PER_QUESTION} options.",
        )

    correct_count = sum(1 for o in options_data if o.is_correct)
    if correct_count != 1:
        raise QuestionServiceError(
            "SINGLE_CORRECT_REQUIRED",
            "A question must have exactly one option marked as correct.",
        )

    question = Question(
        author_id=author_id,
        topic_id=topic_id,
        prompt=cleaned_prompt,
    )
    db.add(question)
    db.flush()  # Generate question.id for options

    for idx, opt_data in enumerate(options_data, start=1):
        order = opt_data.display_order if opt_data.display_order is not None else idx
        text_clean = opt_data.text.strip()
        if not text_clean:
            raise QuestionServiceError(
                "EMPTY_OPTION_TEXT", "Option text cannot be empty or whitespace only."
            )

        option = QuestionOption(
            question_id=question.id,
            option_text=text_clean,
            display_order=order,
            is_correct=opt_data.is_correct,
        )
        db.add(option)

    db.commit()
    db.refresh(question)
    return question


def list_questions(
    db: Session,
    *,
    topic_id: UUID | None = None,
    search: str | None = None,
    include_archived: bool = False,
) -> list[Question]:
    """
    Lists and filters question bank items with options and topic pre-loaded.
    """
    query = (
        select(Question)
        .options(
            joinedload(Question.options),
            joinedload(Question.topic),
        )
        .order_by(Question.created_at.desc())
    )

    if not include_archived:
        query = query.filter(Question.archived_at.is_(None))

    if topic_id is not None:
        query = query.filter(Question.topic_id == topic_id)

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(Question.prompt.ilike(term))

    return list(db.scalars(query).unique().all())


def get_question(db: Session, question_id: UUID) -> Question | None:
    """
    Retrieves a single question by UUID with options and topic joined.
    """
    stmt = (
        select(Question)
        .options(
            joinedload(Question.options),
            joinedload(Question.topic),
        )
        .filter(Question.id == question_id)
    )
    return db.scalars(stmt).unique().first()


def update_question(
    db: Session,
    *,
    question: Question,
    actor_id: UUID,
    prompt: str | None = None,
    topic_id: UUID | None = None,
    options_data: list[QuestionOptionCreate] | None = None,
) -> Question:
    """
    Updates authoring question fields.
    Enforces author ownership and prevents mutating archived questions.
    """
    if question.author_id != actor_id:
        raise QuestionServiceError(
            "FORBIDDEN",
            "Faculty members cannot modify another faculty member's questions.",
            status_code=403,
        )

    if question.archived_at is not None:
        raise QuestionServiceError(
            "ARCHIVED_QUESTION_IMMUTABLE",
            "Archived questions cannot be modified.",
            status_code=400,
        )

    if prompt is not None:
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise QuestionServiceError(
                "EMPTY_PROMPT", "Question prompt cannot be empty."
            )
        question.prompt = clean_prompt

    if topic_id is not None:
        topic = db.get(Topic, topic_id)
        if topic is None or not topic.is_active:
            raise QuestionServiceError(
                "INVALID_TOPIC", "The referenced topic does not exist or is inactive."
            )
        question.topic_id = topic_id

    if options_data is not None:
        if len(options_data) < 2:
            raise QuestionServiceError(
                "TOO_FEW_OPTIONS", "A question must have at least 2 options."
            )
        if len(options_data) > settings.MAX_OPTIONS_PER_QUESTION:
            raise QuestionServiceError(
                "TOO_MANY_OPTIONS",
                f"A question cannot have more than {settings.MAX_OPTIONS_PER_QUESTION} options.",
            )

        correct_count = sum(1 for o in options_data if o.is_correct)
        if correct_count != 1:
            raise QuestionServiceError(
                "SINGLE_CORRECT_REQUIRED",
                "A question must have exactly one option marked as correct.",
            )

        # Clear existing options
        for opt in list(question.options):
            db.delete(opt)
        db.flush()

        # Add replacement options
        for idx, opt_data in enumerate(options_data, start=1):
            order = opt_data.display_order if opt_data.display_order is not None else idx
            text_clean = opt_data.text.strip()
            if not text_clean:
                raise QuestionServiceError(
                    "EMPTY_OPTION_TEXT", "Option text cannot be empty or whitespace only."
                )

            new_opt = QuestionOption(
                question_id=question.id,
                option_text=text_clean,
                display_order=order,
                is_correct=opt_data.is_correct,
            )
            db.add(new_opt)

    question.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(question)
    return question


def archive_question(
    db: Session,
    *,
    question: Question,
    actor_id: UUID,
) -> Question:
    """
    Soft-archives a question bank entry. Does not delete row or options.
    """
    if question.author_id != actor_id:
        raise QuestionServiceError(
            "FORBIDDEN",
            "Faculty members cannot archive another faculty member's questions.",
            status_code=403,
        )

    if question.archived_at is None:
        question.archived_at = datetime.now(timezone.utc)
        question.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(question)

    return question
