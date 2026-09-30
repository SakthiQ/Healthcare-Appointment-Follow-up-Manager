import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.core.security import verify_password
from app.main import create_app
from models.user import UserRole
from scripts.create_admin import CreateAdminError, create_admin


def test_postgres_scheme_normalized_for_sqlalchemy():
    s = Settings(DATABASE_URL="postgres://u:p@host:5432/db?sslmode=require")
    assert s.DATABASE_URL == "postgresql://u:p@host:5432/db?sslmode=require"
    assert Settings(DATABASE_URL="postgresql://u:p@host/db").DATABASE_URL == "postgresql://u:p@host/db"


def _preflight(client, origin):
    return client.options(
        "/api/v1/auth/login",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


def test_cors_origin_regex_allows_matching_preview_origins(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGIN_REGEX", r"^https://myapp-[a-z0-9-]+\.vercel\.app$")
    client = TestClient(create_app())

    allowed = _preflight(client, "https://myapp-git-feature-team.vercel.app")
    assert allowed.headers.get("access-control-allow-origin") == "https://myapp-git-feature-team.vercel.app"
    assert _preflight(client, "https://app.example.com").headers.get("access-control-allow-origin") == "https://app.example.com"
    assert "access-control-allow-origin" not in _preflight(client, "https://evil.example.com").headers


def test_cors_without_regex_only_allows_listed_origins(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGIN_REGEX", None)
    client = TestClient(create_app())
    assert "access-control-allow-origin" not in _preflight(client, "https://myapp-git-x.vercel.app").headers


def test_create_admin_script_creates_admin(db_session):
    user = create_admin(db_session, "bootstrap_admin@example.com", "Bootstrap Admin", "long-enough-pw")
    assert user.role == UserRole.ADMIN
    assert verify_password("long-enough-pw", user.password_hash)

    with pytest.raises(CreateAdminError):
        create_admin(db_session, "bootstrap_admin@example.com", "Again", "long-enough-pw")


def test_create_admin_script_rejects_short_password(db_session):
    with pytest.raises(CreateAdminError):
        create_admin(db_session, "short_pw_admin@example.com", "Admin", "short")
