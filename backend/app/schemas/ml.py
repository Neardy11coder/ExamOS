"""
Pydantic schemas for ML Topic Suggestions (M4-ML-1 / docs/04_API_CONTRACT.md § 8).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TopicSuggestionRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=5000, description="Question prompt text")
    options: list[str] | None = Field(default=None, max_length=10, description="Optional list of option texts")

    model_config = ConfigDict(extra="forbid")

    @field_validator("prompt")
    @classmethod
    def validate_prompt_not_blank(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Question prompt cannot be empty or whitespace only.")
        return trimmed

    @field_validator("options")
    @classmethod
    def validate_options(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [opt.strip() for opt in v if opt is not None]
        for opt in cleaned:
            if len(opt) > 1000:
                raise ValueError("Option text exceeds maximum length of 1000 characters.")
        return cleaned


class TopicSuggestionDetails(BaseModel):
    topic_code: str = Field(..., description="Predicted taxonomy topic code")
    topic_name: str = Field(..., description="Human-readable taxonomy topic display name")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Predicted probability confidence")
    threshold: float = Field(..., ge=0.0, le=1.0, description="Configured confidence threshold applied")

    model_config = ConfigDict(extra="forbid")


class TopicSuggestionResponse(BaseModel):
    available: bool = Field(..., description="True if a valid high-confidence suggestion is available")
    suggestion: TopicSuggestionDetails | None = Field(default=None, description="Suggestion details when available is True")
    reason: str | None = Field(default=None, description="Reason code if available is False (e.g. LOW_CONFIDENCE, MODEL_NOT_FOUND)")

    model_config = ConfigDict(extra="forbid")
