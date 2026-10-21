"""
Pydantic schemas for student examination attempts and answers.

Covers:
- docs/04_API_CONTRACT.md §4 Student exam catalogue and attempt API
- docs/04_API_CONTRACT.md §5 Faculty results and attempt list
- docs/01_REQUIREMENTS.md FR-STUD, FR-ATTEMPT, FR-TIME, FR-SAVE, FR-SUBMIT, FR-EXPIRE, FR-RESULT
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 1. Available exam catalogue (Student)
# ---------------------------------------------------------------------------

class AvailableExamItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    instructions: str
    duration_minutes: int
    question_count: int
    total_marks: Decimal
    has_attempt: bool
    attempt_id: UUID | None = None
    attempt_status: str | None = None


# ---------------------------------------------------------------------------
# 2. Student attempt detail & questions (Strictly confidential while active)
# ---------------------------------------------------------------------------

class StudentOptionRead(BaseModel):
    """Option payload delivered to student during active attempt. Omits is_correct."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    display_order: int


class StudentAnswerState(BaseModel):
    """Answer state for a specific question."""
    model_config = ConfigDict(from_attributes=True)

    selected_option_id: UUID | None = None
    marked_for_review: bool = False
    revision: int = 0


class StudentQuestionRead(BaseModel):
    """Question item with options and current answer state for active attempt."""
    model_config = ConfigDict(from_attributes=True)

    exam_question_id: UUID
    prompt: str
    marks: Decimal
    display_order: int
    options: list[StudentOptionRead]
    answer: StudentAnswerState


class AttemptExamInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    instructions: str = ""
    duration_minutes: int
    total_marks: Decimal


class AttemptDetailRead(BaseModel):
    """Full attempt workspace state returned on start or recovery."""
    model_config = ConfigDict(from_attributes=True)

    attempt_id: UUID
    status: str
    started_at: datetime
    deadline_at: datetime
    remaining_seconds: int
    exam: AttemptExamInfo
    questions: list[StudentQuestionRead]


# ---------------------------------------------------------------------------
# 3. Answer saving & optimistic concurrency
# ---------------------------------------------------------------------------

class AnswerSaveRequest(BaseModel):
    selected_option_id: UUID | None = None
    marked_for_review: bool = False
    expected_revision: int = Field(ge=0)
    mutation_id: UUID | str | None = None


class AnswerSaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    selected_option_id: UUID | None = None
    marked_for_review: bool
    revision: int
    saved_at: datetime


# ---------------------------------------------------------------------------
# 4. Submission
# ---------------------------------------------------------------------------

class SubmitAttemptRequest(BaseModel):
    submission_request_id: UUID | str | None = None


class SubmitAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_id: UUID
    status: str
    score: Decimal
    total_marks: Decimal
    finalized_at: datetime


# ---------------------------------------------------------------------------
# 5. Finalized results (Post-finalization disclosure per OD-04)
# ---------------------------------------------------------------------------

class ResultOptionRead(BaseModel):
    """Option payload after finalization; reveals is_correct."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    display_order: int
    is_correct: bool


class ResultQuestionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exam_question_id: UUID
    prompt: str
    marks: Decimal
    display_order: int
    topic_code: str | None = None
    topic_name: str | None = None
    student_selected_option_id: UUID | None = None
    is_correct: bool
    options: list[ResultOptionRead]


class AttemptResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_id: UUID
    exam_id: UUID
    exam_title: str
    status: str
    score: Decimal
    total_marks: Decimal
    percentage: Decimal
    started_at: datetime
    deadline_at: datetime
    finalized_at: datetime
    questions: list[ResultQuestionItem]


# ---------------------------------------------------------------------------
# 6. Faculty attempt list
# ---------------------------------------------------------------------------

class FacultyAttemptListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    student_id: UUID
    student_email: str
    student_display_name: str
    status: str
    started_at: datetime
    deadline_at: datetime
    finalized_at: datetime | None = None
    score: Decimal | None = None
    total_marks: Decimal
