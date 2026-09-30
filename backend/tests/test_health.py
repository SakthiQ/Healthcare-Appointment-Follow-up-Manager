def test_health_endpoint(client):
    """Test root level /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert "version" in data
    assert "environment" in data
    assert "database" in data
    assert "demo_mode" in data
    assert data["ai_provider"] in ("mock", "real")
    assert data["email_provider"] in ("mock", "real")
    assert data["calendar_provider"] in ("mock", "real")


def test_health_reports_each_integrations_effective_provider(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    monkeypatch.setattr(settings, "AI_DEMO_MODE", False)
    monkeypatch.setattr(settings, "EMAIL_DEMO_MODE", None)
    monkeypatch.setattr(settings, "CALENDAR_DEMO_MODE", False)
    data = client.get("/health").json()
    assert data["ai_provider"] == "real"
    assert data["email_provider"] == "mock"  # unset follows DEMO_MODE
    assert data["calendar_provider"] == "real"

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "AI_DEMO_MODE", True)
    data = client.get("/health").json()
    assert data["ai_provider"] == "mock"
    assert data["email_provider"] == "real"


def test_health_endpoint_v1(client):
    """Test API v1 /api/v1/health endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")


def test_openapi_docs(client):
    """Test OpenAPI JSON specification endpoint."""
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "openapi" in schema
    assert "paths" in schema
    assert "/health" in schema["paths"]
