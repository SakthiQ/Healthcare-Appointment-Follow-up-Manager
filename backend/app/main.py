from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.core.request_context import RequestContextMiddleware
from app.logging_config import setup_logging
from app.exceptions import AppException, app_exception_handler, global_exception_handler
from app.api import api_router
from app.api.health import router as health_router

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    runner = None
    if settings.RUN_WORKERS_IN_PROCESS:
        # Imported here so the web app doesn't load the worker modules unless asked.
        from workers.runner import start_background_workers
        runner = start_background_workers()
    yield
    if runner is not None:
        runner.stop()


def create_app() -> FastAPI:
    """Factory function to build and configure the FastAPI application."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
        lifespan=lifespan
    )

    # CORS configuration. Auth is Bearer-token-based (Authorization header) unless
    # AUTH_COOKIE_MODE is on, so credentials are only allowed then. Credentials combined
    # with a wildcard origin would be a real misconfiguration (any site could then make
    # credentialed cross-origin requests), so origins are restricted to an explicit
    # allow-list instead (CORS_ALLOWED_ORIGINS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_origin_regex=settings.CORS_ALLOWED_ORIGIN_REGEX or None,
        allow_credentials=settings.AUTH_COOKIE_MODE,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Makes the client IP available to services (the audit log records it).
    app.add_middleware(RequestContextMiddleware)

    # Register custom exception handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    # Include API routes
    app.include_router(health_router)  # Root level /health
    app.include_router(api_router, prefix=settings.API_V1_STR)  # /api/v1 prefix

    return app


app = create_app()
