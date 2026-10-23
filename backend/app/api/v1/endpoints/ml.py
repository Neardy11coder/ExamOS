"""
ML topic suggestion endpoint (M4-ML-1).

POST /ml/topic-suggestions — Faculty/admin only.

docs/04_API_CONTRACT.md §8
docs/07_AI_ML_DESIGN.md
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import require_faculty, validate_csrf
from app.models.user import User
from app.schemas.ml import TopicSuggestionRequest, TopicSuggestionResponse
from app.services.ml_service import suggest_topic

router = APIRouter(prefix="/ml", tags=["ml"])


@router.post(
    "/topic-suggestions",
    response_model=TopicSuggestionResponse,
    summary="Suggest a taxonomy topic for a question (advisory, faculty only)",
)
def get_topic_suggestion(
    body: TopicSuggestionRequest,
    current_user: Annotated[User, Depends(require_faculty)],
    _csrf: Annotated[None, Depends(validate_csrf)],
) -> TopicSuggestionResponse:
    """
    Runs the local ML classifier on the supplied question prompt (and optional
    option texts) and returns an advisory topic suggestion.

    The endpoint NEVER returns a fatal error due to classifier absence or low
    confidence — it always returns a 200 JSON response with ``available`` set
    accordingly.  Faculty may accept, override, or ignore the suggestion.

    Requires: authenticated FACULTY_ADMIN role + valid CSRF token.
    """
    return suggest_topic(body.prompt, body.options)
