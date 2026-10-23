"""
Automated tests for ML topic suggestion service and API (M4-ML-1).

Requirements covered:
- docs/04_API_CONTRACT.md §8 (POST /ml/topic-suggestions)
- docs/07_AI_ML_DESIGN.md §5 (graceful fallback, confidence threshold)
- Faculty-only access enforcement
- CSRF token required for POST
- available=True when model present and confidence >= threshold
- available=False with reason when confidence < threshold
- available=False with reason when model artifact missing
- Classifier errors do not propagate as HTTP errors
"""

from __future__ import annotations

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services import ml_service
from app.services.ml_service import (
    REASON_LOW_CONFIDENCE,
    REASON_MODEL_ERROR,
    REASON_MODEL_NOT_FOUND,
    reset_pipeline_cache,
    suggest_topic,
)
from tests.helpers import auth_cookies_and_headers, create_test_user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_ml_cache():
    """Reset the ML pipeline cache before/after each test for isolation."""
    reset_pipeline_cache()
    yield
    reset_pipeline_cache()


def _make_fake_pipeline(proba_map: dict[str, float]):
    """
    Build a minimal mock that mimics the sklearn Pipeline interface:
    .classes_ and .predict_proba().
    """
    classes = list(proba_map.keys())
    proba_row = [proba_map[c] for c in classes]

    pipeline = MagicMock()
    pipeline.classes_ = classes
    pipeline.predict_proba.return_value = [proba_row]
    return pipeline


# ---------------------------------------------------------------------------
# Unit tests — suggest_topic() service function
# ---------------------------------------------------------------------------

class TestSuggestTopicService:
    def test_returns_model_not_found_when_artifact_missing(self):
        """suggest_topic returns available=False/MODEL_NOT_FOUND when path not found."""
        with patch("app.services.ml_service.settings") as mock_settings:
            mock_settings.ML_MODEL_PATH = "/nonexistent/path/classifier.joblib"
            mock_settings.ML_CONFIDENCE_THRESHOLD = 0.55
            result = suggest_topic("What is a deadlock?")

        assert result.available is False
        assert result.reason == REASON_MODEL_NOT_FOUND
        assert result.suggestion is None

    def test_returns_suggestion_when_confidence_above_threshold(self):
        """suggest_topic returns available=True/suggestion when confidence >= threshold."""
        fake_pipeline = _make_fake_pipeline({
            "DB_TRANSACTIONS": 0.80,
            "OS_SYNC": 0.10,
            "DB_INDEXING": 0.05,
            "OS_PROCESS": 0.02,
            "OS_SCHEDULING": 0.01,
            "DB_NORMALIZATION": 0.01,
            "DB_SQL_JOINS": 0.005,
            "OS_MEMORY_FILES": 0.005,
        })

        with (
            patch("app.services.ml_service._load_pipeline", return_value=fake_pipeline),
            patch("app.services.ml_service.settings") as mock_settings,
        ):
            mock_settings.ML_CONFIDENCE_THRESHOLD = 0.55
            result = suggest_topic(
                "Which property makes a transaction all-or-nothing?",
                options=["Atomicity", "Durability", "Isolation", "Normalization"],
            )

        assert result.available is True
        assert result.suggestion is not None
        assert result.suggestion.topic_code == "DB_TRANSACTIONS"
        assert result.suggestion.topic_name == "Transactions and Concurrency"
        assert result.suggestion.confidence >= 0.55
        assert result.suggestion.threshold == 0.55

    def test_returns_low_confidence_when_below_threshold(self):
        """suggest_topic returns available=False/LOW_CONFIDENCE when max proba < threshold."""
        fake_pipeline = _make_fake_pipeline({
            "DB_TRANSACTIONS": 0.30,
            "OS_SYNC": 0.25,
            "DB_INDEXING": 0.20,
            "OS_PROCESS": 0.10,
            "OS_SCHEDULING": 0.05,
            "DB_NORMALIZATION": 0.04,
            "DB_SQL_JOINS": 0.04,
            "OS_MEMORY_FILES": 0.02,
        })

        with (
            patch("app.services.ml_service._load_pipeline", return_value=fake_pipeline),
            patch("app.services.ml_service.settings") as mock_settings,
        ):
            mock_settings.ML_CONFIDENCE_THRESHOLD = 0.55
            result = suggest_topic("A vague question with no strong topic signal")

        assert result.available is False
        assert result.reason == REASON_LOW_CONFIDENCE
        assert result.suggestion is None

    def test_returns_model_error_on_prediction_exception(self):
        """suggest_topic returns available=False/MODEL_ERROR when predict_proba raises."""
        fake_pipeline = MagicMock()
        fake_pipeline.classes_ = ["DB_TRANSACTIONS", "OS_SYNC"]
        fake_pipeline.predict_proba.side_effect = RuntimeError("BLAS error")

        with (
            patch("app.services.ml_service._load_pipeline", return_value=fake_pipeline),
            patch("app.services.ml_service.settings") as mock_settings,
        ):
            mock_settings.ML_CONFIDENCE_THRESHOLD = 0.55
            result = suggest_topic("Trigger error")

        assert result.available is False
        assert result.reason == REASON_MODEL_ERROR
        assert result.suggestion is None

    def test_prompt_only_input_accepted(self):
        """suggest_topic accepts prompt without options."""
        fake_pipeline = _make_fake_pipeline({
            "OS_SCHEDULING": 0.90,
            "OS_PROCESS": 0.05,
            "OS_SYNC": 0.02,
            "OS_MEMORY_FILES": 0.01,
            "DB_TRANSACTIONS": 0.01,
            "DB_INDEXING": 0.005,
            "DB_NORMALIZATION": 0.003,
            "DB_SQL_JOINS": 0.002,
        })

        with (
            patch("app.services.ml_service._load_pipeline", return_value=fake_pipeline),
            patch("app.services.ml_service.settings") as mock_settings,
        ):
            mock_settings.ML_CONFIDENCE_THRESHOLD = 0.55
            result = suggest_topic("Which algorithm uses a time quantum?")

        assert result.available is True
        assert result.suggestion.topic_code == "OS_SCHEDULING"
        assert result.suggestion.topic_name == "CPU Scheduling"

    def test_relative_model_path_resolution_independent_of_cwd(self, tmp_path):
        """A relative ML_MODEL_PATH resolves relative to the backend directory, not process CWD."""
        import os
        from pathlib import Path

        # Default relative model path
        backend_dir = Path(ml_service.__file__).resolve().parents[2]
        expected_artifact = (backend_dir / settings.ML_MODEL_PATH).resolve()

        # Execute from a different working directory (tmp_path)
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            reset_pipeline_cache()
            pipeline = ml_service._load_pipeline()
            # If the artifact exists in repository, it must load even when CWD is tmp_path
            if expected_artifact.is_file():
                assert pipeline is not None
                res = suggest_topic("Explain process synchronization")
                # Must return an inference result (suggestion or low confidence), NOT MODEL_NOT_FOUND
                assert res.reason != REASON_MODEL_NOT_FOUND
        finally:
            os.chdir(old_cwd)
            reset_pipeline_cache()


# ---------------------------------------------------------------------------
# Integration tests — POST /api/v1/ml/topic-suggestions
# ---------------------------------------------------------------------------

class TestMLTopicSuggestionAPI:
    URL = "/api/v1/ml/topic-suggestions"

    def _faculty_post(
        self,
        client: TestClient,
        db: Session,
        payload: dict,
    ):
        """Helper: create faculty user, build cookies+CSRF headers, POST payload."""
        faculty = create_test_user(db, role="FACULTY_ADMIN")
        cookies, headers = auth_cookies_and_headers(faculty)
        return client.post(self.URL, json=payload, cookies=cookies, headers=headers)

    def test_unauthenticated_returns_401(self, client: TestClient):
        resp = client.post(
            self.URL,
            json={"prompt": "What is FCFS?"},
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_student_role_returns_403(
        self, client: TestClient, test_db_session: Session
    ):
        student = create_test_user(test_db_session, role="STUDENT")
        cookies, headers = auth_cookies_and_headers(student)
        resp = client.post(
            self.URL,
            json={"prompt": "What is FCFS?"},
            cookies=cookies,
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_csrf_returns_403(
        self, client: TestClient, test_db_session: Session
    ):
        """Faculty user without CSRF header must be rejected."""
        from app.core.security import JWT_COOKIE_NAME, create_access_token

        faculty = create_test_user(test_db_session, role="FACULTY_ADMIN")
        token = create_access_token(str(faculty.id), faculty.role)
        resp = client.post(
            self.URL,
            json={"prompt": "Describe B-Tree indexing"},
            cookies={JWT_COOKIE_NAME: token},
            # No X-CSRF-Token header, no csrf_token cookie
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_blank_prompt_returns_422(
        self, client: TestClient, test_db_session: Session
    ):
        resp = self._faculty_post(client, test_db_session, {"prompt": "   "})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_empty_prompt_string_returns_422(
        self, client: TestClient, test_db_session: Session
    ):
        resp = self._faculty_post(client, test_db_session, {"prompt": ""})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_missing_prompt_returns_422(
        self, client: TestClient, test_db_session: Session
    ):
        resp = self._faculty_post(client, test_db_session, {"options": ["A", "B"]})
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_model_not_found_returns_200_unavailable(
        self, client: TestClient, test_db_session: Session
    ):
        """When artifact is missing the endpoint returns 200 with available=False."""
        with patch("app.services.ml_service._load_pipeline", return_value=None):
            reset_pipeline_cache()
            resp = self._faculty_post(
                client,
                test_db_session,
                {"prompt": "What is a race condition?"},
            )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["available"] is False
        assert body["reason"] in (REASON_MODEL_NOT_FOUND, REASON_MODEL_ERROR)
        assert body["suggestion"] is None

    def test_high_confidence_returns_200_with_suggestion(
        self, client: TestClient, test_db_session: Session
    ):
        """Faculty request with high-confidence mock returns a full suggestion."""
        fake_pipeline = _make_fake_pipeline({
            "DB_TRANSACTIONS": 0.85,
            "OS_SYNC": 0.08,
            "DB_INDEXING": 0.03,
            "OS_PROCESS": 0.01,
            "OS_SCHEDULING": 0.01,
            "DB_NORMALIZATION": 0.01,
            "DB_SQL_JOINS": 0.005,
            "OS_MEMORY_FILES": 0.005,
        })

        with (
            patch("app.services.ml_service._load_pipeline", return_value=fake_pipeline),
            patch.object(
                ml_service, "_pipeline_load_attempted", True
            ),
        ):
            ml_service._pipeline = fake_pipeline
            ml_service._pipeline_load_attempted = True
            resp = self._faculty_post(
                client,
                test_db_session,
                {
                    "prompt": "Which property guarantees atomicity in a transaction?",
                    "options": ["Commit", "Rollback", "ACID", "Isolation"],
                },
            )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["available"] is True
        s = body["suggestion"]
        assert s is not None
        assert s["topic_code"] == "DB_TRANSACTIONS"
        assert s["topic_name"] == "Transactions and Concurrency"
        assert 0.0 <= s["confidence"] <= 1.0
        assert s["threshold"] == pytest.approx(0.55, abs=0.01)

    def test_low_confidence_returns_200_unavailable(
        self, client: TestClient, test_db_session: Session
    ):
        """Low-confidence prediction returns available=False/LOW_CONFIDENCE, not an error."""
        fake_pipeline = _make_fake_pipeline({
            "DB_TRANSACTIONS": 0.20,
            "OS_SYNC": 0.18,
            "DB_INDEXING": 0.17,
            "OS_PROCESS": 0.15,
            "OS_SCHEDULING": 0.12,
            "DB_NORMALIZATION": 0.08,
            "DB_SQL_JOINS": 0.07,
            "OS_MEMORY_FILES": 0.03,
        })

        ml_service._pipeline = fake_pipeline
        ml_service._pipeline_load_attempted = True

        resp = self._faculty_post(
            client,
            test_db_session,
            {"prompt": "Ambiguous question with no clear topic signal at all"},
        )

        assert resp.status_code == status.HTTP_200_OK
        body = resp.json()
        assert body["available"] is False
        assert body["reason"] == REASON_LOW_CONFIDENCE

    def test_response_schema_never_leaks_artifact_path(
        self, client: TestClient, test_db_session: Session
    ):
        """Response body must never contain artifact path or training data."""
        fake_pipeline = _make_fake_pipeline(
            {"DB_INDEXING": 0.75, **{c: 0.04 for c in [
                "DB_TRANSACTIONS", "OS_SYNC", "OS_PROCESS",
                "OS_SCHEDULING", "DB_NORMALIZATION", "DB_SQL_JOINS", "OS_MEMORY_FILES",
            ]}}
        )

        ml_service._pipeline = fake_pipeline
        ml_service._pipeline_load_attempted = True

        resp = self._faculty_post(
            client,
            test_db_session,
            {"prompt": "How does a B-Tree index speed up range queries?"},
        )

        assert resp.status_code == status.HTTP_200_OK
        raw = resp.text
        assert "joblib" not in raw
        assert "artifacts" not in raw
        assert "topic_classifier" not in raw

    def test_extra_fields_in_request_body_rejected(
        self, client: TestClient, test_db_session: Session
    ):
        """Extra fields are rejected by the strict Pydantic schema."""
        resp = self._faculty_post(
            client,
            test_db_session,
            {"prompt": "What is paging?", "unknown_field": "should_fail"},
        )
        assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
