"""
SQLAlchemy ORM model for the `topics` table.

DB design §3.2: UUID PK, code UNIQUE, name UNIQUE, subject check ('OS', 'DBMS'),
                is_active boolean, timestamptz audit columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.question import Question


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    code: Mapped[str] = mapped_column(
        sa.String(50),
        nullable=False,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(
        sa.String(150),
        nullable=False,
        unique=True,
    )
    subject: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        default=True,
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
    questions: Mapped[list[Question]] = relationship(
        "Question",
        back_populates="topic",
    )

    __table_args__ = (
        sa.CheckConstraint(
            "subject IN ('OS', 'DBMS')",
            name="ck_topics_subject",
        ),
        sa.CheckConstraint(
            "char_length(trim(code)) > 0",
            name="ck_topics_code_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(trim(name)) > 0",
            name="ck_topics_name_nonempty",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Topic id={self.id} code={self.code!r} subject={self.subject!r}>"
