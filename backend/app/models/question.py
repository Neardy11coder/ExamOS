"""
SQLAlchemy ORM models for authoring question bank: `questions` and `question_options`.

DB design §3.3: questions (UUID PK, author_id FK->users.id, topic_id nullable FK->topics.id,
                prompt text non-empty, archived_at timestamptz nullable, audit columns).
DB design §3.4: question_options (UUID PK, question_id FK->questions.id ON DELETE RESTRICT,
                option_text non-empty, display_order >= 1, is_correct boolean,
                UNIQUE(question_id, display_order), partial unique index for single correct).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.exam import ExamQuestion
    from app.models.topic import Topic
    from app.models.user import User


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("topics.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    author: Mapped[User] = relationship("User", foreign_keys=[author_id])
    topic: Mapped[Topic | None] = relationship("Topic", back_populates="questions")
    options: Mapped[list[QuestionOption]] = relationship(
        "QuestionOption",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionOption.display_order",
    )
    snapshots: Mapped[list[ExamQuestion]] = relationship(
        "ExamQuestion",
        back_populates="source_question",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "char_length(trim(prompt)) > 0",
            name="ck_questions_prompt_nonempty",
        ),
        sa.Index(
            "ix_questions_topic_archived",
            "topic_id",
            "archived_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Question id={self.id} prompt={self.prompt[:30]!r}>"


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    option_text: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    is_correct: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=False,
        server_default=sa.false(),
    )

    # Relationships
    question: Mapped[Question] = relationship("Question", back_populates="options")

    __table_args__ = (
        sa.UniqueConstraint(
            "question_id",
            "display_order",
            name="uq_question_options_question_display_order",
        ),
        sa.Index(
            "uq_question_options_single_correct",
            "question_id",
            unique=True,
            postgresql_where=sa.text("is_correct IS TRUE"),
        ),
        sa.CheckConstraint(
            "display_order >= 1",
            name="ck_question_options_display_order_positive",
        ),
        sa.CheckConstraint(
            "char_length(trim(option_text)) > 0",
            name="ck_question_options_text_nonempty",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<QuestionOption id={self.id} order={self.display_order} correct={self.is_correct}>"
