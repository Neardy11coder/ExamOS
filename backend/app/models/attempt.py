"""
SQLAlchemy ORM models for student examination attempts and answers:
`attempts` and `attempt_answers`.

DB design §3.8: attempts (UUID PK, student_id FK->users.id, exam_id FK->exams.id,
                status: IN_PROGRESS, SUBMITTED, EXPIRED; started_at, deadline_at,
                finalized_at nullable, score nullable, last_seen_at nullable,
                created_at, updated_at, UNIQUE(student_id, exam_id), UNIQUE(id, exam_id),
                CHECK(deadline_at > started_at), paired status checks).
DB design §3.9: attempt_answers (UUID PK, attempt_id FK, exam_id FK, exam_question_id FK,
                selected_option_id nullable FK, marked_for_review boolean default false,
                revision integer >= 0 default 0, updated_at,
                UNIQUE(attempt_id, exam_question_id),
                composite FK (attempt_id, exam_id) -> attempts(id, exam_id),
                composite FK (exam_question_id, exam_id) -> exam_questions(id, exam_id),
                composite FK (exam_question_id, selected_option_id) -> exam_question_options(exam_question_id, id)).
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
    from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
    from app.models.user import User


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("exams.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default="IN_PROGRESS",
        default="IN_PROGRESS",
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    deadline_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=True,
    )
    score: Mapped[Decimal | None] = mapped_column(
        sa.Numeric(6, 2),
        nullable=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
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
    student: Mapped[User] = relationship("User", foreign_keys=[student_id])
    exam: Mapped[Exam] = relationship("Exam", foreign_keys=[exam_id])
    answers: Mapped[list[AttemptAnswer]] = relationship(
        "AttemptAnswer",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "student_id",
            "exam_id",
            name="uq_attempts_student_id_exam_id",
        ),
        sa.UniqueConstraint(
            "id",
            "exam_id",
            name="uq_attempts_id_exam_id",
        ),
        sa.CheckConstraint(
            "status IN ('IN_PROGRESS', 'SUBMITTED', 'EXPIRED')",
            name="ck_attempts_status",
        ),
        sa.CheckConstraint(
            "deadline_at > started_at",
            name="ck_attempts_deadline_after_started",
        ),
        sa.CheckConstraint(
            "((status = 'IN_PROGRESS' AND finalized_at IS NULL AND score IS NULL) OR "
            "(status IN ('SUBMITTED', 'EXPIRED') AND finalized_at IS NOT NULL AND score IS NOT NULL))",
            name="ck_attempts_status_finalization_paired",
        ),
        sa.Index(
            "ix_attempts_exam_status_started",
            "exam_id",
            "status",
            "started_at",
        ),
        sa.Index(
            "ix_attempts_in_progress_deadline",
            "deadline_at",
            postgresql_where=sa.text("status = 'IN_PROGRESS'"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Attempt id={self.id} student_id={self.student_id} exam_id={self.exam_id} status={self.status}>"


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    exam_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
    )
    exam_question_id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    marked_for_review: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default="false",
        default=False,
    )
    revision: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default="0",
        default=0,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    attempt: Mapped[Attempt] = relationship("Attempt", back_populates="answers")
    question: Mapped[ExamQuestion] = relationship("ExamQuestion", foreign_keys=[exam_question_id])
    selected_option: Mapped[ExamQuestionOption | None] = relationship(
        "ExamQuestionOption",
        foreign_keys=[selected_option_id],
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "attempt_id",
            "exam_question_id",
            name="uq_attempt_answers_attempt_question",
        ),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_attempt_answers_revision_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "exam_id"],
            ["attempts.id", "attempts.exam_id"],
            ondelete="RESTRICT",
            name="fk_attempt_answers_attempt_exam",
        ),
        sa.ForeignKeyConstraint(
            ["exam_question_id", "exam_id"],
            ["exam_questions.id", "exam_questions.exam_id"],
            ondelete="RESTRICT",
            name="fk_attempt_answers_question_exam",
        ),
        sa.ForeignKeyConstraint(
            ["exam_question_id", "selected_option_id"],
            ["exam_question_options.exam_question_id", "exam_question_options.id"],
            ondelete="RESTRICT",
            name="fk_attempt_answers_option",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AttemptAnswer id={self.id} attempt_id={self.attempt_id} question_id={self.exam_question_id} rev={self.revision}>"
