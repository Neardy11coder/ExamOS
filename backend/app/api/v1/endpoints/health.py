import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def get_health(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Check the health of the FastAPI service and verify PostgreSQL reachability.
    """
    try:
        result = db.execute(text("SELECT 1")).scalar()
        if result != 1:
            logger.warning("Database health check returned unexpected scalar: %s", result)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database service unavailable",
            )
        db_status = "connected"
    except HTTPException:
        raise
    except Exception as exc:
        exc_type = type(exc).__name__
        logger.warning(
            "Database health check failed [diagnostic_code=DB_HEALTH_UNAVAILABLE, exception_type=%s]",
            exc_type,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database service unavailable",
        ) from None

    return HealthResponse(
        status="ok",
        app_env=settings.APP_ENV,
        database=db_status,
    )
