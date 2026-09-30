import os
from typing import Optional
from pydantic import Field, field_validator
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseSettings  # type: ignore


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""
    
    PROJECT_NAME: str = "Healthcare Appointment & Follow-up Manager"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    DEMO_MODE: bool = True

    # Per-integration overrides of DEMO_MODE. Unset (None) follows DEMO_MODE;
    # set one to False to use the real provider for just that integration,
    # e.g. a real LLM while email and calendar stay mocked.
    AI_DEMO_MODE: Optional[bool] = None
    EMAIL_DEMO_MODE: Optional[bool] = None
    CALENDAR_DEMO_MODE: Optional[bool] = None
    
    DATABASE_URL: str = "sqlite:///./healthcare_dev.db"
    
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # LLM provider (used only when DEMO_MODE is False; MockAIProvider requires none of this)
    AI_PROVIDER_API_KEY: Optional[str] = None
    AI_PROVIDER_BASE_URL: str = "https://api.openai.com/v1"
    AI_PROVIDER_MODEL: str = "gpt-4o-mini"
    AI_PROVIDER_TIMEOUT_SECONDS: float = 15.0

    # Email provider (Phase 9). Only used when DEMO_MODE is False; MockEmailProvider
    # requires none of this. Any SMTP-compatible provider (SendGrid, Mailgun, etc.
    # all offer SMTP relay) works without code changes.
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_USE_TLS: bool = True
    SMTP_TIMEOUT_SECONDS: float = 10.0
    EMAIL_FROM_ADDRESS: str = "no-reply@healthcare-app.local"

    NOTIFICATION_MAX_ATTEMPTS: int = 5

    # Google Calendar / OAuth 2.0 (Phase 10). Only used when DEMO_MODE is False;
    # MockCalendarProvider requires none of this. Never hardcode these — the
    # refresh token is obtained once via the OAuth consent flow (see README).
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REFRESH_TOKEN: Optional[str] = None
    GOOGLE_TOKEN_URI: str = "https://oauth2.googleapis.com/token"
    GOOGLE_CALENDAR_API_BASE_URL: str = "https://www.googleapis.com/calendar/v3"
    GOOGLE_CALENDAR_ID: str = "primary"
    GOOGLE_CALENDAR_TIMEOUT_SECONDS: float = 10.0

    CALENDAR_MAX_ATTEMPTS: int = 5

    # SECURITY: self-registration through POST /auth/register must only ever
    # create PATIENT accounts by default — DOCTOR accounts are created by an
    # admin (POST /admin/doctors) and ADMIN accounts have no legitimate
    # self-service path. This flag exists solely so the test suite can
    # bootstrap admin/doctor fixtures without a separate seeding mechanism;
    # it must stay False in any real deployment. See README "Creating the
    # first admin account".
    ALLOW_PRIVILEGED_SELF_REGISTRATION: bool = False

    # Comma-separated list of origins allowed to call the API cross-origin
    # (the deployed frontend's origin(s) in production). Defaults cover local
    # Vite dev only — set explicitly for any hosted deployment.
    CORS_ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("AI_DEMO_MODE", "EMAIL_DEMO_MODE", "CALENDAR_DEMO_MODE", mode="before")
    @classmethod
    def _blank_override_means_unset(cls, value):
        # An empty env var (e.g. AI_DEMO_MODE="") means "follow DEMO_MODE".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def ai_demo_mode(self) -> bool:
        return self.DEMO_MODE if self.AI_DEMO_MODE is None else self.AI_DEMO_MODE

    @property
    def email_demo_mode(self) -> bool:
        return self.DEMO_MODE if self.EMAIL_DEMO_MODE is None else self.EMAIL_DEMO_MODE

    @property
    def calendar_demo_mode(self) -> bool:
        return self.DEMO_MODE if self.CALENDAR_DEMO_MODE is None else self.CALENDAR_DEMO_MODE

    @property
    def cors_allowed_origins_list(self) -> list:
        return [o.strip() for o in self.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]

    try:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore"
        )
    except NameError:
        class Config:
            env_file = ".env"
            extra = "ignore"


settings = Settings()
