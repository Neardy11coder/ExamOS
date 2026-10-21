from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


class ExamCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Exam title")
    instructions: str = Field(default="", description="Exam instructions")
    duration_minutes: int = Field(
        ...,
        ge=1,
        le=settings.MAX_EXAM_DURATION_MINUTES,
        description=f"Duration in minutes (max {settings.MAX_EXAM_DURATION_MINUTES})",
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Exam title cannot be empty or whitespace only.")
        return trimmed


class ExamUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    instructions: str | None = Field(default=None)
    duration_minutes: int | None = Field(
        default=None,
        ge=1,
        le=settings.MAX_EXAM_DURATION_MINUTES,
    )

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str | None) -> str | None:
        if v is not None:
            trimmed = v.strip()
            if not trimmed:
                raise ValueError("Exam title cannot be empty or whitespace only.")
            return trimmed
        return v


class ExamQuestionAttach(BaseModel):
    question_id: UUID = Field(..., description="Source question UUID")
    marks: Decimal = Field(
        default=Decimal("1.00"),
        gt=Decimal("0.00"),
        le=Decimal("999.99"),
        description="Marks for this question (positive)",
    )
    display_order: int | None = Field(
        default=None,
        ge=1,
        description="Display order (1-indexed); defaults to next available",
    )


class ExamQuestionReorderItem(BaseModel):
    question_id: UUID
    marks: Decimal = Field(default=Decimal("1.00"), gt=Decimal("0.00"), le=Decimal("999.99"))
    display_order: int = Field(..., ge=1)


class ExamQuestionOptionSnapshotRead(BaseModel):
    id: UUID
    option_text_snapshot: str
    display_order: int
    is_correct: bool

    model_config = ConfigDict(from_attributes=True)


class ExamQuestionSnapshotRead(BaseModel):
    id: UUID
    source_question_id: UUID | None
    prompt_snapshot: str
    topic_code_snapshot: str | None
    topic_name_snapshot: str | None
    marks: Decimal
    display_order: int
    options: list[ExamQuestionOptionSnapshotRead] = []

    model_config = ConfigDict(from_attributes=True)


class ExamDraftQuestionRead(BaseModel):
    id: UUID
    source_question_id: UUID | None
    prompt: str
    topic_code: str | None
    topic_name: str | None
    marks: Decimal
    display_order: int
    options_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ExamRead(BaseModel):
    id: UUID
    creator_id: UUID
    title: str
    instructions: str
    duration_minutes: int
    status: str
    question_count: int
    total_marks: Decimal
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExamDetailRead(ExamRead):
    questions: list[ExamQuestionSnapshotRead | ExamDraftQuestionRead] = []

    model_config = ConfigDict(from_attributes=True)


class ExamPublishResponse(BaseModel):
    id: UUID
    title: str
    status: str
    duration_minutes: int
    question_count: int
    total_marks: Decimal
    published_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExamUnpublishResponse(BaseModel):
    id: UUID
    title: str
    status: str
    published_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
