from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import settings
from app.schemas.topic import TopicRead


class QuestionOptionCreate(BaseModel):
    text: str = Field(..., min_length=1, description="Option display text")
    is_correct: bool = Field(default=False, description="Whether this option is correct")
    display_order: int | None = Field(default=None, ge=1, description="1-indexed display order")

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Option text cannot be empty or whitespace only.")
        return trimmed


class QuestionOptionRead(BaseModel):
    id: UUID
    option_text: str
    display_order: int
    is_correct: bool

    model_config = ConfigDict(from_attributes=True)


class QuestionCreate(BaseModel):
    prompt: str = Field(..., min_length=1, description="Question prompt text")
    topic_id: UUID | None = Field(default=None, description="Associated topic UUID or null")
    options: list[QuestionOptionCreate] = Field(..., description="List of MCQ options")

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Question prompt cannot be empty or whitespace only.")
        return trimmed

    @model_validator(mode="after")
    def validate_options_constraint(self) -> "QuestionCreate":
        opts = self.options
        if len(opts) < 2:
            raise ValueError("A question must have at least 2 options.")
        if len(opts) > settings.MAX_OPTIONS_PER_QUESTION:
            raise ValueError(
                f"A question cannot have more than {settings.MAX_OPTIONS_PER_QUESTION} options."
            )

        correct_count = sum(1 for o in opts if o.is_correct)
        if correct_count != 1:
            raise ValueError("A question must have exactly one correct option.")

        # If display_orders are provided, ensure no duplicates and >= 1
        orders = [o.display_order for o in opts if o.display_order is not None]
        if orders and len(orders) != len(set(orders)):
            raise ValueError("Duplicate display_order found in options.")

        return self


class QuestionUpdate(BaseModel):
    prompt: str | None = Field(default=None, description="Updated prompt text")
    topic_id: UUID | None = Field(default=None, description="Updated topic UUID or null")
    options: list[QuestionOptionCreate] | None = Field(default=None, description="Updated options")

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str | None) -> str | None:
        if v is not None:
            trimmed = v.strip()
            if not trimmed:
                raise ValueError("Question prompt cannot be empty or whitespace only.")
            return trimmed
        return v

    @model_validator(mode="after")
    def validate_options_constraint(self) -> "QuestionUpdate":
        if self.options is not None:
            opts = self.options
            if len(opts) < 2:
                raise ValueError("A question must have at least 2 options.")
            if len(opts) > settings.MAX_OPTIONS_PER_QUESTION:
                raise ValueError(
                    f"A question cannot have more than {settings.MAX_OPTIONS_PER_QUESTION} options."
                )

            correct_count = sum(1 for o in opts if o.is_correct)
            if correct_count != 1:
                raise ValueError("A question must have exactly one correct option.")

            orders = [o.display_order for o in opts if o.display_order is not None]
            if orders and len(orders) != len(set(orders)):
                raise ValueError("Duplicate display_order found in options.")

        return self


class QuestionRead(BaseModel):
    id: UUID
    author_id: UUID
    topic_id: UUID | None
    prompt: str
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    options: list[QuestionOptionRead] = []
    topic: TopicRead | None = None

    model_config = ConfigDict(from_attributes=True)
