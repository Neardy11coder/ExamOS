"""
Question bank API routes for faculty authors.

Docs:
- docs/04_API_CONTRACT.md §3 Question bank endpoints
- docs/01_REQUIREMENTS.md FR-QUESTION-001 to FR-QUESTION-009
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import require_faculty, validate_csrf
from app.db.session import get_db
from app.models.user import User
from app.schemas.question import (
    QuestionCreate,
    QuestionOptionRead,
    QuestionRead,
    QuestionUpdate,
)
from app.schemas.topic import TopicRead
from app.services.question_service import (
    QuestionServiceError,
    archive_question,
    create_question,
    get_question,
    list_questions,
    update_question,
)

router = APIRouter(prefix="/questions", tags=["questions"])


def _serialize_question(q) -> QuestionRead:
    topic_data = TopicRead.model_validate(q.topic) if q.topic else None
    options_data = [
        QuestionOptionRead(
            id=o.id,
            option_text=o.option_text,
            display_order=o.display_order,
            is_correct=o.is_correct,
        )
        for o in sorted(q.options, key=lambda opt: opt.display_order)
    ]
    return QuestionRead(
        id=q.id,
        author_id=q.author_id,
        topic_id=q.topic_id,
        prompt=q.prompt,
        archived_at=q.archived_at,
        created_at=q.created_at,
        updated_at=q.updated_at,
        options=options_data,
        topic=topic_data,
    )


@router.get(
    "",
    response_model=list[QuestionRead],
    summary="List and filter question bank items",
)
def get_questions_list(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
    topic_id: Annotated[UUID | None, Query(description="Filter by topic UUID")] = None,
    search: Annotated[str | None, Query(description="Search in question prompt")] = None,
    include_archived: Annotated[bool, Query(description="Include archived questions")] = False,
) -> list[QuestionRead]:
    """
    List questions in the question bank.
    Requires FACULTY_ADMIN.
    """
    questions = list_questions(
        db,
        topic_id=topic_id,
        search=search,
        include_archived=include_archived,
    )
    return [_serialize_question(q) for q in questions]


@router.post(
    "",
    response_model=QuestionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(validate_csrf)],
    summary="Create a new question bank item with options",
)
def post_question(
    data: QuestionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> QuestionRead:
    """
    Create a new MCQ question and 2+ options (exactly one correct).
    Requires FACULTY_ADMIN and CSRF validation.
    """
    try:
        question = create_question(
            db,
            author_id=current_user.id,
            prompt=data.prompt,
            topic_id=data.topic_id,
            options_data=data.options,
        )
        return _serialize_question(question)
    except QuestionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.get(
    "/{question_id}",
    response_model=QuestionRead,
    summary="Retrieve question bank item details",
)
def get_single_question(
    question_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> QuestionRead:
    """
    Retrieve question bank item by UUID.
    Includes options and correct option flag.
    Requires FACULTY_ADMIN.
    """
    question = get_question(db, question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "QUESTION_NOT_FOUND", "message": "Question not found."}},
        )
    return _serialize_question(question)


@router.patch(
    "/{question_id}",
    response_model=QuestionRead,
    dependencies=[Depends(validate_csrf)],
    summary="Update question bank item prompt, topic, or options",
)
def patch_question(
    question_id: UUID,
    data: QuestionUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> QuestionRead:
    """
    Update eligible question fields.
    Enforces author ownership.
    Affects future snapshots only; existing published snapshots remain untouched.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    question = get_question(db, question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "QUESTION_NOT_FOUND", "message": "Question not found."}},
        )

    try:
        updated = update_question(
            db,
            question=question,
            actor_id=current_user.id,
            prompt=data.prompt,
            topic_id=data.topic_id,
            options_data=data.options,
        )
        return _serialize_question(updated)
    except QuestionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.post(
    "/{question_id}/archive",
    response_model=QuestionRead,
    dependencies=[Depends(validate_csrf)],
    summary="Soft-archive a question bank item",
)
def post_archive_question(
    question_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> QuestionRead:
    """
    Soft-archive a question. Prevents new usage in drafts/exams while preserving audit provenance.
    Enforces author ownership.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    question = get_question(db, question_id)
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "QUESTION_NOT_FOUND", "message": "Question not found."}},
        )

    try:
        archived = archive_question(
            db,
            question=question,
            actor_id=current_user.id,
        )
        return _serialize_question(archived)
    except QuestionServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )
