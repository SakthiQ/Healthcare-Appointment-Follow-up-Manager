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
