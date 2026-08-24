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
