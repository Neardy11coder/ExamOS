"""create_database_lab_and_benchmark_runs_schema

Revision ID: a7b8c9d0e1f2
Revises: f5a2b3c4d5e6
Create Date: 2026-10-23 17:30:00.000000

Creates Database Performance Lab foundation per:
- docs/03_DATABASE_DESIGN.md §§3.10, 5, 7
- docs/01_REQUIREMENTS.md FR-DBLAB-001 to FR-DBLAB-007

1. public.benchmark_runs: audit and telemetry table for benchmark executions.
2. examos_lab schema (if not exists) and paired benchmark datasets:
   - examos_lab.lab_students_no_index
   - examos_lab.lab_students_indexed (with index on student_number and department)
   - examos_lab.lab_enrollments_no_index
   - examos_lab.lab_enrollments_indexed (with index on student_id and course_code)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f5a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. public.benchmark_runs table
    # -------------------------------------------------------------------------
    op.create_table(
        'benchmark_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('requested_by', sa.UUID(), nullable=False),
        sa.Column('scenario_code', sa.String(length=100), nullable=False),
        sa.Column('dataset_size', sa.String(length=20), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('variant', sa.String(length=20), nullable=False),
        sa.Column('postgres_version', sa.String(length=100), nullable=False),
        sa.Column('run_metadata', JSONB(), nullable=False),
        sa.Column('plan_output', JSONB(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("variant IN ('NO_INDEX', 'INDEXED', 'COMPARISON')", name='ck_benchmark_runs_variant'),
        sa.CheckConstraint("status IN ('SUCCEEDED', 'FAILED', 'TIMED_OUT')", name='ck_benchmark_runs_status'),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_benchmark_runs_created_at_desc', 'benchmark_runs', [sa.text('created_at DESC')], unique=False)
    op.create_index(op.f('ix_benchmark_runs_requested_by'), 'benchmark_runs', ['requested_by'], unique=False)


    # -------------------------------------------------------------------------
    # 2. examos_lab schema (idempotent — may already exist from provisioning)
    # -------------------------------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS examos_lab")

    # -------------------------------------------------------------------------
    # 3. Paired lab tables for selective lookup, join, and aggregation
    # -------------------------------------------------------------------------

    # 3a. lab_students_no_index (heap scan / sequential scan target)
    op.create_table(
        'lab_students_no_index',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_number', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('department', sa.String(length=50), nullable=False),
        sa.Column('gpa', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column('enrolled_year', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='examos_lab',
    )

    # 3b. lab_students_indexed (index scan target)
    op.create_table(
        'lab_students_indexed',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_number', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('department', sa.String(length=50), nullable=False),
        sa.Column('gpa', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column('enrolled_year', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='examos_lab',
    )
    # Selective lookup B-tree index on student_number
    op.create_index(
        'ix_lab_students_student_number',
        'lab_students_indexed',
        ['student_number'],
        unique=True,
        schema='examos_lab',
    )
    # Department index for filtering / grouped aggregation
    op.create_index(
        'ix_lab_students_department',
        'lab_students_indexed',
        ['department'],
        unique=False,
        schema='examos_lab',
    )

    # 3c. lab_enrollments_no_index (heap scan / nested loop without index)
    op.create_table(
        'lab_enrollments_no_index',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('course_code', sa.String(length=50), nullable=False),
        sa.Column('semester', sa.String(length=20), nullable=False),
        sa.Column('grade_point', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='examos_lab',
    )

    # 3d. lab_enrollments_indexed (indexed join / lookup target)
    op.create_table(
        'lab_enrollments_indexed',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('course_code', sa.String(length=50), nullable=False),
        sa.Column('semester', sa.String(length=20), nullable=False),
        sa.Column('grade_point', sa.Numeric(precision=3, scale=2), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='examos_lab',
    )
    op.create_index(
        'ix_lab_enrollments_student_id',
        'lab_enrollments_indexed',
        ['student_id'],
        unique=False,
        schema='examos_lab',
    )
    op.create_index(
        'ix_lab_enrollments_course_code',
        'lab_enrollments_indexed',
        ['course_code'],
        unique=False,
        schema='examos_lab',
    )

    # -------------------------------------------------------------------------
    # 4. Grant least-privilege access on lab tables and schema
    # -------------------------------------------------------------------------
    for role in ("examos_app", "examos_test_runner"):
        op.execute(f"GRANT USAGE ON SCHEMA examos_lab TO {role}")
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
            f"examos_lab.lab_students_no_index, "
            f"examos_lab.lab_students_indexed, "
            f"examos_lab.lab_enrollments_no_index, "
            f"examos_lab.lab_enrollments_indexed TO {role}"
        )
    # benchmark_runs is in public schema; default public privileges apply,
    # but grant explicitly for clarity.
    for role in ("examos_app", "examos_test_runner"):
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.benchmark_runs TO {role}"
        )


def downgrade() -> None:
    op.drop_table('lab_enrollments_indexed', schema='examos_lab')
    op.drop_table('lab_enrollments_no_index', schema='examos_lab')
    op.drop_table('lab_students_indexed', schema='examos_lab')
    op.drop_table('lab_students_no_index', schema='examos_lab')
    op.drop_table('benchmark_runs')
