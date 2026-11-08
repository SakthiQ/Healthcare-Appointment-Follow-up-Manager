import os
import re
from typing import Optional
from pydantic import Field, field_validator, model_validator
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseSettings  # type: ignore


# The well-known development signing key. Anyone can read it in the repo, so a
# production deployment that still uses it lets anyone forge any user's token.
DEFAULT_SECRET_KEY = "dev-secret-key-change-in-production"


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
    
    SECRET_KEY: str = DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Cookie sessions (opt-in). Off: the access token is returned in the login response
    # and sent as a Bearer header, which the frontend keeps in localStorage, where any
    # script injected into the page can read it. On: the token travels only in an
    # httpOnly cookie that scripts cannot read, and the login response body carries no
    # token. Needs the frontend and the API on the SAME SITE (e.g. app.example.com and
    # api.example.com) so a SameSite cookie is sent; the frontend must be built with
    # VITE_AUTH_COOKIES=true. Bearer tokens keep working either way (API clients, tests).
    AUTH_COOKIE_MODE: bool = False
    AUTH_COOKIE_NAME: str = "healthcare_session"
    AUTH_COOKIE_SECURE: bool = True      # set False only for plain-http local development
    AUTH_COOKIE_SAMESITE: str = "lax"    # "lax" or "strict"

    # Login throttling, per (email, client IP): after this many consecutive failures
    # the pair is locked out (HTTP 429) for LOGIN_LOCKOUT_MINUTES. Keyed on the IP as
    # well as the email so a stranger can't lock a real user out of their own account.
    LOGIN_MAX_FAILED_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Cap on AI summaries generated per appointment and type (successes and
    # failures both count), so repeated clicks can't run up the LLM bill.
    AI_MAX_SUMMARIES_PER_APPOINTMENT: int = 10

    # When set, a doctor cannot record a consultation (which marks the appointment
    # COMPLETED and schedules medication reminders) more than this many minutes before
    # the appointment starts. Unset = no check, which the demo flow needs: it books a
    # future slot and consults straight away. A real clinic should set it (e.g. 15).
    CONSULTATION_EARLY_SUBMIT_MINUTES: Optional[int] = None

    # LLM provider (used only when AI demo mode is off, i.e. AI_DEMO_MODE=False or, if
    # that is unset, DEMO_MODE=False; MockAIProvider requires none of this)
    AI_PROVIDER_API_KEY: Optional[str] = None
    AI_PROVIDER_BASE_URL: str = "https://api.openai.com/v1"
    AI_PROVIDER_MODEL: str = "gpt-4o-mini"
    AI_PROVIDER_TIMEOUT_SECONDS: float = 15.0

    # Email provider (Phase 9). Only used when email demo mode is off (EMAIL_DEMO_MODE=False
    # or, if unset, DEMO_MODE=False); MockEmailProvider requires none of this. Any SMTP-compatible provider (SendGrid, Mailgun, etc.
    # all offer SMTP relay) works without code changes.
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_USE_TLS: bool = True
    SMTP_TIMEOUT_SECONDS: float = 10.0
    EMAIL_FROM_ADDRESS: str = "no-reply@healthcare-app.local"

    NOTIFICATION_MAX_ATTEMPTS: int = 5
    # A job still PROCESSING after this long had its worker die mid-batch, so it
    # is put back in the queue. Must comfortably exceed the time to send a batch.
    NOTIFICATION_PROCESSING_TIMEOUT_MINUTES: int = 30

    # Google Calendar / OAuth 2.0 (Phase 10). Only used when calendar demo mode is off
    # (CALENDAR_DEMO_MODE=False or, if unset, DEMO_MODE=False);
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

    # Run the notification and calendar workers on background threads inside the
    # web process. Off by default (tests, local dev, and deployments that run
    # `python -m workers.<name>` as separate processes); the Render blueprint
    # turns it on because that service type has no separate worker process.
    RUN_WORKERS_IN_PROCESS: bool = False
    WORKER_POLL_INTERVAL_SECONDS: float = 30.0

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

    # Optional regex for origins that can't be listed up front, such as Vercel
    # preview deployments (a new URL per branch). Empty disables it.
    CORS_ALLOWED_ORIGIN_REGEX: Optional[str] = None

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Several hosts (Render, Heroku) hand out "postgres://" URLs, a scheme
        # SQLAlchemy 2.x no longer accepts.
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://"):]
        # Name the driver. A bare "postgresql://" means psycopg2 on SQLAlchemy 2.0 but
        # psycopg (v3) on 2.1, and requirements.txt allows both versions while shipping
        # only psycopg2, so a fresh install would otherwise crash at startup.
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg2://" + value[len("postgresql://"):]
        return value

    @model_validator(mode="after")
    def _refuse_default_secret_key_in_production(self):
        # Fail at startup rather than quietly run with a publicly known JWT key.
        if self.ENVIRONMENT.strip().lower() in ("production", "prod") and self.SECRET_KEY == DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is still the built-in development key while ENVIRONMENT=production. "
                "Set SECRET_KEY to a long random value (e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
            )
        return self

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

    def is_cors_origin_allowed(self, origin: str) -> bool:
        """Same rule CORSMiddleware applies to the allow-list and regex."""
        if origin in self.cors_allowed_origins_list:
            return True
        regex = self.CORS_ALLOWED_ORIGIN_REGEX
        return bool(regex) and re.fullmatch(regex, origin) is not None

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
