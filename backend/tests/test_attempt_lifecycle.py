"""
Automated tests for M1-ATTEMPT-1: Student Examination Lifecycle & Secure Attempt Engine.

Covers:
- docs/04_API_CONTRACT.md §4 Student exam catalogue and attempt API
- docs/04_API_CONTRACT.md §5 Faculty results and attempt list
- docs/01_REQUIREMENTS.md FR-STUD, FR-ATTEMPT, FR-TIME, FR-SAVE, FR-SUBMIT, FR-EXPIRE, FR-RESULT
- Available exam listing and visibility
- Idempotent attempt starting, deadline calculation, and snapshot-question delivery
- Confidentiality: omission of is_correct during active attempt
- Durable answer autosave, revision increment, and recovery
- Optimistic concurrency and revision conflict handling (409)
- Exclusive deadline boundary enforcement and lazy expiry (IN_PROGRESS -> EXPIRED)
- Submission and atomic scoring
- Repeated submission idempotency
- Post-finalization result retrieval and correct-option disclosure
- Faculty attempt list and overdue finalization
- Ownership, role guards (STUDENT vs FACULTY_ADMIN), and CSRF protection
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.attempt import Attempt, AttemptAnswer
from app.models.exam import Exam, ExamQuestion, ExamQuestionOption
from app.models.question import Question, QuestionOption
from app.models.user import User
from app.services.exam_service import create_exam, publish_exam
from app.services.question_service import create_question
from app.services.topic_service import seed_taxonomy_topics
from tests.helpers import auth_cookies_and_headers, create_test_user

_EXAMS_URL = "/api/v1/exams"
_ATTEMPTS_URL = "/api/v1/attempts"


@pytest.fixture
def seeded_topics(test_db_session: Session):
    return seed_taxonomy_topics(test_db_session)


@pytest.fixture
def faculty_user(test_db_session: Session) -> User:
    return create_test_user(test_db_session, role="FACULTY_ADMIN")


@pytest.fixture
def other_faculty_user(test_db_session: Session) -> User:
    return create_test_user(test_db_session, role="FACULTY_ADMIN")


@pytest.fixture
def student_user(test_db_session: Session) -> User:
    return create_test_user(test_db_session, role="STUDENT")


@pytest.fixture
def other_student_user(test_db_session: Session) -> User:
    return create_test_user(test_db_session, role="STUDENT")


@pytest.fixture
def published_exam(test_db_session: Session, faculty_user: User, seeded_topics):
    """Creates and publishes an exam with 2 questions and 7.5 total marks."""
    from app.schemas.question import QuestionOptionCreate

    q1 = create_question(
        test_db_session,
        author_id=faculty_user.id,
        prompt="Which CPU scheduling algorithm uses time slicing?",
        topic_id=seeded_topics[1].id,
        options_data=[
            QuestionOptionCreate(text="Round Robin", is_correct=True, display_order=1),
            QuestionOptionCreate(text="FCFS", is_correct=False, display_order=2),
            QuestionOptionCreate(text="SJF", is_correct=False, display_order=3),
        ],
    )
    q2 = create_question(
        test_db_session,
        author_id=faculty_user.id,
        prompt="Which normal form eliminates partial key dependencies?",
        topic_id=seeded_topics[4].id,
        options_data=[
            QuestionOptionCreate(text="1NF", is_correct=False, display_order=1),
            QuestionOptionCreate(text="2NF", is_correct=True, display_order=2),
            QuestionOptionCreate(text="3NF", is_correct=False, display_order=3),
            QuestionOptionCreate(text="BCNF", is_correct=False, display_order=4),
        ],
    )

    exam = create_exam(
        test_db_session,
        creator_id=faculty_user.id,
        title="Midterm Examination 2026",
        instructions="Select one option per question.",
        duration_minutes=30,
    )

    # Attach questions
    eq1 = ExamQuestion(
        exam_id=exam.id,
        source_question_id=q1.id,
        prompt_snapshot=q1.prompt,
        topic_code_snapshot="OS_SCHEDULING",
        topic_name_snapshot="CPU Scheduling",
        marks=Decimal("3.50"),
        display_order=1,
    )
    eq2 = ExamQuestion(
        exam_id=exam.id,
        source_question_id=q2.id,
        prompt_snapshot=q2.prompt,
        topic_code_snapshot="DB_NORMALIZATION",
        topic_name_snapshot="Relational Modeling and Normalization",
        marks=Decimal("4.00"),
        display_order=2,
    )
    test_db_session.add_all([eq1, eq2])
    test_db_session.commit()

    # Publish
    published = publish_exam(test_db_session, exam_id=exam.id, actor_id=faculty_user.id)
    return published


# ===========================================================================
# 1. Available Exam Catalogue
# ===========================================================================

class TestAvailableExamCatalogue:
    def test_student_can_list_available_published_exams(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """GET /exams/available lists published exams with duration and marks."""
        cookies, headers = auth_cookies_and_headers(student_user)
        resp = client.get(f"{_EXAMS_URL}/available", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        assert len(data) >= 1
        item = next(e for e in data if e["id"] == str(published_exam.id))
        assert item["title"] == "Midterm Examination 2026"
        assert item["duration_minutes"] == 30
        assert item["question_count"] == 2
        assert Decimal(str(item["total_marks"])) == Decimal("7.50")
        assert item["has_attempt"] is False
        assert item["attempt_id"] is None

    def test_available_exams_omits_draft_and_unpublished(
        self, client: TestClient, test_db_session: Session, student_user: User, faculty_user: User
    ):
        """Draft and unpublished exams do not appear in /exams/available."""
        draft = create_exam(
            test_db_session,
            creator_id=faculty_user.id,
            title="Secret Draft Exam",
            duration_minutes=45,
        )
        cookies, headers = auth_cookies_and_headers(student_user)
        resp = client.get(f"{_EXAMS_URL}/available", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_200_OK
        ids = [e["id"] for e in resp.json()]
        assert str(draft.id) not in ids

    def test_available_exams_requires_student_role(
        self, client: TestClient, faculty_user: User
    ):
        """Faculty cannot access student available exams route."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        resp = client.get(f"{_EXAMS_URL}/available", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# 2. Starting an Attempt & In-Progress Confidentiality
# ===========================================================================

class TestStartAttempt:
    def test_student_start_attempt_success(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """
        POST /exams/{id}/attempts/start:
        - Creates IN_PROGRESS attempt.
        - Calculates deadline = start + duration.
        - Pre-populates answer rows for all snapshot questions.
        - OMITTING is_correct from question options (AC-14, FR-STUD-012).
        """
        cookies, headers = auth_cookies_and_headers(student_user)
        resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code == status.HTTP_200_OK, resp.text
        data = resp.json()
        assert data["status"] == "IN_PROGRESS"
        assert data["remaining_seconds"] > 0
        assert data["exam"]["title"] == "Midterm Examination 2026"
        assert Decimal(str(data["exam"]["total_marks"])) == Decimal("7.50")
        assert len(data["questions"]) == 2

        # Verify options strictly omit is_correct!
        for q in data["questions"]:
            assert "prompt" in q
            assert "marks" in q
            assert len(q["options"]) >= 2
            for opt in q["options"]:
                assert "is_correct" not in opt, "SECURITY VIOLATION: is_correct leaked in active attempt!"
                assert "text" in opt
                assert "display_order" in opt
            assert q["answer"]["selected_option_id"] is None
            assert q["answer"]["marked_for_review"] is False
            assert q["answer"]["revision"] == 0

    def test_start_attempt_is_idempotent(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """Calling start attempt twice for the same student/exam returns the existing attempt."""
        cookies, headers = auth_cookies_and_headers(student_user)
        resp1 = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        assert resp1.status_code == status.HTTP_200_OK
        att_id1 = resp1.json()["attempt_id"]

        resp2 = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        assert resp2.status_code == status.HTTP_200_OK
        att_id2 = resp2.json()["attempt_id"]
        assert att_id1 == att_id2

    def test_cannot_start_attempt_on_draft_exam(
        self, client: TestClient, test_db_session: Session, student_user: User, faculty_user: User
    ):
        """Students cannot start draft exams."""
        draft = create_exam(
            test_db_session,
            creator_id=faculty_user.id,
            title="Unpublished Draft",
            duration_minutes=20,
        )
        cookies, headers = auth_cookies_and_headers(student_user)
        resp = client.post(
            f"{_EXAMS_URL}/{draft.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_start_attempt_requires_csrf(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """Start attempt requires CSRF header."""
        cookies, _ = auth_cookies_and_headers(student_user)
        resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            # No CSRF header
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_faculty_cannot_start_attempt(
        self, client: TestClient, faculty_user: User, published_exam: Exam
    ):
        """Faculty cannot start student attempts."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# 3. Answer Persistence & Optimistic Concurrency
# ===========================================================================

class TestAnswerSavingAndRecovery:
    def test_save_and_retrieve_answer(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """
        PUT /attempts/{id}/answers/{qid}:
        - Saves selected option and review flag.
        - Increments revision from 0 to 1.
        - GET /attempts/{id} reflects the saved answer.
        """
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        att_data = start_resp.json()
        attempt_id = att_data["attempt_id"]
        q1 = att_data["questions"][0]
        qid = q1["exam_question_id"]
        opt1_id = q1["options"][0]["id"]

        # Save answer
        save_resp = client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{qid}",
            json={
                "selected_option_id": opt1_id,
                "marked_for_review": True,
                "expected_revision": 0,
            },
            cookies=cookies,
            headers=headers,
        )
        assert save_resp.status_code == status.HTTP_200_OK, save_resp.text
        save_data = save_resp.json()
        assert save_data["selected_option_id"] == opt1_id
        assert save_data["marked_for_review"] is True
        assert save_data["revision"] == 1
        assert "saved_at" in save_data

        # Verify retrieval / recovery
        get_resp = client.get(f"{_ATTEMPTS_URL}/{attempt_id}", cookies=cookies, headers=headers)
        assert get_resp.status_code == status.HTTP_200_OK
        recovered = get_resp.json()
        rec_q1 = next(q for q in recovered["questions"] if q["exam_question_id"] == qid)
        assert rec_q1["answer"]["selected_option_id"] == opt1_id
        assert rec_q1["answer"]["marked_for_review"] is True
        assert rec_q1["answer"]["revision"] == 1

    def test_stale_revision_conflict_rejected(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """
        FR-SAVE-005 & contract §4:
        If expected_revision does not match current revision, returns 409 ANSWER_REVISION_CONFLICT
        with canonical current state.
        """
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        att_data = start_resp.json()
        attempt_id = att_data["attempt_id"]
        q1 = att_data["questions"][0]
        qid = q1["exam_question_id"]
        opt1_id = q1["options"][0]["id"]
        opt2_id = q1["options"][1]["id"]

        # First save (0 -> 1)
        client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{qid}",
            json={"selected_option_id": opt1_id, "expected_revision": 0},
            cookies=cookies,
            headers=headers,
        )

        # Stale save (sending expected_revision=0 again)
        stale_resp = client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{qid}",
            json={"selected_option_id": opt2_id, "expected_revision": 0},
            cookies=cookies,
            headers=headers,
        )
        assert stale_resp.status_code == status.HTTP_409_CONFLICT
        conflict_data = stale_resp.json()
        assert conflict_data["error"]["code"] == "ANSWER_REVISION_CONFLICT"
        assert conflict_data["error"]["details"]["revision"] == 1
        assert conflict_data["error"]["details"]["selected_option_id"] == opt1_id

    def test_cannot_save_option_from_different_question(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """Option belonging to Q2 cannot be saved as an answer to Q1."""
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        att_data = start_resp.json()
        attempt_id = att_data["attempt_id"]
        q1_id = att_data["questions"][0]["exam_question_id"]
        q2_opt_id = att_data["questions"][1]["options"][0]["id"]

        resp = client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{q1_id}",
            json={"selected_option_id": q2_opt_id, "expected_revision": 0},
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error"]["code"] == "INVALID_OPTION"

    def test_student_cannot_access_other_student_attempt(
        self, client: TestClient, student_user: User, other_student_user: User, published_exam: Exam
    ):
        """Student B cannot access or mutate Student A's attempt."""
        cookies_a, headers_a = auth_cookies_and_headers(student_user)
        cookies_b, headers_b = auth_cookies_and_headers(other_student_user)

        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies_a,
            headers=headers_a,
        )
        attempt_id = start_resp.json()["attempt_id"]

        # Student B attempts GET
        get_resp = client.get(f"{_ATTEMPTS_URL}/{attempt_id}", cookies=cookies_b, headers=headers_b)
        assert get_resp.status_code == status.HTTP_403_FORBIDDEN

        # Student B attempts PUT answer
        qid = start_resp.json()["questions"][0]["exam_question_id"]
        put_resp = client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{qid}",
            json={"selected_option_id": None, "expected_revision": 0},
            cookies=cookies_b,
            headers=headers_b,
        )
        assert put_resp.status_code == status.HTTP_403_FORBIDDEN


# ===========================================================================
# 4. Deadline Enforcement & Lazy Expiry
# ===========================================================================

class TestDeadlineEnforcement:
    def test_lazy_expiry_finalizes_overdue_attempt(
        self, client: TestClient, test_db_session: Session, student_user: User, published_exam: Exam
    ):
        """
        FR-EXPIRE-001 & Appendix A.2:
        When an attempt is past its deadline, retrieving it lazily finalizes as EXPIRED.
        """
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        attempt_id = start_resp.json()["attempt_id"]

        # Simulate deadline passing in the past
        att = test_db_session.get(Attempt, uuid.UUID(attempt_id))
        att.started_at = datetime.now(timezone.utc) - timedelta(hours=2)
        att.deadline_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        test_db_session.commit()

        # GET /attempts/{id} discovers overdue attempt and lazily finalizes
        get_resp = client.get(f"{_ATTEMPTS_URL}/{attempt_id}", cookies=cookies, headers=headers)
        assert get_resp.status_code == status.HTTP_200_OK
        data = get_resp.json()
        assert data["status"] == "EXPIRED"
        assert data["remaining_seconds"] == 0

        # DB row is now finalized
        test_db_session.refresh(att)
        assert att.status == "EXPIRED"
        assert att.finalized_at is not None
        assert att.score is not None

    def test_save_rejected_after_deadline_and_finalizes_expired(
        self, client: TestClient, test_db_session: Session, student_user: User, published_exam: Exam
    ):
        """FR-TIME-005: Answer save processed after deadline is rejected and finalizes attempt."""
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        attempt_id = start_resp.json()["attempt_id"]
        qid = start_resp.json()["questions"][0]["exam_question_id"]
        opt_id = start_resp.json()["questions"][0]["options"][0]["id"]

        # Set deadline to the past
        att = test_db_session.get(Attempt, uuid.UUID(attempt_id))
        att.started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        att.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        test_db_session.commit()

        # Attempt to save answer after deadline
        save_resp = client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{qid}",
            json={"selected_option_id": opt_id, "expected_revision": 0},
            cookies=cookies,
            headers=headers,
        )
        assert save_resp.status_code == status.HTTP_409_CONFLICT
        assert save_resp.json()["error"]["code"] == "ATTEMPT_EXPIRED"

        # Verify attempt transitioned to EXPIRED
        test_db_session.refresh(att)
        assert att.status == "EXPIRED"
        assert att.finalized_at is not None


# ===========================================================================
# 5. Submission & Atomic Scoring
# ===========================================================================

class TestSubmissionAndScoring:
    def test_successful_timely_submission_scores_correctly(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """
        POST /attempts/{id}/submit:
        - Timely submission transitions to SUBMITTED.
        - Correctly scores answered questions (Q1 correct = 3.5, Q2 unanswered = 0; score = 3.50).
        """
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        att_data = start_resp.json()
        attempt_id = att_data["attempt_id"]

        # Q1 has options: Round Robin (correct), FCFS, SJF.
        # Find Round Robin option ID by matching text
        q1 = att_data["questions"][0]
        rr_opt = next(o for o in q1["options"] if o["text"] == "Round Robin")

        # Answer Q1 correctly
        client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{q1['exam_question_id']}",
            json={"selected_option_id": rr_opt["id"], "expected_revision": 0},
            cookies=cookies,
            headers=headers,
        )

        # Leave Q2 unanswered. Submit attempt.
        sub_resp = client.post(
            f"{_ATTEMPTS_URL}/{attempt_id}/submit",
            cookies=cookies,
            headers=headers,
        )
        assert sub_resp.status_code == status.HTTP_200_OK, sub_resp.text
        sub_data = sub_resp.json()
        assert sub_data["status"] == "SUBMITTED"
        assert Decimal(str(sub_data["score"])) == Decimal("3.50")
        assert Decimal(str(sub_data["total_marks"])) == Decimal("7.50")
        assert sub_data["finalized_at"] is not None

    def test_repeated_submit_is_idempotent(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """FR-SUBMIT-006: Submitting an already finalized attempt returns existing result safely."""
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        attempt_id = start_resp.json()["attempt_id"]

        sub1 = client.post(f"{_ATTEMPTS_URL}/{attempt_id}/submit", cookies=cookies, headers=headers)
        assert sub1.status_code == status.HTTP_200_OK

        sub2 = client.post(f"{_ATTEMPTS_URL}/{attempt_id}/submit", cookies=cookies, headers=headers)
        assert sub2.status_code == status.HTTP_200_OK
        assert sub1.json() == sub2.json()

    def test_post_submission_answer_mutation_rejected(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """Answers cannot be modified after finalization."""
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        attempt_id = start_resp.json()["attempt_id"]
        qid = start_resp.json()["questions"][0]["exam_question_id"]

        # Submit attempt
        client.post(f"{_ATTEMPTS_URL}/{attempt_id}/submit", cookies=cookies, headers=headers)

        # Attempt to save answer after submit
        resp = client.put(
            f"{_ATTEMPTS_URL}/{attempt_id}/answers/{qid}",
            json={"selected_option_id": None, "expected_revision": 0},
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code == status.HTTP_409_CONFLICT


# ===========================================================================
# 6. Finalized Result Disclosure (OD-04)
# ===========================================================================

class TestFinalizedResultDisclosure:
    def test_result_not_available_before_finalization(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """GET /attempts/{id}/result is rejected while attempt is IN_PROGRESS."""
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        attempt_id = start_resp.json()["attempt_id"]

        resp = client.get(f"{_ATTEMPTS_URL}/{attempt_id}/result", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.json()["error"]["code"] == "RESULT_NOT_AVAILABLE"

    def test_result_discloses_correct_options_post_finalization(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """
        OD-04 & contract §4:
        Post-finalization, result reveals is_correct on options and question correctness.
        """
        cookies, headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=cookies,
            headers=headers,
        )
        att_data = start_resp.json()
        attempt_id = att_data["attempt_id"]

        # Submit attempt
        client.post(f"{_ATTEMPTS_URL}/{attempt_id}/submit", cookies=cookies, headers=headers)

        # Retrieve result
        resp = client.get(f"{_ATTEMPTS_URL}/{attempt_id}/result", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_200_OK, resp.text
        res = resp.json()
        assert res["status"] == "SUBMITTED"
        assert len(res["questions"]) == 2

        # Verify correct options are now disclosed
        for q in res["questions"]:
            assert "is_correct" in q
            assert len(q["options"]) >= 2
            correct_opts = [o for o in q["options"] if o["is_correct"]]
            assert len(correct_opts) == 1, "Must disclose exactly one correct option per question."

    def test_faculty_can_view_any_finalized_attempt_result(
        self, client: TestClient, faculty_user: User, student_user: User, published_exam: Exam
    ):
        """Faculty can inspect finalized attempt result."""
        s_cookies, s_headers = auth_cookies_and_headers(student_user)
        start_resp = client.post(
            f"{_EXAMS_URL}/{published_exam.id}/attempts/start",
            cookies=s_cookies,
            headers=s_headers,
        )
        attempt_id = start_resp.json()["attempt_id"]
        client.post(f"{_ATTEMPTS_URL}/{attempt_id}/submit", cookies=s_cookies, headers=s_headers)

        f_cookies, f_headers = auth_cookies_and_headers(faculty_user)
        f_resp = client.get(f"{_ATTEMPTS_URL}/{attempt_id}/result", cookies=f_cookies, headers=f_headers)
        assert f_resp.status_code == status.HTTP_200_OK
        assert f_resp.json()["attempt_id"] == attempt_id


# ===========================================================================
# 7. Faculty Attempt List
# ===========================================================================

class TestFacultyAttemptList:
    def test_faculty_can_list_attempts_for_exam(
        self, client: TestClient, faculty_user: User, student_user: User, published_exam: Exam
    ):
        """GET /exams/{id}/attempts lists attempts for faculty."""
        s_cookies, s_headers = auth_cookies_and_headers(student_user)
        client.post(f"{_EXAMS_URL}/{published_exam.id}/attempts/start", cookies=s_cookies, headers=s_headers)

        f_cookies, f_headers = auth_cookies_and_headers(faculty_user)
        resp = client.get(f"{_EXAMS_URL}/{published_exam.id}/attempts", cookies=f_cookies, headers=f_headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) == 1
        att_item = data[0]
        assert att_item["student_email"] == student_user.email
        assert att_item["status"] == "IN_PROGRESS"

    def test_student_cannot_list_faculty_attempts(
        self, client: TestClient, student_user: User, published_exam: Exam
    ):
        """Students cannot access the faculty attempt list."""
        cookies, headers = auth_cookies_and_headers(student_user)
        resp = client.get(f"{_EXAMS_URL}/{published_exam.id}/attempts", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN
