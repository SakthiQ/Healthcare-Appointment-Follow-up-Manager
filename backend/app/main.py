from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.logging_config import setup_logging
from app.exceptions import AppException, app_exception_handler, global_exception_handler
from app.api import api_router
from app.api.health import router as health_router

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    # Startup actions (e.g. log initialization)
    yield
    # Shutdown actions


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

    # CORS configuration. Auth is Bearer-token-based (Authorization header),
    # never cookies, so allow_credentials stays False; combined with a
    # wildcard origin that is a real misconfiguration (any site could then
    # make credentialed cross-origin requests), so origins are restricted to
    # an explicit allow-list instead (CORS_ALLOWED_ORIGINS).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register custom exception handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, global_exception_handler)

    # Include API routes
    app.include_router(health_router)  # Root level /health
    app.include_router(api_router, prefix=settings.API_V1_STR)  # /api/v1 prefix

    return app


app = create_app()
