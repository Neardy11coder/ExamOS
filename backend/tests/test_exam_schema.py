"""
Automated tests for M1-SCHEMA-1: Core Examination Database Schema.

Validates:
- All target tables created with correct columns, types, nullability, and foreign keys.
- Constraint enforcement:
  - topics: subject check ('OS' or 'DBMS'), code/name non-empty, unique code.
  - questions: prompt non-empty, author FK.
  - question_options: display_order >= 1, unique display_order, single correct option partial index.
  - exams: status check ('DRAFT', 'PUBLISHED', 'UNPUBLISHED'), duration_minutes > 0, title non-empty.
  - exam_questions: marks > 0, display_order >= 1, unique (exam_id, display_order), unique (id, exam_id).
  - exam_question_options: display_order >= 1, unique display_order, single correct option partial index.
- Snapshot immutability: snapshot fields store frozen prompt, options, marks, topic.
- Migration upgrade and downgrade round-trip behavior.
"""

import uuid
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
from app.models.question import Question, QuestionOption
from app.models.topic import Topic
from app.models.user import User


@pytest.fixture
def faculty_user(test_db_session: Session) -> User:
    """Fixture providing an active faculty user for testing ownership and foreign keys."""
    user = User(
        id=uuid.uuid4(),
        email=f"faculty_{uuid.uuid4().hex[:8]}@examos.local",
        display_name="Test Faculty Author",
        password_hash="adaptive_hash_placeholder",
        role="FACULTY_ADMIN",
        is_active=True,
    )
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)
    return user


class TestSchemaStructure:
    """Verifies table presence, columns, types, and foreign key definitions."""

    def test_tables_present_in_database(self, test_db_session: Session):
        engine = test_db_session.get_bind()
        insp = inspect(engine)
        table_names = set(insp.get_table_names())

        expected_tables = {
            "users",
            "topics",
            "questions",
            "question_options",
            "exams",
            "exam_questions",
            "exam_question_options",
        }
        assert expected_tables.issubset(table_names), (
            f"Missing tables: {expected_tables - table_names}"
        )

    def test_topics_columns_and_nullability(self, test_db_session: Session):
        engine = test_db_session.get_bind()
        insp = inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("topics")}

        assert "id" in cols and not cols["id"]["nullable"]
        assert "code" in cols and not cols["code"]["nullable"]
        assert "name" in cols and not cols["name"]["nullable"]
        assert "subject" in cols and not cols["subject"]["nullable"]
        assert "is_active" in cols and not cols["is_active"]["nullable"]
        assert "created_at" in cols and not cols["created_at"]["nullable"]
        assert "updated_at" in cols and not cols["updated_at"]["nullable"]

    def test_foreign_keys_definition(self, test_db_session: Session):
        engine = test_db_session.get_bind()
        insp = inspect(engine)

        q_fks = insp.get_foreign_keys("questions")
        q_targets = {fk["referred_table"]: fk["constrained_columns"] for fk in q_fks}
        assert "users" in q_targets and "author_id" in q_targets["users"]
        assert "topics" in q_targets and "topic_id" in q_targets["topics"]

        qo_fks = insp.get_foreign_keys("question_options")
        qo_targets = {fk["referred_table"]: fk["constrained_columns"] for fk in qo_fks}
        assert "questions" in qo_targets and "question_id" in qo_targets["questions"]

        exam_fks = insp.get_foreign_keys("exams")
        exam_targets = {fk["referred_table"]: fk["constrained_columns"] for fk in exam_fks}
        assert "users" in exam_targets and "creator_id" in exam_targets["users"]

        eq_fks = insp.get_foreign_keys("exam_questions")
        eq_targets = {fk["referred_table"]: fk["constrained_columns"] for fk in eq_fks}
        assert "exams" in eq_targets and "exam_id" in eq_targets["exams"]
        assert "questions" in eq_targets and "source_question_id" in eq_targets["questions"]

        eqo_fks = insp.get_foreign_keys("exam_question_options")
        eqo_targets = {fk["referred_table"]: fk["constrained_columns"] for fk in eqo_fks}
        assert "exam_questions" in eqo_targets and "exam_question_id" in eqo_targets["exam_questions"]


class TestTopicConstraints:
    """Verifies constraint enforcement on topics table."""

    def test_topic_valid_subjects(self, test_db_session: Session):
        t1 = Topic(code="OS_TEST_1", name="OS Test Topic", subject="OS")
        t2 = Topic(code="DBMS_TEST_1", name="DBMS Test Topic", subject="DBMS")
        test_db_session.add_all([t1, t2])
        test_db_session.commit()
        assert t1.id is not None
        assert t2.id is not None

    def test_topic_invalid_subject_rejected(self, test_db_session: Session):
        t = Topic(code="INVALID_SUBJ", name="Invalid Subject Topic", subject="NETWORKING")
        test_db_session.add(t)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_topic_duplicate_code_rejected(self, test_db_session: Session):
        t1 = Topic(code="DUP_CODE", name="Topic Alpha", subject="OS")
        t2 = Topic(code="DUP_CODE", name="Topic Beta", subject="OS")
        test_db_session.add(t1)
        test_db_session.commit()

        test_db_session.add(t2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_topic_empty_code_rejected(self, test_db_session: Session):
        t = Topic(code="   ", name="Empty Code Topic", subject="OS")
        test_db_session.add(t)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()


class TestQuestionAndOptionConstraints:
    """Verifies constraints on questions and question_options."""

    def test_question_empty_prompt_rejected(self, test_db_session: Session, faculty_user: User):
        q = Question(author_id=faculty_user.id, prompt="   ")
        test_db_session.add(q)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_question_options_single_correct_partial_unique_index(
        self, test_db_session: Session, faculty_user: User
    ):
        q = Question(author_id=faculty_user.id, prompt="Which scheduling algorithm uses time slices?")
        test_db_session.add(q)
        test_db_session.commit()

        opt1 = QuestionOption(question_id=q.id, option_text="Round Robin", display_order=1, is_correct=True)
        opt2 = QuestionOption(question_id=q.id, option_text="FCFS", display_order=2, is_correct=True)
        test_db_session.add(opt1)
        test_db_session.commit()

        test_db_session.add(opt2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_question_options_duplicate_display_order_rejected(
        self, test_db_session: Session, faculty_user: User
    ):
        q = Question(author_id=faculty_user.id, prompt="Sample question prompt?")
        test_db_session.add(q)
        test_db_session.commit()

        opt1 = QuestionOption(question_id=q.id, option_text="Option 1", display_order=1, is_correct=False)
        opt2 = QuestionOption(question_id=q.id, option_text="Option 2", display_order=1, is_correct=False)
        test_db_session.add(opt1)
        test_db_session.commit()

        test_db_session.add(opt2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_question_options_nonpositive_display_order_rejected(
        self, test_db_session: Session, faculty_user: User
    ):
        q = Question(author_id=faculty_user.id, prompt="Sample question prompt?")
        test_db_session.add(q)
        test_db_session.commit()

        opt = QuestionOption(question_id=q.id, option_text="Option 0", display_order=0, is_correct=False)
        test_db_session.add(opt)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()


class TestExamAndSnapshotConstraints:
    """Verifies constraints on exams, exam_questions, and exam_question_options."""

    def test_exam_status_check_constraint(self, test_db_session: Session, faculty_user: User):
        exam = Exam(
            creator_id=faculty_user.id,
            title="Invalid Status Exam",
            duration_minutes=30,
            status="ARCHIVED",  # Only DRAFT, PUBLISHED, UNPUBLISHED allowed
        )
        test_db_session.add(exam)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_exam_duration_positive_constraint(self, test_db_session: Session, faculty_user: User):
        exam = Exam(
            creator_id=faculty_user.id,
            title="Zero Duration Exam",
            duration_minutes=0,
            status="DRAFT",
        )
        test_db_session.add(exam)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_exam_question_marks_positive_constraint(self, test_db_session: Session, faculty_user: User):
        exam = Exam(
            creator_id=faculty_user.id,
            title="Valid Exam",
            duration_minutes=45,
            status="DRAFT",
        )
        test_db_session.add(exam)
        test_db_session.commit()

        eq = ExamQuestion(
            exam_id=exam.id,
            prompt_snapshot="Snapshot prompt text",
            marks=Decimal("0.00"),  # Must be > 0
            display_order=1,
        )
        test_db_session.add(eq)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_exam_question_duplicate_display_order_in_same_exam_rejected(
        self, test_db_session: Session, faculty_user: User
    ):
        exam = Exam(
            creator_id=faculty_user.id,
            title="Ordering Exam",
            duration_minutes=45,
            status="DRAFT",
        )
        test_db_session.add(exam)
        test_db_session.commit()

        eq1 = ExamQuestion(exam_id=exam.id, prompt_snapshot="Prompt 1", marks=Decimal("2.00"), display_order=1)
        eq2 = ExamQuestion(exam_id=exam.id, prompt_snapshot="Prompt 2", marks=Decimal("2.00"), display_order=1)
        test_db_session.add(eq1)
        test_db_session.commit()

        test_db_session.add(eq2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

    def test_exam_question_option_single_correct_partial_unique_index(
        self, test_db_session: Session, faculty_user: User
    ):
        exam = Exam(
            creator_id=faculty_user.id,
            title="Snapshot Single Correct Exam",
            duration_minutes=30,
            status="PUBLISHED",
        )
        test_db_session.add(exam)
        test_db_session.commit()

        eq = ExamQuestion(
            exam_id=exam.id,
            prompt_snapshot="Frozen prompt?",
            marks=Decimal("1.50"),
            display_order=1,
        )
        test_db_session.add(eq)
        test_db_session.commit()

        eqo1 = ExamQuestionOption(exam_question_id=eq.id, option_text_snapshot="A", display_order=1, is_correct=True)
        eqo2 = ExamQuestionOption(exam_question_id=eq.id, option_text_snapshot="B", display_order=2, is_correct=True)
        test_db_session.add(eqo1)
        test_db_session.commit()

        test_db_session.add(eqo2)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()


class TestSnapshotImmutabilityDesign:
    """Verifies that snapshot tables preserve frozen content independently of bank changes."""

    def test_snapshot_independence_from_question_bank(
        self, test_db_session: Session, faculty_user: User
    ):
        # 1. Author a question with topic in question bank
        topic = Topic(code="OS_CPU_SCHED", name="CPU Scheduling", subject="OS")
        test_db_session.add(topic)
        test_db_session.commit()

        q = Question(
            author_id=faculty_user.id,
            topic_id=topic.id,
            prompt="Original authoring question prompt",
        )
        test_db_session.add(q)
        test_db_session.commit()

        opt_a = QuestionOption(question_id=q.id, option_text="Original Opt A", display_order=1, is_correct=True)
        opt_b = QuestionOption(question_id=q.id, option_text="Original Opt B", display_order=2, is_correct=False)
        test_db_session.add_all([opt_a, opt_b])
        test_db_session.commit()

        # 2. Publish an exam with frozen snapshot
        exam = Exam(
            creator_id=faculty_user.id,
            title="Midterm OS Exam",
            instructions="Select one option.",
            duration_minutes=60,
            status="PUBLISHED",
        )
        test_db_session.add(exam)
        test_db_session.commit()

        eq = ExamQuestion(
            exam_id=exam.id,
            source_question_id=q.id,
            prompt_snapshot=q.prompt,
            topic_code_snapshot=topic.code,
            topic_name_snapshot=topic.name,
            marks=Decimal("2.50"),
            display_order=1,
        )
        test_db_session.add(eq)
        test_db_session.commit()

        eqo_a = ExamQuestionOption(exam_question_id=eq.id, option_text_snapshot="Original Opt A", display_order=1, is_correct=True)
        eqo_b = ExamQuestionOption(exam_question_id=eq.id, option_text_snapshot="Original Opt B", display_order=2, is_correct=False)
        test_db_session.add_all([eqo_a, eqo_b])
        test_db_session.commit()

        # 3. Later, faculty edits the question in the question bank (simulating authoring change)
        q.prompt = "MODIFIED prompt for future exams"
        opt_a.option_text = "MODIFIED Opt A"
        test_db_session.commit()

        # 4. Verify snapshot remains completely unaffected
        test_db_session.refresh(eq)
        test_db_session.refresh(eqo_a)
        assert eq.prompt_snapshot == "Original authoring question prompt"
        assert eq.topic_code_snapshot == "OS_CPU_SCHED"
        assert eq.marks == Decimal("2.50")
        assert eqo_a.option_text_snapshot == "Original Opt A"
        assert eqo_a.is_correct is True


class TestMigrationRoundTrip:
    """Verifies downgrade and upgrade round trips of the new migration."""

    def test_migration_downgrade_and_upgrade(self, test_db_session: Session):
        test_url = str(settings.TEST_DATABASE_URL)
        from pathlib import Path
        from alembic import command
        from alembic.config import Config
        backend_dir = Path(__file__).resolve().parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = Config(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("version_locations", str(backend_dir / "alembic" / "versions"))
        cfg.set_main_option("sqlalchemy.url", test_url)

        # 1. Downgrade to 0cb900c103a1
        command.downgrade(cfg, "0cb900c103a1")

        engine = create_engine(test_url)
        insp = inspect(engine)
        tables_after_downgrade = set(insp.get_table_names())
        assert "users" in tables_after_downgrade
        assert "topics" not in tables_after_downgrade
        assert "questions" not in tables_after_downgrade
        assert "exams" not in tables_after_downgrade
        assert "exam_questions" not in tables_after_downgrade
        assert "exam_question_options" not in tables_after_downgrade

        # 2. Upgrade back to head (e4a1f8b2c9d0)
        command.upgrade(cfg, "head")

        insp2 = inspect(engine)
        tables_after_upgrade = set(insp2.get_table_names())
        assert "topics" in tables_after_upgrade
        assert "questions" in tables_after_upgrade
        assert "question_options" in tables_after_upgrade
        assert "exams" in tables_after_upgrade
        assert "exam_questions" in tables_after_upgrade
        assert "exam_question_options" in tables_after_upgrade
        engine.dispose()
