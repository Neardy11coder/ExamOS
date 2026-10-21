"""
Attempt workspace, answer autosave, submission, and finalized result endpoints.

Docs:
- docs/04_API_CONTRACT.md §4 Student exam catalogue and attempt API
- docs/01_REQUIREMENTS.md FR-STUD, FR-ATTEMPT, FR-TIME, FR-SAVE, FR-SUBMIT, FR-EXPIRE, FR-RESULT
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_student, validate_csrf
from app.db.session import get_db
from app.models.user import User
from app.schemas.attempt import (
    AnswerSaveRequest,
    AnswerSaveResponse,
    AttemptDetailRead,
    AttemptResultResponse,
    SubmitAttemptRequest,
    SubmitAttemptResponse,
)
from app.services.attempt_service import (
    AttemptRevisionConflictError,
    AttemptServiceError,
    get_attempt,
    get_attempt_result,
    save_answer,
    submit_attempt,
)

router = APIRouter(prefix="/attempts", tags=["attempts"])


@router.get(
    "/{attempt_id}",
    response_model=AttemptDetailRead,
    summary="Get current attempt workspace state",
)
def get_attempt_endpoint(
    attempt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_student)],
) -> AttemptDetailRead:
    """
    Returns current attempt status, remaining time, saved responses, and review flags.
    Enforces student ownership and performs lazy expiry.
    """
    try:
        return get_attempt(db, attempt_id=attempt_id, student_id=current_user.id)
    except AttemptServiceError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": {"code": e.code, "message": e.message, "details": e.details}},
        )


@router.put(
    "/{attempt_id}/answers/{exam_question_id}",
    response_model=AnswerSaveResponse,
    summary="Save or update an answer to an examination question",
)
def save_answer_endpoint(
    attempt_id: UUID,
    exam_question_id: UUID,
    payload: AnswerSaveRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_student)],
    _csrf: Annotated[None, Depends(validate_csrf)],
) -> AnswerSaveResponse:
    """
    Durably persists an answer or review flag change.
    Validates deadline, question/option ownership, and optimistic revision.
    """
    try:
        return save_answer(
            db,
            attempt_id=attempt_id,
            student_id=current_user.id,
            exam_question_id=exam_question_id,
            payload=payload,
        )
    except AttemptRevisionConflictError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": {"code": e.code, "message": e.message, "details": e.canonical_state}},
        )
    except AttemptServiceError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": {"code": e.code, "message": e.message, "details": e.details}},
        )


@router.post(
    "/{attempt_id}/submit",
    response_model=SubmitAttemptResponse,
    summary="Submit an examination attempt",
)
def submit_attempt_endpoint(
    attempt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_student)],
    _csrf: Annotated[None, Depends(validate_csrf)],
    payload: SubmitAttemptRequest | None = None,
) -> SubmitAttemptResponse:
    """
    Submits an examination attempt.
    Server time < deadline_at commits SUBMITTED; at/after deadline commits EXPIRED.
    Atomically scores the attempt. Repeated requests return the existing outcome.
    """
    try:
        return submit_attempt(
            db,
            attempt_id=attempt_id,
            student_id=current_user.id,
            payload=payload,
        )
    except AttemptServiceError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": {"code": e.code, "message": e.message, "details": e.details}},
        )


@router.get(
    "/{attempt_id}/result",
    response_model=AttemptResultResponse,
    summary="Get finalized examination result",
)
def get_result_endpoint(
    attempt_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AttemptResultResponse:
    """
    Returns finalized score and per-question correctness breakdown.
    Accessible to student owner or faculty.
    Requires attempt to be in terminal status (SUBMITTED or EXPIRED).
    """
    try:
        return get_attempt_result(
            db,
            attempt_id=attempt_id,
            user_id=current_user.id,
            user_role=current_user.role,
        )
    except AttemptServiceError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": {"code": e.code, "message": e.message, "details": e.details}},
        )
