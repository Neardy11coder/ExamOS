"""
SQLAlchemy ORM model for the `users` table.

FR-AUTH-004: passwords stored only as salted adaptive hashes.
FR-AUTH-007: exactly two roles, STUDENT and FACULTY_ADMIN.
DB design §3.1: UUID PK, email UNIQUE lower-case, role check constraint,
               is_active flag, timestamptz audit columns.
Appendix A OD-01: public registration inserts STUDENT only; FACULTY_ADMIN
                   via trusted seed/bootstrap command only.
"""

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        sa.String(254),
        nullable=False,
        unique=True,
        index=True,
    )
    display_name: Mapped[str] = mapped_column(
        sa.String(200),
        nullable=False,
    )
    password_hash: Mapped[str] = mapped_column(
        sa.String(256),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
        server_default="STUDENT",
    )
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
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

    # Table-level constraints kept in the model to mirror DB schema doc §3.1
    __table_args__ = (
        sa.CheckConstraint(
            "role IN ('STUDENT', 'FACULTY_ADMIN')",
            name="ck_users_role",
        ),
        sa.CheckConstraint(
            "char_length(trim(email)) > 0",
            name="ck_users_email_nonempty",
        ),
        sa.CheckConstraint(
            "char_length(trim(display_name)) > 0",
            name="ck_users_display_name_nonempty",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r} role={self.role}>"
