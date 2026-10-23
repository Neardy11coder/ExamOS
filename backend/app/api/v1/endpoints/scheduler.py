"""
OS CPU Scheduling Simulator API routes (M2-OS-UI-1 / docs/04_API_CONTRACT §6).

Restricted to FACULTY_ADMIN. Performs educational simulation over abstract jobs.
Does not read or modify examination tables.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import require_faculty, validate_csrf
from app.models.user import User
from app.schemas.scheduler import ScheduleResult, SchedulerRunRequest
from app.services.scheduler_service import SchedulerValidationError, simulate

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.post(
    "/simulate",
    response_model=ScheduleResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(validate_csrf)],
)
def run_simulation(
    request: SchedulerRunRequest,
    current_user: Annotated[User, Depends(require_faculty)],
) -> ScheduleResult:
    """Run educational CPU scheduling simulation.

    Faculty/admin only.
    Validates job inputs, quantum, and algorithm.
    Returns per-job metrics, timeline segments, and summary utilization statistics.
    """
    try:
        return simulate(
            algorithm=request.algorithm,
            jobs=request.jobs,
            quantum=request.quantum,
        )
    except SchedulerValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "SCHEDULER_VALIDATION_ERROR",
                    "message": e.message,
                    "field": e.field,
                }
            },
        )
