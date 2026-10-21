from fastapi import APIRouter

from app.api.v1.endpoints import auth, exams, health, questions, topics

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(topics.router, tags=["topics"])
api_router.include_router(questions.router, tags=["questions"])
api_router.include_router(exams.router, tags=["exams"])
