"""
SQLAlchemy ORM models for exams and immutable publication snapshots:
`exams`, `exam_questions`, and `exam_question_options`.

DB design §3.5: exams (UUID PK, creator_id FK->users.id, title, instructions,
                duration_minutes, status, published_at, audit columns).
DB design §3.6: exam_questions (frozen published snapshot: UUID PK, exam_id FK->exams.id,
                source_question_id nullable FK->questions.id, prompt_snapshot,
                topic_code_snapshot, topic_name_snapshot, marks numeric > 0, display_order >= 1,
                UNIQUE(exam_id, display_order), UNIQUE(id, exam_id)).
DB design §3.7: exam_question_options (frozen options: UUID PK, exam_question_id FK->exam_questions.id,
                option_text_snapshot, display_order >= 1, is_correct boolean,
                UNIQUE(exam_question_id, display_order), UNIQUE(exam_question_id, id),
                partial unique index for single correct).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.question import Question
    from app.models.user import User


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        sa.String(255),
        nullable=False,
    )
    instructions: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        server_default="",
        default="",
    )
    duration_minutes: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default="DRAFT",
        default="DRAFT",
    )
    published_at: Mapped[datetime | None] = mapped_column(
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
    creator: Mapped[User] = relationship("User", foreign_keys=[creator_id])
    questions: Mapped[list[ExamQuestion]] = relationship(
        "ExamQuestion",
        back_populates="exam",
        cascade="all, delete-orphan",
        order_by="ExamQuestion.display_order",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'UNPUBLISHED')",
            name="ck_exams_status",
        ),
        sa.CheckConstraint(
            "duration_minutes > 0",
            name="ck_exams_duration_minutes_positive",
        ),
        sa.CheckConstraint(
            "char_length(trim(title)) > 0",
            name="ck_exams_title_nonempty",
        ),
        sa.Index(
            "ix_exams_status_created_at",
            "status",
            "created_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Exam id={self.id} title={self.title!r} status={self.status}>"


class ExamQuestion(Base):
    __tablename__ = "exam_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("exams.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_question_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    prompt_snapshot: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
    )
    topic_code_snapshot: Mapped[str | None] = mapped_column(
        sa.String(50),
        nullable=True,
    )
    topic_name_snapshot: Mapped[str | None] = mapped_column(
        sa.String(150),
        nullable=True,
    )
    marks: Mapped[Decimal] = mapped_column(
        sa.Numeric(5, 2),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )

    # Relationships
    exam: Mapped[Exam] = relationship("Exam", back_populates="questions")
    source_question: Mapped[Question | None] = relationship("Question", back_populates="snapshots")
    options: Mapped[list[ExamQuestionOption]] = relationship(
        "ExamQuestionOption",
        back_populates="exam_question",
        cascade="all, delete-orphan",
        order_by="ExamQuestionOption.display_order",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "exam_id",
            "display_order",
            name="uq_exam_questions_exam_display_order",
        ),
        sa.UniqueConstraint(
            "id",
            "exam_id",
            name="uq_exam_questions_id_exam_id",
        ),
        sa.CheckConstraint(
            "marks > 0",
            name="ck_exam_questions_marks_positive",
        ),
        sa.CheckConstraint(
            "display_order >= 1",
            name="ck_exam_questions_display_order_positive",
        ),
        sa.CheckConstraint(
            "char_length(trim(prompt_snapshot)) > 0",
            name="ck_exam_questions_prompt_snapshot_nonempty",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExamQuestion id={self.id} exam_id={self.exam_id} order={self.display_order}>"


class ExamQuestionOption(Base):
    __tablename__ = "exam_question_options"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("exam_questions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    option_text_snapshot: Mapped[str] = mapped_column(
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
    )

    # Relationships
    exam_question: Mapped[ExamQuestion] = relationship("ExamQuestion", back_populates="options")

    __table_args__ = (
        sa.UniqueConstraint(
            "exam_question_id",
            "display_order",
            name="uq_exam_question_options_question_display_order",
        ),
        sa.UniqueConstraint(
            "exam_question_id",
            "id",
            name="uq_exam_question_options_question_id",
        ),
        sa.Index(
            "uq_exam_question_options_single_correct",
            "exam_question_id",
            unique=True,
            postgresql_where=sa.text("is_correct IS TRUE"),
        ),
        sa.CheckConstraint(
            "display_order >= 1",
            name="ck_exam_question_options_display_order_positive",
        ),
        sa.CheckConstraint(
            "char_length(trim(option_text_snapshot)) > 0",
            name="ck_exam_question_options_text_snapshot_nonempty",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ExamQuestionOption id={self.id} order={self.display_order} correct={self.is_correct}>"
