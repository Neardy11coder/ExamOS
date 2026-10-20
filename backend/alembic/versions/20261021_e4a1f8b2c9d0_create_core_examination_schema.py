"""create_core_examination_schema

Revision ID: e4a1f8b2c9d0
Revises: 0cb900c103a1
Create Date: 2026-10-21 00:08:00.000000

Creates core examination and question authoring & snapshot schema per
docs/03_DATABASE_DESIGN.md §§3.2-3.7:
- topics
- questions
- question_options
- exams
- exam_questions
- exam_question_options
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a1f8b2c9d0'
down_revision: Union[str, None] = '0cb900c103a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. topics
    op.create_table(
        'topics',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('subject', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("subject IN ('OS', 'DBMS')", name='ck_topics_subject'),
        sa.CheckConstraint('char_length(trim(code)) > 0', name='ck_topics_code_nonempty'),
        sa.CheckConstraint('char_length(trim(name)) > 0', name='ck_topics_name_nonempty'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_topics_code'),
        sa.UniqueConstraint('name', name='uq_topics_name'),
    )
    op.create_index(op.f('ix_topics_code'), 'topics', ['code'], unique=False)

    # 2. questions (authoring bank)
    op.create_table(
        'questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('author_id', sa.UUID(), nullable=False),
        sa.Column('topic_id', sa.UUID(), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('archived_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('char_length(trim(prompt)) > 0', name='ck_questions_prompt_nonempty'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_questions_author_id'), 'questions', ['author_id'], unique=False)
    op.create_index('ix_questions_topic_archived', 'questions', ['topic_id', 'archived_at'], unique=False)

    # 3. question_options (authoring options)
    op.create_table(
        'question_options',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('question_id', sa.UUID(), nullable=False),
        sa.Column('option_text', sa.Text(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.CheckConstraint('display_order >= 1', name='ck_question_options_display_order_positive'),
        sa.CheckConstraint('char_length(trim(option_text)) > 0', name='ck_question_options_text_nonempty'),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'display_order', name='uq_question_options_question_display_order'),
    )
    op.create_index(op.f('ix_question_options_question_id'), 'question_options', ['question_id'], unique=False)
    op.create_index(
        'uq_question_options_single_correct',
        'question_options',
        ['question_id'],
        unique=True,
        postgresql_where=sa.text('is_correct IS TRUE'),
    )

    # 4. exams
    op.create_table(
        'exams',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('creator_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('instructions', sa.Text(), server_default='', nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='DRAFT', nullable=False),
        sa.Column('published_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'UNPUBLISHED')", name='ck_exams_status'),
        sa.CheckConstraint('duration_minutes > 0', name='ck_exams_duration_minutes_positive'),
        sa.CheckConstraint('char_length(trim(title)) > 0', name='ck_exams_title_nonempty'),
        sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_exams_creator_id'), 'exams', ['creator_id'], unique=False)
    op.create_index('ix_exams_status_created_at', 'exams', ['status', 'created_at'], unique=False)

    # 5. exam_questions (frozen published snapshot)
    op.create_table(
        'exam_questions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('exam_id', sa.UUID(), nullable=False),
        sa.Column('source_question_id', sa.UUID(), nullable=True),
        sa.Column('prompt_snapshot', sa.Text(), nullable=False),
        sa.Column('topic_code_snapshot', sa.String(length=50), nullable=True),
        sa.Column('topic_name_snapshot', sa.String(length=150), nullable=True),
        sa.Column('marks', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.CheckConstraint('marks > 0', name='ck_exam_questions_marks_positive'),
        sa.CheckConstraint('display_order >= 1', name='ck_exam_questions_display_order_positive'),
        sa.CheckConstraint('char_length(trim(prompt_snapshot)) > 0', name='ck_exam_questions_prompt_snapshot_nonempty'),
        sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['source_question_id'], ['questions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('exam_id', 'display_order', name='uq_exam_questions_exam_display_order'),
        sa.UniqueConstraint('id', 'exam_id', name='uq_exam_questions_id_exam_id'),
    )
    op.create_index(op.f('ix_exam_questions_exam_id'), 'exam_questions', ['exam_id'], unique=False)
    op.create_index(op.f('ix_exam_questions_source_question_id'), 'exam_questions', ['source_question_id'], unique=False)

    # 6. exam_question_options (frozen options)
    op.create_table(
        'exam_question_options',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('exam_question_id', sa.UUID(), nullable=False),
        sa.Column('option_text_snapshot', sa.Text(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False),
        sa.Column('is_correct', sa.Boolean(), nullable=False),
        sa.CheckConstraint('display_order >= 1', name='ck_exam_question_options_display_order_positive'),
        sa.CheckConstraint('char_length(trim(option_text_snapshot)) > 0', name='ck_exam_question_options_text_snapshot_nonempty'),
        sa.ForeignKeyConstraint(['exam_question_id'], ['exam_questions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('exam_question_id', 'display_order', name='uq_exam_question_options_question_display_order'),
        sa.UniqueConstraint('exam_question_id', 'id', name='uq_exam_question_options_question_id'),
    )
    op.create_index(op.f('ix_exam_question_options_exam_question_id'), 'exam_question_options', ['exam_question_id'], unique=False)
    op.create_index(
        'uq_exam_question_options_single_correct',
        'exam_question_options',
        ['exam_question_id'],
        unique=True,
        postgresql_where=sa.text('is_correct IS TRUE'),
    )


def downgrade() -> None:
    # Drop in exact reverse dependency order
    op.drop_index('uq_exam_question_options_single_correct', table_name='exam_question_options')
    op.drop_index(op.f('ix_exam_question_options_exam_question_id'), table_name='exam_question_options')
    op.drop_table('exam_question_options')

    op.drop_index(op.f('ix_exam_questions_source_question_id'), table_name='exam_questions')
    op.drop_index(op.f('ix_exam_questions_exam_id'), table_name='exam_questions')
    op.drop_table('exam_questions')

    op.drop_index('ix_exams_status_created_at', table_name='exams')
    op.drop_index(op.f('ix_exams_creator_id'), table_name='exams')
    op.drop_table('exams')

    op.drop_index('uq_question_options_single_correct', table_name='question_options')
    op.drop_index(op.f('ix_question_options_question_id'), table_name='question_options')
    op.drop_table('question_options')

    op.drop_index('ix_questions_topic_archived', table_name='questions')
    op.drop_index(op.f('ix_questions_author_id'), table_name='questions')
    op.drop_table('questions')

    op.drop_index(op.f('ix_topics_code'), table_name='topics')
    op.drop_table('topics')
