"""
Automated tests for Question Bank CRUD and authorization.

Covers:
- docs/04_API_CONTRACT.md §3 Question bank endpoints
- docs/01_REQUIREMENTS.md FR-QUESTION-001 to FR-QUESTION-009
- Role and ownership enforcement
- Option validation (2..6 options, exactly one correct, non-empty)
- CSRF validation on mutations
"""

import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.question import Question
from app.services.topic_service import seed_taxonomy_topics
from tests.helpers import auth_cookies_and_headers, create_test_user

_BASE = "/api/v1/questions"


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


class TestQuestionCreation:
    def test_successful_question_creation(
        self, client: TestClient, faculty_user, seeded_topics
    ):
        """Faculty can create a valid MCQ question with options."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        topic = seeded_topics[0]

        payload = {
            "prompt": "Which scheduling algorithm uses a time quantum?",
            "topic_id": str(topic.id),
            "options": [
                {"text": "Round Robin", "is_correct": True},
                {"text": "FCFS", "is_correct": False},
                {"text": "SSTF", "is_correct": False},
                {"text": "FIFO page replacement", "is_correct": False},
            ],
        }

        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert data["prompt"] == payload["prompt"]
        assert data["author_id"] == str(faculty_user.id)
        assert data["topic_id"] == str(topic.id)
        assert len(data["options"]) == 4

        # Exactly 1 correct option
        correct = [o for o in data["options"] if o["is_correct"]]
        assert len(correct) == 1
        assert correct[0]["option_text"] == "Round Robin"

        # Display orders 1..4
        orders = [o["display_order"] for o in data["options"]]
        assert orders == [1, 2, 3, 4]

    def test_create_question_without_topic_permitted(
        self, client: TestClient, faculty_user
    ):
        """FR-QUESTION-005: A question without a topic is permitted."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "General question without topic?",
            "topic_id": None,
            "options": [
                {"text": "True", "is_correct": True},
                {"text": "False", "is_correct": False},
            ],
        }

        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["topic_id"] is None
        assert len(data["options"]) == 2

    def test_create_question_empty_prompt_rejected(
        self, client: TestClient, faculty_user
    ):
        """Empty prompt is rejected."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "   ",
            "options": [
                {"text": "A", "is_correct": True},
                {"text": "B", "is_correct": False},
            ],
        }
        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_create_question_fewer_than_two_options_rejected(
        self, client: TestClient, faculty_user
    ):
        """FR-QUESTION-001: At least two options required."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "Single option question?",
            "options": [
                {"text": "Only option", "is_correct": True},
            ],
        }
        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_create_question_no_correct_option_rejected(
        self, client: TestClient, faculty_user
    ):
        """FR-QUESTION-002: Exactly one option must be correct (0 correct rejected)."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "No correct option question?",
            "options": [
                {"text": "Opt 1", "is_correct": False},
                {"text": "Opt 2", "is_correct": False},
            ],
        }
        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_create_question_multiple_correct_options_rejected(
        self, client: TestClient, faculty_user
    ):
        """FR-QUESTION-002: Exactly one option must be correct (2 correct rejected)."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "Two correct options question?",
            "options": [
                {"text": "Opt 1", "is_correct": True},
                {"text": "Opt 2", "is_correct": True},
            ],
        }
        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_create_question_empty_option_text_rejected(
        self, client: TestClient, faculty_user
    ):
        """Empty option text is rejected."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "Empty option question?",
            "options": [
                {"text": "   ", "is_correct": True},
                {"text": "Valid option", "is_correct": False},
            ],
        }
        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    def test_create_question_invalid_topic_rejected(
        self, client: TestClient, faculty_user
    ):
        """Referencing non-existent topic is rejected."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        payload = {
            "prompt": "Invalid topic question?",
            "topic_id": str(uuid.uuid4()),
            "options": [
                {"text": "A", "is_correct": True},
                {"text": "B", "is_correct": False},
            ],
        }
        resp = client.post(_BASE, json=payload, cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


class TestQuestionRetrievalAndListing:
    def test_get_single_question_returns_detail(
        self, client: TestClient, faculty_user, seeded_topics
    ):
        """GET /questions/{id} returns full question with options and correct flag."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        topic = seeded_topics[1]

        create_resp = client.post(
            _BASE,
            json={
                "prompt": "Test single question retrieval?",
                "topic_id": str(topic.id),
                "options": [
                    {"text": "Ans A", "is_correct": True},
                    {"text": "Ans B", "is_correct": False},
                ],
            },
            cookies=cookies,
            headers=headers,
        )
        qid = create_resp.json()["id"]

        get_resp = client.get(f"{_BASE}/{qid}", cookies=cookies, headers=headers)
        assert get_resp.status_code == status.HTTP_200_OK
        data = get_resp.json()
        assert data["id"] == qid
        assert data["prompt"] == "Test single question retrieval?"
        assert data["topic"]["code"] == topic.code
        assert len(data["options"]) == 2

    def test_get_nonexistent_question_returns_404(
        self, client: TestClient, faculty_user
    ):
        """Missing question ID returns 404."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        resp = client.get(f"{_BASE}/{uuid.uuid4()}", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    def test_list_and_filter_questions(
        self, client: TestClient, faculty_user, seeded_topics
    ):
        """FR-QUESTION-006: Faculty can list and filter questions by topic and search query."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        topic1 = seeded_topics[0]
        topic2 = seeded_topics[1]

        # Create 2 questions with topic1, 1 with topic2
        client.post(
            _BASE,
            json={
                "prompt": "OS scheduling question alpha",
                "topic_id": str(topic1.id),
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            headers=headers,
        )
        client.post(
            _BASE,
            json={
                "prompt": "OS scheduling question beta",
                "topic_id": str(topic1.id),
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            headers=headers,
        )
        client.post(
            _BASE,
            json={
                "prompt": "Database normalization third normal form",
                "topic_id": str(topic2.id),
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            headers=headers,
        )

        # Filter by topic1
        resp_t1 = client.get(f"{_BASE}?topic_id={topic1.id}", cookies=cookies, headers=headers)
        assert resp_t1.status_code == status.HTTP_200_OK
        data_t1 = resp_t1.json()
        assert len(data_t1) == 2
        assert all(q["topic_id"] == str(topic1.id) for q in data_t1)

        # Search by keyword
        resp_search = client.get(f"{_BASE}?search=normalization", cookies=cookies, headers=headers)
        assert resp_search.status_code == status.HTTP_200_OK
        data_search = resp_search.json()
        assert len(data_search) == 1
        assert "normalization" in data_search[0]["prompt"]


class TestQuestionUpdateAndArchive:
    def test_faculty_can_update_own_question(
        self, client: TestClient, faculty_user, seeded_topics
    ):
        """Faculty can update prompt, topic, and options on their own question."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        topic = seeded_topics[0]

        create_resp = client.post(
            _BASE,
            json={
                "prompt": "Original prompt text",
                "topic_id": str(topic.id),
                "options": [
                    {"text": "Old Opt 1", "is_correct": True},
                    {"text": "Old Opt 2", "is_correct": False},
                ],
            },
            cookies=cookies,
            headers=headers,
        )
        qid = create_resp.json()["id"]

        # Update prompt and options
        patch_payload = {
            "prompt": "Updated prompt text",
            "options": [
                {"text": "New Opt A", "is_correct": False},
                {"text": "New Opt B", "is_correct": True},
                {"text": "New Opt C", "is_correct": False},
            ],
        }
        patch_resp = client.patch(f"{_BASE}/{qid}", json=patch_payload, cookies=cookies, headers=headers)
        assert patch_resp.status_code == status.HTTP_200_OK
        data = patch_resp.json()
        assert data["prompt"] == "Updated prompt text"
        assert len(data["options"]) == 3
        correct = [o for o in data["options"] if o["is_correct"]]
        assert len(correct) == 1
        assert correct[0]["option_text"] == "New Opt B"

    def test_faculty_cannot_update_another_faculty_question(
        self, client: TestClient, faculty_user, other_faculty_user
    ):
        """Faculty cannot modify questions authored by another faculty member."""
        cookies1, headers1 = auth_cookies_and_headers(faculty_user)
        cookies2, headers2 = auth_cookies_and_headers(other_faculty_user)

        create_resp = client.post(
            _BASE,
            json={
                "prompt": "Faculty 1 prompt",
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies1,
            headers=headers1,
        )
        qid = create_resp.json()["id"]

        # Faculty 2 attempts to patch Faculty 1's question
        patch_resp = client.patch(
            f"{_BASE}/{qid}",
            json={"prompt": "Hijacked prompt"},
            cookies=cookies2,
            headers=headers2,
        )
        assert patch_resp.status_code == status.HTTP_403_FORBIDDEN

    def test_soft_archive_question(
        self, client: TestClient, faculty_user
    ):
        """Soft archiving sets archived_at and excludes from default question listing."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        create_resp = client.post(
            _BASE,
            json={
                "prompt": "Question to be archived",
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            headers=headers,
        )
        qid = create_resp.json()["id"]

        # Archive
        archive_resp = client.post(f"{_BASE}/{qid}/archive", cookies=cookies, headers=headers)
        assert archive_resp.status_code == status.HTTP_200_OK
        assert archive_resp.json()["archived_at"] is not None

        # Excluded from default list
        list_resp = client.get(_BASE, cookies=cookies, headers=headers)
        ids = [q["id"] for q in list_resp.json()]
        assert qid not in ids

        # Included when include_archived=true
        list_archived = client.get(f"{_BASE}?include_archived=true", cookies=cookies, headers=headers)
        ids_archived = [q["id"] for q in list_archived.json()]
        assert qid in ids_archived

    def test_archived_question_cannot_be_updated(
        self, client: TestClient, faculty_user
    ):
        """Updating an archived question is rejected."""
        cookies, headers = auth_cookies_and_headers(faculty_user)
        create_resp = client.post(
            _BASE,
            json={
                "prompt": "Question to freeze",
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            headers=headers,
        )
        qid = create_resp.json()["id"]
        client.post(f"{_BASE}/{qid}/archive", cookies=cookies, headers=headers)

        patch_resp = client.patch(
            f"{_BASE}/{qid}",
            json={"prompt": "Attempt edit archived"},
            cookies=cookies,
            headers=headers,
        )
        assert patch_resp.status_code == status.HTTP_400_BAD_REQUEST


class TestQuestionAuthorizationAndCSRF:
    def test_student_rejected_from_question_bank(
        self, client: TestClient, student_user
    ):
        """Students must not gain access to faculty question bank."""
        cookies, headers = auth_cookies_and_headers(student_user)

        resp_get = client.get(_BASE, cookies=cookies, headers=headers)
        assert resp_get.status_code == status.HTTP_403_FORBIDDEN

        resp_post = client.post(
            _BASE,
            json={
                "prompt": "Student prompt",
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            headers=headers,
        )
        assert resp_post.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_rejected(self, client: TestClient):
        """Unauthenticated requests return 401."""
        resp = client.get(_BASE)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_post_question_missing_csrf_rejected(
        self, client: TestClient, faculty_user
    ):
        """State-changing question bank requests require CSRF."""
        cookies, _ = auth_cookies_and_headers(faculty_user)
        resp = client.post(
            _BASE,
            json={
                "prompt": "CSRF test prompt",
                "options": [{"text": "A", "is_correct": True}, {"text": "B", "is_correct": False}],
            },
            cookies=cookies,
            # No CSRF header
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
