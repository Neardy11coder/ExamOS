from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.api import api_router
from app.core.config import Settings, settings


def create_application(settings_override: Settings | None = None) -> FastAPI:
    """
    Application factory for ExamOS FastAPI service.

    Architectural note on settings_override:
    The settings_override parameter serves as a test and configuration seam for
    application-level settings (such as docs_url, openapi_url, and CORS origins).
    Unless all dependent API routes and services are refactored to consume settings
    via FastAPI dependency injection (e.g. Depends(get_settings)), lower-level
    route endpoints (such as /health) access the authoritative module-level singleton
    `app.core.config.settings`. Do not rely on settings_override for multi-tenant or
    per-request settings mutations without a full dependency-injection refactoring.
    """
    app_settings = settings_override or settings
    is_prod = app_settings.is_production

    application = FastAPI(
        title="ExamOS API",
        version="0.1.0",
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/openapi.json",
    )

    # Configure CORS restricted to frontend origin
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[app_settings.FRONTEND_ORIGIN],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, exc: HTTPException):
        """Formats HTTPException responses to conform to API contract §1.2."""
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
        )

    # Mount API v1
    application.include_router(api_router, prefix="/api/v1")

    return application


app = create_application()
