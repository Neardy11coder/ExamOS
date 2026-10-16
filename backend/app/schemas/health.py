from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Schema for /api/v1/health response."""
    status: str
    app_env: str
    database: str
