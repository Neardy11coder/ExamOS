"""
Exam management, draft authoring, and atomic publishing API routes.

Docs:
- docs/04_API_CONTRACT.md §3 Faculty examination and question management
- docs/03_DATABASE_DESIGN.md §§3.5-3.7
- docs/01_REQUIREMENTS.md FR-EXAM-001 to FR-EXAM-010, OD-08
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import require_faculty, validate_csrf
from app.db.session import get_db
from app.models.exam import Exam
from app.models.user import User
from app.schemas.exam import (
    ExamCreate,
    ExamDetailRead,
    ExamDraftQuestionRead,
    ExamPublishResponse,
    ExamQuestionAttach,
    ExamQuestionOptionSnapshotRead,
    ExamQuestionReorderItem,
    ExamQuestionSnapshotRead,
    ExamRead,
    ExamUnpublishResponse,
    ExamUpdate,
)
from app.services.exam_service import (
    ExamServiceError,
    attach_question_to_draft,
    create_exam,
    get_exam,
    list_exams,
    publish_exam,
    remove_question_from_draft,
    set_draft_questions,
    unpublish_exam,
    update_draft_exam,
)

router = APIRouter(prefix="/exams", tags=["exams"])


def _calculate_exam_metrics(exam: Exam) -> tuple[int, Decimal]:
    count = len(exam.questions)
    total_marks = sum((eq.marks for eq in exam.questions), Decimal("0.00"))
    return count, total_marks


def _serialize_exam_summary(exam: Exam) -> ExamRead:
    count, total_marks = _calculate_exam_metrics(exam)
    return ExamRead(
        id=exam.id,
        creator_id=exam.creator_id,
        title=exam.title,
        instructions=exam.instructions,
        duration_minutes=exam.duration_minutes,
        status=exam.status,
        question_count=count,
        total_marks=total_marks,
        published_at=exam.published_at,
        created_at=exam.created_at,
        updated_at=exam.updated_at,
    )


def _serialize_exam_detail(exam: Exam) -> ExamDetailRead:
    count, total_marks = _calculate_exam_metrics(exam)
    sorted_eqs = sorted(exam.questions, key=lambda q: q.display_order)

    questions_data: list[ExamQuestionSnapshotRead | ExamDraftQuestionRead] = []

    if exam.status in ("PUBLISHED", "UNPUBLISHED"):
        for eq in sorted_eqs:
            options_data = [
                ExamQuestionOptionSnapshotRead(
                    id=opt.id,
                    option_text_snapshot=opt.option_text_snapshot,
                    display_order=opt.display_order,
                    is_correct=opt.is_correct,
                )
                for opt in sorted(eq.options, key=lambda o: o.display_order)
            ]
            questions_data.append(
                ExamQuestionSnapshotRead(
                    id=eq.id,
                    source_question_id=eq.source_question_id,
                    prompt_snapshot=eq.prompt_snapshot,
                    topic_code_snapshot=eq.topic_code_snapshot,
                    topic_name_snapshot=eq.topic_name_snapshot,
                    marks=eq.marks,
                    display_order=eq.display_order,
                    options=options_data,
                )
            )
    else:
        # DRAFT: show draft question associations
        for eq in sorted_eqs:
            sq = eq.source_question
            prompt_text = sq.prompt if sq else eq.prompt_snapshot
            topic_code = (
                sq.topic.code if sq and sq.topic else eq.topic_code_snapshot
            )
            topic_name = (
                sq.topic.name if sq and sq.topic else eq.topic_name_snapshot
            )
            opt_count = len(sq.options) if sq else 0

            questions_data.append(
                ExamDraftQuestionRead(
                    id=eq.id,
                    source_question_id=eq.source_question_id,
                    prompt=prompt_text,
                    topic_code=topic_code,
                    topic_name=topic_name,
                    marks=eq.marks,
                    display_order=eq.display_order,
                    options_count=opt_count,
                )
            )

    return ExamDetailRead(
        id=exam.id,
        creator_id=exam.creator_id,
        title=exam.title,
        instructions=exam.instructions,
        duration_minutes=exam.duration_minutes,
        status=exam.status,
        question_count=count,
        total_marks=total_marks,
        published_at=exam.published_at,
        created_at=exam.created_at,
        updated_at=exam.updated_at,
        questions=questions_data,
    )


@router.get(
    "",
    response_model=list[ExamRead],
    summary="List all faculty examinations",
)
def get_exams_list(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> list[ExamRead]:
    """
    Returns faculty's complete exam list with title, duration, status, question count, and timestamps.
    Requires FACULTY_ADMIN.
    """
    exams = list_exams(db)
    return [_serialize_exam_summary(e) for e in exams]


@router.post(
    "",
    response_model=ExamRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(validate_csrf)],
    summary="Create a new draft examination",
)
def post_create_exam(
    data: ExamCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamRead:
    """
    Creates a new DRAFT examination.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    try:
        exam = create_exam(
            db,
            creator_id=current_user.id,
            title=data.title,
            instructions=data.instructions,
            duration_minutes=data.duration_minutes,
        )
        return _serialize_exam_summary(exam)
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.get(
    "/{exam_id}",
    response_model=ExamDetailRead,
    summary="Retrieve examination details and question associations",
)
def get_single_exam(
    exam_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamDetailRead:
    """
    Returns exam metadata. For a draft, returns editable question associations.
    For a published/unpublished exam, returns the immutable frozen assessment summary.
    Requires FACULTY_ADMIN.
    """
    exam = get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXAM_NOT_FOUND", "message": "Examination not found."}},
        )
    return _serialize_exam_detail(exam)


@router.patch(
    "/{exam_id}",
    response_model=ExamRead,
    dependencies=[Depends(validate_csrf)],
    summary="Update draft examination metadata",
)
def patch_exam(
    exam_id: UUID,
    data: ExamUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamRead:
    """
    Updates title, instructions, or duration only while in DRAFT status.
    Rejects modification of published or unpublished examinations.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    exam = get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXAM_NOT_FOUND", "message": "Examination not found."}},
        )

    try:
        updated = update_draft_exam(
            db,
            exam=exam,
            actor_id=current_user.id,
            title=data.title,
            instructions=data.instructions,
            duration_minutes=data.duration_minutes,
        )
        return _serialize_exam_summary(updated)
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.post(
    "/{exam_id}/questions",
    response_model=ExamDetailRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(validate_csrf)],
    summary="Attach a question to a draft examination",
)
def post_attach_question(
    exam_id: UUID,
    data: ExamQuestionAttach,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamDetailRead:
    """
    Attaches a question from the question bank to a DRAFT examination.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    exam = get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXAM_NOT_FOUND", "message": "Examination not found."}},
        )

    try:
        attach_question_to_draft(
            db,
            exam=exam,
            actor_id=current_user.id,
            question_id=data.question_id,
            marks=data.marks,
            display_order=data.display_order,
        )
        return _serialize_exam_detail(exam)
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.put(
    "/{exam_id}/questions",
    response_model=ExamDetailRead,
    dependencies=[Depends(validate_csrf)],
    summary="Replace or reorder all questions in a draft examination",
)
def put_set_draft_questions(
    exam_id: UUID,
    items: list[ExamQuestionReorderItem],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamDetailRead:
    """
    Sets or reorders the complete list of questions in a DRAFT examination.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    exam = get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXAM_NOT_FOUND", "message": "Examination not found."}},
        )

    try:
        set_draft_questions(
            db,
            exam=exam,
            actor_id=current_user.id,
            items=items,
        )
        return _serialize_exam_detail(exam)
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.delete(
    "/{exam_id}/questions/{question_id}",
    response_model=ExamDetailRead,
    dependencies=[Depends(validate_csrf)],
    summary="Remove a question from a draft examination",
)
def delete_remove_question(
    exam_id: UUID,
    question_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamDetailRead:
    """
    Removes a question from a DRAFT examination.
    Accepts question_id or exam_question_id.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    exam = get_exam(db, exam_id)
    if exam is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "EXAM_NOT_FOUND", "message": "Examination not found."}},
        )

    try:
        remove_question_from_draft(
            db,
            exam=exam,
            actor_id=current_user.id,
            question_id=question_id,
        )
        return _serialize_exam_detail(exam)
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.post(
    "/{exam_id}/publish",
    response_model=ExamPublishResponse,
    dependencies=[Depends(validate_csrf)],
    summary="Publish draft examination atomically into immutable snapshot",
)
def post_publish_exam(
    exam_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamPublishResponse:
    """
    Validates draft examination and atomically freezes its questions and options into immutable snapshots.
    Must fail atomically if any validation check fails.
    Duplicate requests return existing published outcome safely.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    try:
        exam = publish_exam(
            db,
            exam_id=exam_id,
            actor_id=current_user.id,
        )
        count, total_marks = _calculate_exam_metrics(exam)
        return ExamPublishResponse(
            id=exam.id,
            title=exam.title,
            status=exam.status,
            duration_minutes=exam.duration_minutes,
            question_count=count,
            total_marks=total_marks,
            published_at=exam.published_at,
        )
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )


@router.post(
    "/{exam_id}/unpublish",
    response_model=ExamUnpublishResponse,
    dependencies=[Depends(validate_csrf)],
    summary="Unpublish an examination",
)
def post_unpublish_exam(
    exam_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_faculty)],
) -> ExamUnpublishResponse:
    """
    Unpublishes an examination.
    Blocks new attempt starts; existing attempts and snapshots remain intact.
    Requires FACULTY_ADMIN and CSRF validation.
    """
    try:
        exam = unpublish_exam(
            db,
            exam_id=exam_id,
            actor_id=current_user.id,
        )
        return ExamUnpublishResponse(
            id=exam.id,
            title=exam.title,
            status=exam.status,
            published_at=exam.published_at,
        )
    except ExamServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": {"code": exc.code, "message": exc.message}},
        )
