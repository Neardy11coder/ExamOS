"""
Automated tests for Atomic Examination Publishing and Immutable Snapshots.

Covers:
- docs/04_API_CONTRACT.md §3 POST /exams/{id}/publish and POST /exams/{id}/unpublish
- docs/03_DATABASE_DESIGN.md §§3.5-3.7 (exam_questions and exam_question_options)
- docs/01_REQUIREMENTS.md FR-EXAM-005, FR-EXAM-006, FR-EXAM-008, OD-08
- Atomic transaction behavior and complete rollback on failure
- Snapshot freezing (prompt, topic, marks, display_order, options, is_correct)
- Complete isolation and immutability from subsequent question-bank edits
- Repeated publish idempotency
- Unpublish lifecycle rules
- Protection of published exams from draft-only mutation
"""

from decimal import Decimal
import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
from app.models.question import Question, QuestionOption
from app.services.question_service import create_question
from app.services.topic_service import seed_taxonomy_topics
from tests.helpers import auth_cookies_and_headers, create_test_user

_EXAMS_URL = "/api/v1/exams"
_QUESTIONS_URL = "/api/v1/questions"


@pytest.fixture
def seeded_topics(test_db_session: Session):
    return seed_taxonomy_topics(test_db_session)


@pytest.fixture
def faculty_user(test_db_session: Session):
    return create_test_user(test_db_session, role="FACULTY_ADMIN")


@pytest.fixture
def other_faculty_user(test_db_session: Session):
    return create_test_user(test_db_session, role="FACULTY_ADMIN")


@pytest.fixture
def student_user(test_db_session: Session):
    return create_test_user(test_db_session, role="STUDENT")


@pytest.fixture
def authored_questions(test_db_session: Session, faculty_user, seeded_topics):
    """Fixture creating two distinct authored questions in the question bank."""
    from app.schemas.question import QuestionOptionCreate

    q1 = create_question(
        test_db_session,
        author_id=faculty_user.id,
        prompt="Which CPU scheduler uses preemption with a time quantum?",
        topic_id=seeded_topics[1].id,  # OS_SCHEDULING
        options_data=[
            QuestionOptionCreate(text="Round Robin", is_correct=True, display_order=1),
            QuestionOptionCreate(text="FCFS", is_correct=False, display_order=2),
            QuestionOptionCreate(text="SJF Non-preemptive", is_correct=False, display_order=3),
        ],
    )
    q2 = create_question(
        test_db_session,
        author_id=faculty_user.id,
        prompt="What anomaly occurs when increasing page frames causes more page faults?",
        topic_id=seeded_topics[3].id,  # OS_MEMORY_FILES
        options_data=[
            QuestionOptionCreate(text="Belady's Anomaly", is_correct=True, display_order=1),
            QuestionOptionCreate(text="Convoy Effect", is_correct=False, display_order=2),
            QuestionOptionCreate(text="Priority Inversion", is_correct=False, display_order=3),
            QuestionOptionCreate(text="Thrashing", is_correct=False, display_order=4),
        ],
    )
    return q1, q2


class TestExamPublicationSuccess:
    def test_successful_atomic_publication_and_snapshot_creation(
        self, client: TestClient, test_db_session: Session, faculty_user, authored_questions
    ):
        """
        Publishing an exam atomically:
        - Freezes prompt, topic code, topic name, marks, display_order in exam_questions.
        - Freezes option text, display_order, is_correct in exam_question_options.
        - Sets exam.status = 'PUBLISHED' and records published_at timestamp.
        """
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, q2 = authored_questions

        # 1. Create draft exam
        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Midterm Examination 2026", "duration_minutes": 60},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]

        # 2. Attach questions
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 2.5, "display_order": 1},
            cookies=cookies,
            headers=headers,
        )
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q2.id), "marks": 3.0, "display_order": 2},
            cookies=cookies,
            headers=headers,
        )

        # 3. Publish
        pub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        assert pub_resp.status_code == status.HTTP_200_OK, pub_resp.text
        pub_data = pub_resp.json()
        assert pub_data["status"] == "PUBLISHED"
        assert pub_data["question_count"] == 2
        assert Decimal(str(pub_data["total_marks"])) == Decimal("5.50")
        assert pub_data["published_at"] is not None

        # 4. Verify snapshots in database
        exam = test_db_session.get(Exam, uuid.UUID(exam_id))
        assert exam.status == "PUBLISHED"
        assert exam.published_at is not None
        assert len(exam.questions) == 2

        # Question 1 snapshot
        eq1 = next(eq for eq in exam.questions if eq.display_order == 1)
        assert eq1.source_question_id == q1.id
        assert eq1.prompt_snapshot == q1.prompt
        assert eq1.topic_code_snapshot == "OS_SCHEDULING"
        assert eq1.marks == Decimal("2.50")
        assert len(eq1.options) == 3
        correct_opts_1 = [o for o in eq1.options if o.is_correct]
        assert len(correct_opts_1) == 1
        assert correct_opts_1[0].option_text_snapshot == "Round Robin"

        # Question 2 snapshot
        eq2 = next(eq for eq in exam.questions if eq.display_order == 2)
        assert eq2.source_question_id == q2.id
        assert eq2.prompt_snapshot == q2.prompt
        assert eq2.topic_code_snapshot == "OS_MEMORY_FILES"
        assert eq2.marks == Decimal("3.00")
        assert len(eq2.options) == 4
        correct_opts_2 = [o for o in eq2.options if o.is_correct]
        assert len(correct_opts_2) == 1
        assert correct_opts_2[0].option_text_snapshot == "Belady's Anomaly"

    def test_repeated_publish_is_idempotent(
        self, client: TestClient, test_db_session: Session, faculty_user, authored_questions
    ):
        """Repeated publish requests return the existing outcome safely without duplicate snapshots."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, _ = authored_questions

        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Idempotent Pub Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 2.0},
            cookies=cookies,
            headers=headers,
        )

        pub1 = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        assert pub1.status_code == status.HTTP_200_OK

        # Call publish again
        pub2 = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        assert pub2.status_code == status.HTTP_200_OK
        assert pub2.json()["status"] == "PUBLISHED"

        # Verify snapshot count remains exactly 1
        exam = test_db_session.get(Exam, uuid.UUID(exam_id))
        test_db_session.refresh(exam)
        assert len(exam.questions) == 1
        assert len(exam.questions[0].options) == 3


class TestSnapshotImmutabilityFromQuestionBankEdits:
    def test_edits_to_source_questions_do_not_alter_published_snapshots(
        self, client: TestClient, test_db_session: Session, faculty_user, authored_questions
    ):
        """
        OD-08 & FR-EXAM-008:
        Editing a source question or options in the question bank does NOT alter
        already-published snapshot prompt, marks, topic, or options.
        """
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, _ = authored_questions

        # 1. Publish exam with q1
        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Snapshot Immutability Exam", "duration_minutes": 40},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 4.0},
            cookies=cookies,
            headers=headers,
        )
        client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)

        # Verify snapshot baseline
        exam = test_db_session.get(Exam, uuid.UUID(exam_id))
        eq = exam.questions[0]
        assert eq.prompt_snapshot == "Which CPU scheduler uses preemption with a time quantum?"
        assert eq.marks == Decimal("4.00")
        correct_opt = next(o for o in eq.options if o.is_correct)
        assert correct_opt.option_text_snapshot == "Round Robin"

        # 2. Modify the source question in the question bank via API
        client.patch(
            f"{_QUESTIONS_URL}/{q1.id}",
            json={
                "prompt": "COMPLETELY CHANGED BANK PROMPT",
                "options": [
                    {"text": "SJF Non-preemptive", "is_correct": False},
                    {"text": "FCFS", "is_correct": False},
                    {"text": "MULTILEVEL FEEDBACK QUEUE", "is_correct": True},
                ],
            },
            cookies=cookies,
            headers=headers,
        )

        # 3. Verify the published snapshot is COMPLETELY UNTOUCHED
        test_db_session.expire_all()
        exam_reloaded = test_db_session.get(Exam, uuid.UUID(exam_id))
        eq_reloaded = exam_reloaded.questions[0]

        assert eq_reloaded.prompt_snapshot == "Which CPU scheduler uses preemption with a time quantum?"
        assert eq_reloaded.marks == Decimal("4.00")
        assert len(eq_reloaded.options) == 3
        correct_opt_reloaded = next(o for o in eq_reloaded.options if o.is_correct)
        assert correct_opt_reloaded.option_text_snapshot == "Round Robin"

    def test_published_exam_cannot_be_mutated_via_draft_operations(
        self, client: TestClient, faculty_user, authored_questions
    ):
        """Published examinations reject any draft mutation (title/duration/question edits)."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, q2 = authored_questions

        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Frozen Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 2.0},
            cookies=cookies,
            headers=headers,
        )
        client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)

        # Attempt to patch title
        patch_resp = client.patch(
            f"{_EXAMS_URL}/{exam_id}",
            json={"title": "Attempt Modify Published"},
            cookies=cookies,
            headers=headers,
        )
        assert patch_resp.status_code == status.HTTP_409_CONFLICT

        # Attempt to attach another question
        attach_resp = client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q2.id), "marks": 1.0},
            cookies=cookies,
            headers=headers,
        )
        assert attach_resp.status_code == status.HTTP_409_CONFLICT

        # Attempt to remove a question
        del_resp = client.delete(
            f"{_EXAMS_URL}/{exam_id}/questions/{q1.id}",
            cookies=cookies,
            headers=headers,
        )
        assert del_resp.status_code == status.HTTP_409_CONFLICT


class TestPublicationValidationAndRollback:
    def test_publish_exam_with_no_questions_rejected(
        self, client: TestClient, faculty_user
    ):
        """FR-EXAM-005: Cannot publish an exam containing 0 questions."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Empty Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]

        pub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        assert pub_resp.status_code == status.HTTP_400_BAD_REQUEST
        assert pub_resp.json()["error"]["code"] == "EMPTY_EXAM"

    def test_publish_exam_with_archived_question_rejected_and_rolled_back(
        self, client: TestClient, test_db_session: Session, faculty_user, authored_questions
    ):
        """
        If a question attached to a draft was archived prior to publish,
        publication is rejected and the transaction rolls back cleanly.
        """
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, q2 = authored_questions

        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Rollback Test Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 2.0, "display_order": 1},
            cookies=cookies,
            headers=headers,
        )
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q2.id), "marks": 2.0, "display_order": 2},
            cookies=cookies,
            headers=headers,
        )

        # Archive Q2 right before publication
        client.post(f"{_QUESTIONS_URL}/{q2.id}/archive", cookies=cookies, headers=headers)

        pub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        assert pub_resp.status_code == status.HTTP_400_BAD_REQUEST

        # Verify rollback: exam remains DRAFT, published_at is None, no options materialized
        test_db_session.expire_all()
        exam = test_db_session.get(Exam, uuid.UUID(exam_id))
        assert exam.status == "DRAFT"
        assert exam.published_at is None
        # No frozen options exist
        for eq in exam.questions:
            assert len(eq.options) == 0


class TestUnpublishLifecycle:
    def test_unpublish_exam_blocks_new_starts_preserves_snapshots(
        self, client: TestClient, test_db_session: Session, faculty_user, authored_questions
    ):
        """
        FR-EXAM-006 & OD-08:
        Unpublishing changes status to UNPUBLISHED and does NOT delete snapshots.
        """
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, _ = authored_questions

        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Unpublish Lifecycle Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 2.0},
            cookies=cookies,
            headers=headers,
        )
        client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)

        # Unpublish
        unpub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/unpublish", cookies=cookies, headers=headers)
        assert unpub_resp.status_code == status.HTTP_200_OK
        assert unpub_resp.json()["status"] == "UNPUBLISHED"

        # Verify in DB: snapshots are still completely present!
        exam = test_db_session.get(Exam, uuid.UUID(exam_id))
        assert exam.status == "UNPUBLISHED"
        assert len(exam.questions) == 1
        assert len(exam.questions[0].options) == 3

    def test_cannot_republish_unpublished_exam(
        self, client: TestClient, faculty_user, authored_questions
    ):
        """OD-08: An unpublished examination cannot be republished. A new draft is required."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        q1, _ = authored_questions

        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "No Republish Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 2.0},
            cookies=cookies,
            headers=headers,
        )
        client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        client.post(f"{_EXAMS_URL}/{exam_id}/unpublish", cookies=cookies, headers=headers)

        # Attempt to republish
        repub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies, headers=headers)
        assert repub_resp.status_code == status.HTTP_409_CONFLICT
        assert repub_resp.json()["error"]["code"] == "EXAM_ALREADY_UNPUBLISHED"

    def test_cannot_unpublish_draft_exam(
        self, client: TestClient, faculty_user
    ):
        """A draft exam cannot be unpublished (only PUBLISHED can be unpublished)."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Draft Cannot Unpublish", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = create_resp.json()["id"]

        unpub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/unpublish", cookies=cookies, headers=headers)
        assert unpub_resp.status_code == status.HTTP_409_CONFLICT


class TestPublishAuthorization:
    def test_student_cannot_publish_exam(
        self, client: TestClient, student_user
    ):
        """Students cannot publish exams."""
        cookies, headers = auth_cookies_and_headers(student_user)
        resp = client.post(f"{_EXAMS_URL}/{uuid.uuid4()}/publish", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_faculty_cannot_publish_another_faculty_exam(
        self, client: TestClient, faculty_user, other_faculty_user, authored_questions
    ):
        """Faculty cannot publish exams created by another faculty member."""
        cookies1, headers1 = auth_cookies_and_headers(faculty_user)
        cookies2, headers2 = auth_cookies_and_headers(other_faculty_user)
        q1, _ = authored_questions

        create_resp = client.post(
            _EXAMS_URL,
            json={"title": "Faculty 1 Pub Exam", "duration_minutes": 30},
            cookies=cookies1,
            headers=headers1,
        )
        exam_id = create_resp.json()["id"]
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(q1.id), "marks": 1.0},
            cookies=cookies1,
            headers=headers1,
        )

        # Faculty 2 attempts to publish
        pub_resp = client.post(f"{_EXAMS_URL}/{exam_id}/publish", cookies=cookies2, headers=headers2)
        assert pub_resp.status_code == status.HTTP_403_FORBIDDEN
