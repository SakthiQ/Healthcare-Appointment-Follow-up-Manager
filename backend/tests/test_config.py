from app.config import Settings


def test_default_settings():
    """Test that default settings load correctly."""
    s = Settings()
    assert s.PROJECT_NAME == "Healthcare Appointment & Follow-up Manager"
    assert s.API_V1_STR == "/api/v1"
    assert isinstance(s.DEMO_MODE, bool)
    assert s.DATABASE_URL is not None


def test_settings_override(monkeypatch):
    """Test environment variable override of configuration settings."""
    monkeypatch.setenv("PROJECT_NAME", "Custom Healthcare System")
    monkeypatch.setenv("DEMO_MODE", "false")
    s = Settings()
    assert s.PROJECT_NAME == "Custom Healthcare System"
    assert s.DEMO_MODE is False


def test_integration_overrides_follow_demo_mode_when_unset():
    s = Settings(DEMO_MODE=True, AI_DEMO_MODE=None, EMAIL_DEMO_MODE=None, CALENDAR_DEMO_MODE=None)
    assert (s.ai_demo_mode, s.email_demo_mode, s.calendar_demo_mode) == (True, True, True)
    s = Settings(DEMO_MODE=False, AI_DEMO_MODE=None, EMAIL_DEMO_MODE=None, CALENDAR_DEMO_MODE=None)
    assert (s.ai_demo_mode, s.email_demo_mode, s.calendar_demo_mode) == (False, False, False)


def test_real_ai_can_be_enabled_alone(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("AI_DEMO_MODE", "false")
    monkeypatch.setenv("EMAIL_DEMO_MODE", "")
    monkeypatch.delenv("CALENDAR_DEMO_MODE", raising=False)
    s = Settings()
    assert s.ai_demo_mode is False
    assert s.email_demo_mode is True  # blank value means "follow DEMO_MODE"
    assert s.calendar_demo_mode is True


def test_provider_factories_respect_per_integration_switches(monkeypatch):
    from app.config import settings
    from providers.ai_provider import MockAIProvider, RealAIProvider, get_ai_provider
    from providers.calendar_provider import MockCalendarProvider, get_calendar_provider
    from providers.email_provider import MockEmailProvider, get_email_provider

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    monkeypatch.setattr(settings, "AI_DEMO_MODE", False)
    monkeypatch.setattr(settings, "EMAIL_DEMO_MODE", None)
    monkeypatch.setattr(settings, "CALENDAR_DEMO_MODE", None)
    assert isinstance(get_ai_provider(), RealAIProvider)
    assert isinstance(get_email_provider(), MockEmailProvider)
    assert isinstance(get_calendar_provider(), MockCalendarProvider)

    monkeypatch.setattr(settings, "AI_DEMO_MODE", None)
    assert isinstance(get_ai_provider(), MockAIProvider)


def test_default_secret_key_is_refused_in_production():
    import pytest
    from pydantic import ValidationError
    from app.config import DEFAULT_SECRET_KEY

    for env in ("production", "Production", " prod "):
        with pytest.raises(ValidationError, match="SECRET_KEY"):
            Settings(ENVIRONMENT=env, SECRET_KEY=DEFAULT_SECRET_KEY)


def test_default_secret_key_still_allowed_outside_production_and_custom_key_allowed_in_it():
    from app.config import DEFAULT_SECRET_KEY

    assert Settings(ENVIRONMENT="development", SECRET_KEY=DEFAULT_SECRET_KEY).SECRET_KEY == DEFAULT_SECRET_KEY
    assert Settings(ENVIRONMENT="production", SECRET_KEY="x" * 48).SECRET_KEY == "x" * 48
