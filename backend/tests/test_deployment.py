import pytest
from fastapi.testclient import TestClient

from app.config import Settings, settings
from app.core.security import verify_password
from app.database import get_db
from app.main import create_app
from models.user import UserRole
from scripts.create_admin import CreateAdminError, create_admin
from scripts import seed_demo


def test_postgres_scheme_normalized_for_sqlalchemy():
    s = Settings(DATABASE_URL="postgres://u:p@host:5432/db?sslmode=require")
    assert s.DATABASE_URL == "postgresql+psycopg2://u:p@host:5432/db?sslmode=require"
    assert Settings(DATABASE_URL="postgresql://u:p@host/db").DATABASE_URL == "postgresql+psycopg2://u:p@host/db"


def test_database_driver_is_named_explicitly_and_other_urls_are_left_alone():
    """A bare postgresql:// is psycopg2 on SQLAlchemy 2.0 but psycopg (v3) on 2.1, which
    is not installed; an explicit driver or a non-Postgres URL must pass through."""
    assert Settings(DATABASE_URL="postgresql+psycopg://u@h/d").DATABASE_URL == "postgresql+psycopg://u@h/d"
    assert Settings(DATABASE_URL="sqlite:///./x.db").DATABASE_URL == "sqlite:///./x.db"


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


def test_unhandled_error_response_keeps_cors_headers(monkeypatch):
    """Otherwise the browser blocks the 500 and the frontend reports a network failure."""
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGIN_REGEX", r"^https://myapp-[a-z0-9-]+\.vercel\.app$")

    def broken_db():
        raise RuntimeError("database down")

    app = create_app()
    app.dependency_overrides[get_db] = broken_db
    client = TestClient(app, raise_server_exceptions=False)

    def error_response(origin):
        response = client.get("/api/v1/doctors", headers={"Origin": origin})
        assert response.status_code == 500
        return response

    assert error_response("https://app.example.com").headers.get("access-control-allow-origin") == "https://app.example.com"
    assert error_response("https://myapp-git-x.vercel.app").headers.get("access-control-allow-origin") == "https://myapp-git-x.vercel.app"
    assert "access-control-allow-origin" not in error_response("https://evil.example.com").headers


def test_create_admin_script_creates_admin(db_session):
    user = create_admin(db_session, "bootstrap_admin@example.com", "Bootstrap Admin", "long-enough-pw")
    assert user.role == UserRole.ADMIN
    assert verify_password("long-enough-pw", user.password_hash)

    with pytest.raises(CreateAdminError):
        create_admin(db_session, "bootstrap_admin@example.com", "Again", "long-enough-pw")


def test_create_admin_script_rejects_short_password(db_session):
    with pytest.raises(CreateAdminError):
        create_admin(db_session, "short_pw_admin@example.com", "Admin", "short")


def test_seed_demo_creates_one_account_per_role_and_is_idempotent(client, db_session):
    first = seed_demo.seed(db_session)
    assert [line.split()[0] for line in first] == ["created", "created", "created"]
    second = seed_demo.seed(db_session)
    assert [line.split()[0] for line in second] == ["exists", "exists", "exists"]

    for email, role in [
        (seed_demo.ADMIN_EMAIL, "ADMIN"),
        (seed_demo.DOCTOR_EMAIL, "DOCTOR"),
        (seed_demo.PATIENT_EMAIL, "PATIENT"),
    ]:
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": seed_demo.DEMO_PASSWORD})
        assert resp.status_code == 200, (email, resp.text)
        me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
        assert me.json()["role"] == role

    # The doctor is bookable: listed publicly, with Monday-Friday working hours.
    doctors = client.get("/api/v1/doctors").json()
    demo = [d for d in doctors if d["full_name"] == "Dr Demo"]
    assert len(demo) == 1
    hours = client.get(f"/api/v1/doctors/{demo[0]['id']}/schedule").json()
    assert sorted(h["day_of_week"] for h in hours) == [0, 1, 2, 3, 4]


@pytest.mark.parametrize("environment, demo_mode", [("production", True), ("Production", True), ("development", False)])
def test_seed_demo_refuses_outside_demo_mode_or_in_production(environment, demo_mode):
    with pytest.raises(seed_demo.SeedRefused):
        seed_demo.check_allowed(environment, demo_mode)


def test_seed_demo_allowed_in_local_demo_mode():
    seed_demo.check_allowed("development", True)
