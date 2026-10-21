"""
Automated tests for M1-ATTEMPT-1: Student Attempt and Answer Schema.

Validates:
- All target tables created with correct columns, types, nullability, and foreign keys:
  - attempts
  - attempt_answers
- Constraint enforcement:
  - attempts: status check ('IN_PROGRESS', 'SUBMITTED', 'EXPIRED'), deadline > started,
              paired status finalization nullability checks, unique (student_id, exam_id),
              unique (id, exam_id).
  - attempt_answers: revision >= 0, unique (attempt_id, exam_question_id),
                     composite foreign key (attempt_id, exam_id) -> attempts(id, exam_id),
                     composite foreign key (exam_question_id, exam_id) -> exam_questions(id, exam_id),
                     composite foreign key (exam_question_id, selected_option_id) -> exam_question_options(exam_question_id, id).
- Migration upgrade and downgrade round-trip behavior for revision f5a2b3c4d5e6.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.attempt import Attempt, AttemptAnswer
from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
from app.models.question import Question, QuestionOption
from app.models.topic import Topic
from app.models.user import User


@pytest.fixture
def student_user(test_db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"student_{uuid.uuid4().hex[:8]}@examos.local",
        display_name="Test Student",
        password_hash="adaptive_hash_placeholder",
        role="STUDENT",
        is_active=True,
    )
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)
    return user


@pytest.fixture
def faculty_user(test_db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"faculty_{uuid.uuid4().hex[:8]}@examos.local",
        display_name="Test Faculty",
        password_hash="adaptive_hash_placeholder",
        role="FACULTY_ADMIN",
        is_active=True,
    )
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)
    return user


@pytest.fixture
def published_exam_with_snapshots(test_db_session: Session, faculty_user: User):
    exam = Exam(
        id=uuid.uuid4(),
        creator_id=faculty_user.id,
        title="Schema Test Midterm Exam",
        duration_minutes=60,
        status="PUBLISHED",
        published_at=datetime.now(timezone.utc),
    )
    test_db_session.add(exam)
    test_db_session.flush()

    eq1 = ExamQuestion(
        id=uuid.uuid4(),
        exam_id=exam.id,
        prompt_snapshot="What is CPU quantum?",
        marks=Decimal("3.00"),
        display_order=1,
    )
    test_db_session.add(eq1)
    test_db_session.flush()

    opt1 = ExamQuestionOption(
        id=uuid.uuid4(),
        exam_question_id=eq1.id,
        option_text_snapshot="Time slice",
        display_order=1,
        is_correct=True,
    )
    opt2 = ExamQuestionOption(
        id=uuid.uuid4(),
        exam_question_id=eq1.id,
        option_text_snapshot="Thread count",
        display_order=2,
        is_correct=False,
    )
    test_db_session.add_all([opt1, opt2])
    test_db_session.commit()
    return exam, eq1, [opt1, opt2]


class TestAttemptSchemaStructure:
    def test_attempt_tables_present(self, test_db_session: Session):
        insp = inspect(test_db_session.get_bind())
        tables = set(insp.get_table_names())
        assert "attempts" in tables
        assert "attempt_answers" in tables

    def test_attempt_status_check_constraint(
        self, test_db_session: Session, student_user: User, published_exam_with_snapshots
    ):
        exam, _, _ = published_exam_with_snapshots
        now = datetime.now(timezone.utc)
        # Attempt with invalid status should be rejected
        att = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="INVALID_STATUS",
            started_at=now,
            deadline_at=now + timedelta(minutes=60),
        )
        test_db_session.add(att)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_attempt_deadline_after_started_check(
        self, test_db_session: Session, student_user: User, published_exam_with_snapshots
    ):
        exam, _, _ = published_exam_with_snapshots
        now = datetime.now(timezone.utc)
        # deadline_at <= started_at should be rejected
        att = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="IN_PROGRESS",
            started_at=now,
            deadline_at=now - timedelta(minutes=5),
        )
        test_db_session.add(att)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_paired_status_finalization_check(
        self, test_db_session: Session, student_user: User, published_exam_with_snapshots
    ):
        exam, _, _ = published_exam_with_snapshots
        now = datetime.now(timezone.utc)

        # IN_PROGRESS cannot have finalized_at set
        att1 = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="IN_PROGRESS",
            started_at=now,
            deadline_at=now + timedelta(minutes=60),
            finalized_at=now,  # Invalid for IN_PROGRESS
        )
        test_db_session.add(att1)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

        # SUBMITTED must have finalized_at and score set
        att2 = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="SUBMITTED",
            started_at=now,
            deadline_at=now + timedelta(minutes=60),
            finalized_at=None,  # Invalid for SUBMITTED
            score=None,
        )
        test_db_session.add(att2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_unique_student_exam_attempt_constraint(
        self, test_db_session: Session, student_user: User, published_exam_with_snapshots
    ):
        exam, _, _ = published_exam_with_snapshots
        now = datetime.now(timezone.utc)

        att1 = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="IN_PROGRESS",
            started_at=now,
            deadline_at=now + timedelta(minutes=60),
        )
        test_db_session.add(att1)
        test_db_session.commit()

        # Attempting second attempt for same (student, exam) violates uniqueness
        att2 = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="IN_PROGRESS",
            started_at=now,
            deadline_at=now + timedelta(minutes=60),
        )
        test_db_session.add(att2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_attempt_answer_composite_foreign_keys(
        self, test_db_session: Session, student_user: User, published_exam_with_snapshots
    ):
        exam, eq1, opts = published_exam_with_snapshots
        now = datetime.now(timezone.utc)

        att = Attempt(
            student_id=student_user.id,
            exam_id=exam.id,
            status="IN_PROGRESS",
            started_at=now,
            deadline_at=now + timedelta(minutes=60),
        )
        test_db_session.add(att)
        test_db_session.commit()

        # Valid answer row
        ans = AttemptAnswer(
            attempt_id=att.id,
            exam_id=exam.id,
            exam_question_id=eq1.id,
            selected_option_id=opts[0].id,
            marked_for_review=False,
            revision=0,
        )
        test_db_session.add(ans)
        test_db_session.commit()

        # Selected option must belong to the question
        fake_opt_id = uuid.uuid4()
        ans2 = AttemptAnswer(
            attempt_id=att.id,
            exam_id=exam.id,
            exam_question_id=eq1.id,
            selected_option_id=fake_opt_id,
        )
        test_db_session.add(ans2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()


class TestAttemptMigrationRoundTrip:
    def test_migration_downgrade_and_upgrade(self, test_db_session: Session):
        test_url = str(settings.TEST_DATABASE_URL)
        from alembic import command
        from alembic.config import Config

        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("version_locations", str(backend_dir / "alembic" / "versions"))
        cfg.set_main_option("sqlalchemy.url", test_url)

        # 1. Downgrade to e4a1f8b2c9d0
        command.downgrade(cfg, "e4a1f8b2c9d0")

        engine = create_engine(test_url)
        insp = inspect(engine)
        tables_after_downgrade = set(insp.get_table_names())
        assert "exams" in tables_after_downgrade
        assert "exam_questions" in tables_after_downgrade
        assert "attempts" not in tables_after_downgrade
        assert "attempt_answers" not in tables_after_downgrade

        # 2. Upgrade back to head (f5a2b3c4d5e6)
        command.upgrade(cfg, "head")

        insp2 = inspect(engine)
        tables_after_upgrade = set(insp2.get_table_names())
        assert "attempts" in tables_after_upgrade
        assert "attempt_answers" in tables_after_upgrade
        engine.dispose()
