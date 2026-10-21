"""
Automated tests for Draft Examination Authoring and Question Management.

Covers:
- docs/04_API_CONTRACT.md §3 Faculty examination and question management
- docs/01_REQUIREMENTS.md FR-EXAM-001 to FR-EXAM-004, FR-EXAM-007, FR-EXAM-009
- Draft exam creation, reading, and metadata updating
- Adding, ordering, and removing questions in draft exams
- Ownership, authorization, and validation rules
"""

from decimal import Decimal
import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
def sample_question(test_db_session: Session, faculty_user, seeded_topics):
    """Fixture creating a valid question bank item."""
    from app.schemas.question import QuestionOptionCreate

    return create_question(
        test_db_session,
        author_id=faculty_user.id,
        prompt="Sample authoring question prompt?",
        topic_id=seeded_topics[0].id,
        options_data=[
            QuestionOptionCreate(text="Opt 1", is_correct=True),
            QuestionOptionCreate(text="Opt 2", is_correct=False),
        ],
    )


@pytest.fixture
def sample_question_2(test_db_session: Session, faculty_user, seeded_topics):
    """Fixture creating a second valid question bank item."""
    from app.schemas.question import QuestionOptionCreate

    return create_question(
        test_db_session,
        author_id=faculty_user.id,
        prompt="Second authoring question prompt?",
        topic_id=seeded_topics[1].id,
        options_data=[
            QuestionOptionCreate(text="Ans A", is_correct=True),
            QuestionOptionCreate(text="Ans B", is_correct=False),
            QuestionOptionCreate(text="Ans C", is_correct=False),
        ],
    )


class TestDraftExamCreationAndListing:
    def test_create_draft_exam_successful(
        self, client: TestClient, faculty_user
    ):
        """FR-EXAM-001: Faculty can create a DRAFT examination with title, instructions, and duration."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "title": "Operating Systems Midterm",
            "instructions": "Answer all questions carefully.",
            "duration_minutes": 45,
        }
        resp = client.post(_EXAMS_URL, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert data["title"] == payload["title"]
        assert data["instructions"] == payload["instructions"]
        assert data["duration_minutes"] == 45
        assert data["status"] == "DRAFT"
        assert data["question_count"] == 0
        assert Decimal(str(data["total_marks"])) == Decimal("0.00")
        assert data["published_at"] is None

    def test_create_draft_exam_invalid_duration_rejected(
        self, client: TestClient, faculty_user
    ):
        """FR-EXAM-002: Duration must be positive and <= configured maximum."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        # Zero duration
        resp0 = client.post(
            _EXAMS_URL,
            json={"title": "Zero Exam", "duration_minutes": 0},
            cookies=cookies,
            headers=headers,
        )
        assert resp0.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY)

        # Exceeds maximum 240
        resp_too_long = client.post(
            _EXAMS_URL,
            json={"title": "Too Long Exam", "duration_minutes": 300},
            cookies=cookies,
            headers=headers,
        )
        assert resp_too_long.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_create_draft_exam_blank_title_rejected(
        self, client: TestClient, faculty_user
    ):
        """FR-EXAM-002: Title must be non-empty."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        resp = client.post(
            _EXAMS_URL,
            json={"title": "   ", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_list_exams_returns_summary_with_counts(
        self, client: TestClient, faculty_user
    ):
        """FR-EXAM-007: Faculty exam list returns title, duration, status, and question count."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        client.post(
            _EXAMS_URL,
            json={"title": "Exam A", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        client.post(
            _EXAMS_URL,
            json={"title": "Exam B", "duration_minutes": 60},
            cookies=cookies,
            headers=headers,
        )

        resp = client.get(_EXAMS_URL, cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) >= 2
        titles = [e["title"] for e in data]
        assert "Exam A" in titles
        assert "Exam B" in titles


class TestDraftExamDetailAndUpdate:
    def test_get_draft_exam_detail(
        self, client: TestClient, faculty_user, sample_question
    ):
        """GET /exams/{id} returns draft exam metadata and attached questions."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Detail Test Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        # Attach sample question
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 2.5},
            cookies=cookies,
            headers=headers,
        )

        detail_resp = client.get(f"{_EXAMS_URL}/{exam_id}", cookies=cookies, headers=headers)
        assert detail_resp.status_code == status.HTTP_200_OK
        data = detail_resp.json()
        assert data["id"] == exam_id
        assert data["question_count"] == 1
        assert Decimal(str(data["total_marks"])) == Decimal("2.50")
        assert len(data["questions"]) == 1
        q0 = data["questions"][0]
        assert q0["source_question_id"] == str(sample_question.id)
        assert q0["prompt"] == sample_question.prompt
        assert Decimal(str(q0["marks"])) == Decimal("2.50")
        assert q0["display_order"] == 1

    def test_patch_draft_exam_metadata(
        self, client: TestClient, faculty_user
    ):
        """FR-EXAM-003: Faculty can edit draft exam title, instructions, and duration."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Original Title", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        patch_resp = client.patch(
            f"{_EXAMS_URL}/{exam_id}",
            json={"title": "Revised Title", "duration_minutes": 50, "instructions": "Updated instructions."},
            cookies=cookies,
            headers=headers,
        )
        assert patch_resp.status_code == status.HTTP_200_OK
        data = patch_resp.json()
        assert data["title"] == "Revised Title"
        assert data["duration_minutes"] == 50
        assert data["instructions"] == "Updated instructions."

    def test_patch_draft_exam_forbidden_for_other_faculty(
        self, client: TestClient, faculty_user, other_faculty_user
    ):
        """Faculty cannot modify examinations created by another faculty member."""
        cookies1, headers1 = auth_cookies_and_headers(faculty_user)
        cookies2, headers2 = auth_cookies_and_headers(other_faculty_user)

        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Faculty 1 Exam", "duration_minutes": 30},
            cookies=cookies1,
            headers=headers1,
        )
        exam_id = exam_resp.json()["id"]

        patch_resp = client.patch(
            f"{_EXAMS_URL}/{exam_id}",
            json={"title": "Hijacked Exam"},
            cookies=cookies2,
            headers=headers2,
        )
        assert patch_resp.status_code == status.HTTP_403_FORBIDDEN


class TestDraftQuestionManagement:
    def test_attach_questions_and_calculate_total_marks(
        self, client: TestClient, faculty_user, sample_question, sample_question_2
    ):
        """FR-EXAM-004 & FR-EXAM-009: Questions can be attached with order and total marks is summed."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Sum Marks Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        # Attach Q1 with marks=2.00
        r1 = client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 2.0},
            cookies=cookies,
            headers=headers,
        )
        assert r1.status_code == status.HTTP_201_CREATED
        assert r1.json()["question_count"] == 1
        assert Decimal(str(r1.json()["total_marks"])) == Decimal("2.00")

        # Attach Q2 with marks=3.50
        r2 = client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question_2.id), "marks": 3.5},
            cookies=cookies,
            headers=headers,
        )
        assert r2.status_code == status.HTTP_201_CREATED
        assert r2.json()["question_count"] == 2
        assert Decimal(str(r2.json()["total_marks"])) == Decimal("5.50")

    def test_attach_duplicate_question_rejected(
        self, client: TestClient, faculty_user, sample_question
    ):
        """Attaching the same question twice to an exam is rejected with 409 conflict."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Duplicate Q Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 1.0},
            cookies=cookies,
            headers=headers,
        )

        dup_resp = client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 1.0},
            cookies=cookies,
            headers=headers,
        )
        assert dup_resp.status_code == status.HTTP_409_CONFLICT

    def test_attach_archived_question_rejected(
        self, client: TestClient, faculty_user, sample_question
    ):
        """Archived questions cannot be attached to an examination."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        # Archive sample question
        client.post(f"{_QUESTIONS_URL}/{sample_question.id}/archive", cookies=cookies, headers=headers)

        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Archived Attach Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        attach_resp = client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 1.0},
            cookies=cookies,
            headers=headers,
        )
        assert attach_resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_reorder_and_replace_questions_via_put(
        self, client: TestClient, faculty_user, sample_question, sample_question_2
    ):
        """PUT /exams/{id}/questions bulk updates question ordering and marks."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Reorder Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        # Initial single question
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 1.0, "display_order": 1},
            cookies=cookies,
            headers=headers,
        )

        # Bulk reorder: Q2 as order 1 (marks 5.0), Q1 as order 2 (marks 2.0)
        put_payload = [
            {"question_id": str(sample_question_2.id), "marks": 5.0, "display_order": 1},
            {"question_id": str(sample_question.id), "marks": 2.0, "display_order": 2},
        ]
        put_resp = client.put(f"{_EXAMS_URL}/{exam_id}/questions", json=put_payload, cookies=cookies, headers=headers)
        assert put_resp.status_code == status.HTTP_200_OK
        data = put_resp.json()
        assert data["question_count"] == 2
        assert Decimal(str(data["total_marks"])) == Decimal("7.00")
        assert data["questions"][0]["source_question_id"] == str(sample_question_2.id)
        assert data["questions"][0]["display_order"] == 1
        assert data["questions"][1]["source_question_id"] == str(sample_question.id)
        assert data["questions"][1]["display_order"] == 2

    def test_remove_question_from_draft(
        self, client: TestClient, faculty_user, sample_question, sample_question_2
    ):
        """DELETE /exams/{id}/questions/{qid} removes question from draft exam."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        exam_resp = client.post(
            _EXAMS_URL,
            json={"title": "Delete Q Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        exam_id = exam_resp.json()["id"]

        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question.id), "marks": 2.0},
            cookies=cookies,
            headers=headers,
        )
        client.post(
            f"{_EXAMS_URL}/{exam_id}/questions",
            json={"question_id": str(sample_question_2.id), "marks": 3.0},
            cookies=cookies,
            headers=headers,
        )

        # Remove Q1
        del_resp = client.delete(
            f"{_EXAMS_URL}/{exam_id}/questions/{sample_question.id}",
            cookies=cookies,
            headers=headers,
        )
        assert del_resp.status_code == status.HTTP_200_OK
        data = del_resp.json()
        assert data["question_count"] == 1
        assert Decimal(str(data["total_marks"])) == Decimal("3.00")
        assert data["questions"][0]["source_question_id"] == str(sample_question_2.id)


class TestDraftExamAuthorization:
    def test_student_cannot_access_exam_authoring(
        self, client: TestClient, student_user
    ):
        """Students must receive 403 on exam authoring endpoints."""
        cookies, headers = auth_cookies_and_headers(student_user)

        resp_list = client.get(_EXAMS_URL, cookies=cookies, headers=headers)
        assert resp_list.status_code == status.HTTP_403_FORBIDDEN

        resp_post = client.post(
            _EXAMS_URL,
            json={"title": "Student Exam", "duration_minutes": 30},
            cookies=cookies,
            headers=headers,
        )
        assert resp_post.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_cannot_access_exam_authoring(
        self, client: TestClient
    ):
        """Unauthenticated requests must receive 401."""
        resp = client.get(_EXAMS_URL)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
