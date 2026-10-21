"""
Automated tests for Topic taxonomy seeding and retrieval.

Requirements covered:
- docs/03_DATABASE_DESIGN.md §3.2 (topics table, check constraints)
- docs/07_AI_ML_DESIGN.md §2 (8 authoritative topics)
- Idempotency: repeated seeding produces no duplicates and preserves existing IDs/FKs
- GET /api/v1/topics API authentication and response schema
"""

import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.question import Question
from app.models.topic import Topic
from app.models.user import User
from app.services.topic_service import (
    TAXONOMY_TOPICS,
    list_topics,
    seed_taxonomy_topics,
)
from tests.helpers import auth_cookies_and_headers, create_test_user


class TestTopicSeeding:
    def test_seed_taxonomy_topics_creates_exact_eight(self, test_db_session: Session):
        """Seeding must create exactly the 8 authoritative taxonomy topics."""
        # Clean any prior topics in this transaction
        seeded = seed_taxonomy_topics(test_db_session)
        assert len(seeded) == 8

        topics_in_db = list_topics(test_db_session, active_only=False)
        assert len(topics_in_db) == 8

        codes = {t.code for t in topics_in_db}
        expected_codes = {item["code"] for item in TAXONOMY_TOPICS}
        assert codes == expected_codes

        for t in topics_in_db:
            assert t.subject in ("OS", "DBMS")
            assert len(t.name) > 0
            assert t.is_active is True

    def test_seed_taxonomy_idempotency_no_duplicates(self, test_db_session: Session):
        """Re-running the seed function must not duplicate topics or alter existing IDs."""
        first_run = seed_taxonomy_topics(test_db_session)
        first_ids = {t.code: t.id for t in first_run}

        second_run = seed_taxonomy_topics(test_db_session)
        second_ids = {t.code: t.id for t in second_run}

        assert first_ids == second_ids

        all_topics = list_topics(test_db_session, active_only=False)
        assert len(all_topics) == 8

    def test_seed_preserves_existing_topic_question_references(
        self, test_db_session: Session
    ):
        """Existing topic IDs and related question references must remain intact."""
        seeded = seed_taxonomy_topics(test_db_session)
        target_topic = seeded[0]

        faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
        q = Question(
            author_id=faculty.id,
            topic_id=target_topic.id,
            prompt="Sample Question on " + target_topic.name,
        )
        test_db_session.add(q)
        test_db_session.commit()
        test_db_session.refresh(q)

        # Re-seed
        seed_taxonomy_topics(test_db_session)

        # Verify question still points to the same topic
        test_db_session.refresh(q)
        assert q.topic_id == target_topic.id
        assert q.topic.code == target_topic.code

    def test_topic_constraints_subject_and_nonempty(self, test_db_session: Session):
        """Topic constraints: subject must be 'OS' or 'DBMS'; code/name must be non-empty."""
        # Invalid subject
        bad_topic = Topic(
            code="NET_TOPIC",
            name="Computer Networks",
            subject="NETWORKS",  # rejected
        )
        test_db_session.add(bad_topic)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()

        # Blank code
        blank_code = Topic(
            code="   ",
            name="Blank Code Topic",
            subject="OS",
        )
        test_db_session.add(blank_code)
        with pytest.raises(IntegrityError):
            test_db_session.commit()
        test_db_session.rollback()


class TestTopicAPI:
    def test_get_topics_unauthenticated_rejected(self, client: TestClient):
        """Unauthenticated requests must be rejected with 401."""
        resp = client.get("/api/v1/topics")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_topics_authenticated_returns_active_topics(
        self, client: TestClient, test_db_session: Session
    ):
        """Authenticated user receives the list of active taxonomy topics."""
        seed_taxonomy_topics(test_db_session)
        user = create_test_user(test_db_session, role="STUDENT")
        cookies, headers = auth_cookies_and_headers(user)

        resp = client.get("/api/v1/topics", cookies=cookies, headers=headers)
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert len(data) == 8
        first = data[0]
        assert "id" in first
        assert "code" in first
        assert "name" in first
        assert "subject" in first
