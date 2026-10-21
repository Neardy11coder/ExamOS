"""
Topic taxonomy API routes.

GET /topics — list active taxonomy topics
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.topic import TopicRead
from app.services.topic_service import list_topics

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get(
    "",
    response_model=list[TopicRead],
    summary="List active taxonomy topics",
)
def get_topics(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[TopicRead]:
    """
    Returns list of active topics in the taxonomy.
    Requires authentication.
    """
    topics = list_topics(db, active_only=True)
    return [TopicRead.model_validate(t) for t in topics]
