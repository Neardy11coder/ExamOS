"""
SQLAlchemy ORM models for Database Performance Lab (M3-DB-1).

Includes:
1. BenchmarkRun in public schema (operational audit history of benchmark executions).
2. LabStudents, LabEnrollments in isolated examos_lab schema (paired with-index and without-index).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BenchmarkRun(Base):
    """
    Public schema table recording official faculty benchmark execution results.
    Matches docs/03_DATABASE_DESIGN.md §3.10.
    """
    __tablename__ = "benchmark_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scenario_code: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
    )
    dataset_size: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
    )
    seed: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
    )
    variant: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
    )
    postgres_version: Mapped[str] = mapped_column(
        sa.String(100),
        nullable=False,
    )
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    plan_output: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        sa.String(20),
        nullable=False,
    )
    error_summary: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            "variant IN ('NO_INDEX', 'INDEXED', 'COMPARISON')",
            name="ck_benchmark_runs_variant",
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT')",
            name="ck_benchmark_runs_status",
        ),
        sa.Index("ix_benchmark_runs_created_at_desc", created_at.desc()),
    )
