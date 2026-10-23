from fastapi import APIRouter

from app.api.v1.endpoints import (
    attempts,
    auth,
    database_lab,
    exams,
    health,
    ml,
    questions,
    scheduler,
    topics,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(topics.router, tags=["topics"])
api_router.include_router(questions.router, tags=["questions"])
api_router.include_router(exams.router, tags=["exams"])
api_router.include_router(attempts.router, tags=["attempts"])
api_router.include_router(scheduler.router, tags=["scheduler"])
api_router.include_router(database_lab.router, tags=["database-lab"])
api_router.include_router(ml.router, tags=["ml"])
