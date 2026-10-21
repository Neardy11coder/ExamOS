"""create_attempt_and_answer_schema

Revision ID: f5a2b3c4d5e6
Revises: e4a1f8b2c9d0
Create Date: 2026-10-21 16:00:00.000000

Creates student attempt lifecycle and answer persistence schema per
docs/03_DATABASE_DESIGN.md §§3.8-3.9 and docs/01_REQUIREMENTS.md Appendix A:
- attempts
- attempt_answers
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5a2b3c4d5e6'
down_revision: Union[str, None] = 'e4a1f8b2c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. attempts
    op.create_table(
        'attempts',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('student_id', sa.UUID(), nullable=False),
        sa.Column('exam_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='IN_PROGRESS', nullable=False),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deadline_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('finalized_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('score', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('last_seen_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('IN_PROGRESS', 'SUBMITTED', 'EXPIRED')", name='ck_attempts_status'),
        sa.CheckConstraint('deadline_at > started_at', name='ck_attempts_deadline_after_started'),
        sa.CheckConstraint(
            "((status = 'IN_PROGRESS' AND finalized_at IS NULL AND score IS NULL) OR "
            "(status IN ('SUBMITTED', 'EXPIRED') AND finalized_at IS NOT NULL AND score IS NOT NULL))",
            name='ck_attempts_status_finalization_paired',
        ),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'exam_id', name='uq_attempts_student_id_exam_id'),
        sa.UniqueConstraint('id', 'exam_id', name='uq_attempts_id_exam_id'),
    )
    op.create_index(op.f('ix_attempts_student_id'), 'attempts', ['student_id'], unique=False)
    op.create_index(op.f('ix_attempts_exam_id'), 'attempts', ['exam_id'], unique=False)
    op.create_index('ix_attempts_exam_status_started', 'attempts', ['exam_id', 'status', 'started_at'], unique=False)
    op.create_index(
        'ix_attempts_in_progress_deadline',
        'attempts',
        ['deadline_at'],
        unique=False,
        postgresql_where=sa.text("status = 'IN_PROGRESS'"),
    )

    # 2. attempt_answers
    op.create_table(
        'attempt_answers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('attempt_id', sa.UUID(), nullable=False),
        sa.Column('exam_id', sa.UUID(), nullable=False),
        sa.Column('exam_question_id', sa.UUID(), nullable=False),
        sa.Column('selected_option_id', sa.UUID(), nullable=True),
        sa.Column('marked_for_review', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('revision', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('revision >= 0', name='ck_attempt_answers_revision_nonnegative'),
        sa.ForeignKeyConstraint(
            ['attempt_id', 'exam_id'],
            ['attempts.id', 'attempts.exam_id'],
            ondelete='RESTRICT',
            name='fk_attempt_answers_attempt_exam',
        ),
        sa.ForeignKeyConstraint(
            ['exam_question_id', 'exam_id'],
            ['exam_questions.id', 'exam_questions.exam_id'],
            ondelete='RESTRICT',
            name='fk_attempt_answers_question_exam',
        ),
        sa.ForeignKeyConstraint(
            ['exam_question_id', 'selected_option_id'],
            ['exam_question_options.exam_question_id', 'exam_question_options.id'],
            ondelete='RESTRICT',
            name='fk_attempt_answers_option',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('attempt_id', 'exam_question_id', name='uq_attempt_answers_attempt_question'),
    )
    op.create_index(op.f('ix_attempt_answers_attempt_id'), 'attempt_answers', ['attempt_id'], unique=False)
    op.create_index(op.f('ix_attempt_answers_exam_question_id'), 'attempt_answers', ['exam_question_id'], unique=False)
    op.create_index(op.f('ix_attempt_answers_selected_option_id'), 'attempt_answers', ['selected_option_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_attempt_answers_selected_option_id'), table_name='attempt_answers')
    op.drop_index(op.f('ix_attempt_answers_exam_question_id'), table_name='attempt_answers')
    op.drop_index(op.f('ix_attempt_answers_attempt_id'), table_name='attempt_answers')
    op.drop_table('attempt_answers')

    op.drop_index('ix_attempts_in_progress_deadline', table_name='attempts')
    op.drop_index('ix_attempts_exam_status_started', table_name='attempts')
    op.drop_index(op.f('ix_attempts_exam_id'), table_name='attempts')
    op.drop_index(op.f('ix_attempts_student_id'), table_name='attempts')
    op.drop_table('attempts')
