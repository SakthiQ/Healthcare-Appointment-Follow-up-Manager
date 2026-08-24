from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from app.config import settings, Settings
from app.database import check_db_connection
from app.dependencies import get_settings

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    demo_mode: bool


@router.get("/health", response_model=HealthResponse, status_code=status.HTTP_200_OK)
def health_check(current_settings: Settings = Depends(get_settings)):
    """Health check endpoint that reports application and database health."""
    db_connected = check_db_connection()
    return HealthResponse(
        status="ok" if db_connected else "degraded",
        version=current_settings.VERSION,
        environment=current_settings.ENVIRONMENT,
        database="connected" if db_connected else "disconnected",
        demo_mode=current_settings.DEMO_MODE
    )
