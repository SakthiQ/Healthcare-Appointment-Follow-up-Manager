import pytest
from app.config import settings
from app.exceptions import ForbiddenError
from app.dependencies import check_resource_ownership
from models.user import User, UserRole


def test_successful_patient_registration(client):
    """Test successful patient registration."""
    payload = {
        "email": "newpatient@example.com",
        "password": "securepassword123",
        "full_name": "New Patient",
        "role": "PATIENT"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newpatient@example.com"
    assert data["role"] == "PATIENT"
    assert "password" not in data
    assert "password_hash" not in data


def test_successful_doctor_registration(client):
    """Test successful doctor registration with specialization."""
    payload = {
        "email": "drsmith@example.com",
        "password": "doctorpassword123",
        "full_name": "Dr. Smith",
        "role": "DOCTOR",
        "specialization": "Neurology"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "DOCTOR"


def test_privileged_self_registration_rejected_by_default(client):
    """
    Security regression test (Phase 13 audit finding): without explicit
    opt-in, POST /auth/register must refuse to create anything other than a
    PATIENT account. The test suite globally sets
    ALLOW_PRIVILEGED_SELF_REGISTRATION=True (see conftest.py) so its own
    fixtures can bootstrap admin/doctor users, so this test flips it back to
    the secure default to prove that default actually holds — otherwise the
    whole suite running with the flag on could mask a real vulnerability.
    """
    original = settings.ALLOW_PRIVILEGED_SELF_REGISTRATION
    settings.ALLOW_PRIVILEGED_SELF_REGISTRATION = False
    try:
        r = client.post("/api/v1/auth/register", json={
            "email": "attacker_admin@example.com", "password": "password123",
            "full_name": "Attacker", "role": "ADMIN",
        })
        assert r.status_code == 403
        assert r.json()["error_code"] == "FORBIDDEN"

        r2 = client.post("/api/v1/auth/register", json={
            "email": "attacker_doctor@example.com", "password": "password123",
            "full_name": "Attacker", "role": "DOCTOR", "specialization": "Cardiology",
        })
        assert r2.status_code == 403

        # PATIENT self-registration must remain unaffected.
        r3 = client.post("/api/v1/auth/register", json={
            "email": "genuine_patient@example.com", "password": "password123",
            "full_name": "Genuine Patient", "role": "PATIENT",
        })
        assert r3.status_code == 201
    finally:
        settings.ALLOW_PRIVILEGED_SELF_REGISTRATION = original


def test_duplicate_registration_fails(client):
    """Test registering with duplicate email returns 409 Conflict."""
    payload = {
        "email": "duplicate@example.com",
        "password": "password123",
        "full_name": "User One"
    }
    r1 = client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201

    r2 = client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409
    assert r2.json()["error_code"] == "CONFLICT"


def test_successful_login(client):
    """Test successful login returns valid JWT access token."""
    reg = client.post("/api/v1/auth/register", json={
        "email": "loginuser@example.com",
        "password": "loginpassword123",
        "full_name": "Login User"
    })
    assert reg.status_code == 201

    login_resp = client.post("/api/v1/auth/login", json={
        "email": "loginuser@example.com",
        "password": "loginpassword123"
    })
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "loginuser@example.com"


def test_invalid_login_credentials(client):
    """Test login with wrong password or unknown email fails with 401."""
    client.post("/api/v1/auth/register", json={
        "email": "registered@example.com",
        "password": "correctpassword"
    })

    # Wrong password
    r1 = client.post("/api/v1/auth/login", json={
        "email": "registered@example.com",
        "password": "wrongpassword"
    })
    assert r1.status_code == 401
    assert r1.json()["error_code"] == "UNAUTHORIZED"

    # Nonexistent user
    r2 = client.post("/api/v1/auth/login", json={
        "email": "unknown@example.com",
        "password": "somepassword"
    })
    assert r2.status_code == 401


def test_authenticated_me_endpoint(client):
    """Test accessing /auth/me with valid Bearer token."""
    client.post("/api/v1/auth/register", json={
        "email": "meuser@example.com",
        "password": "mepassword123",
        "full_name": "Me User"
    })

    token = client.post("/api/v1/auth/login", json={
        "email": "meuser@example.com",
        "password": "mepassword123"
    }).json()["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get("/api/v1/auth/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "meuser@example.com"


def test_unauthenticated_access_rejected(client):
    """Test accessing protected route without token returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_expired_token_rejected(client):
    """
    Red-team scenario: a syntactically valid, correctly-signed JWT whose exp
    claim has already passed must be rejected, not just a missing/garbled
    token (test_unauthenticated_access_rejected / test_invalid_login_credentials
    cover those, but neither exercises the ExpiredSignatureError branch in
    app/core/security.py::decode_access_token).
    """
    from datetime import timedelta
    from app.core.security import create_access_token

    client.post("/api/v1/auth/register", json={
        "email": "expiring@example.com", "password": "password123",
        "full_name": "Expiring User", "role": "PATIENT",
    })

    expired_token = create_access_token(
        {"sub": "irrelevant-id", "email": "expiring@example.com", "role": "PATIENT"},
        expires_delta=timedelta(seconds=-1),
    )

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert r.status_code == 401
    assert r.json()["error_code"] == "UNAUTHORIZED"
    assert "expired" in r.json()["detail"].lower()

    # A garbled/tampered token (wrong signature) must be rejected too.
    r2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}tampered"})
    assert r2.status_code == 401


def test_role_based_authorization_restrictions(client):
    """Test server-side RBAC role restrictions for Patient, Doctor, and Admin."""
    # 1. Register Patient
    client.post("/api/v1/auth/register", json={
        "email": "p_role@example.com", "password": "password123", "full_name": "P Role", "role": "PATIENT"
    })
    token_p = client.post("/api/v1/auth/login", json={"email": "p_role@example.com", "password": "password123"}).json()["access_token"]
    headers_p = {"Authorization": f"Bearer {token_p}"}

    # Patient accessing patient endpoint -> OK
    assert client.get("/api/v1/auth/patient-only", headers=headers_p).status_code == 200
    # Patient accessing doctor endpoint -> 403 Forbidden
    assert client.get("/api/v1/auth/doctor-only", headers=headers_p).status_code == 403
    # Patient accessing admin endpoint -> 403 Forbidden
    assert client.get("/api/v1/auth/admin-only", headers=headers_p).status_code == 403

    # 2. Register Doctor
    client.post("/api/v1/auth/register", json={
        "email": "d_role@example.com", "password": "password123", "full_name": "D Role", "role": "DOCTOR", "specialization": "Pediatrics"
    })
    token_d = client.post("/api/v1/auth/login", json={"email": "d_role@example.com", "password": "password123"}).json()["access_token"]
    headers_d = {"Authorization": f"Bearer {token_d}"}

    # Doctor accessing doctor endpoint -> OK
    assert client.get("/api/v1/auth/doctor-only", headers=headers_d).status_code == 200
    # Doctor accessing admin endpoint -> 403 Forbidden
    assert client.get("/api/v1/auth/admin-only", headers=headers_d).status_code == 403

    # 3. Register Admin
    client.post("/api/v1/auth/register", json={
        "email": "a_role@example.com", "password": "password123", "full_name": "A Role", "role": "ADMIN"
    })
    token_a = client.post("/api/v1/auth/login", json={"email": "a_role@example.com", "password": "password123"}).json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Admin accessing admin endpoint -> OK
    assert client.get("/api/v1/auth/admin-only", headers=headers_a).status_code == 200



def test_cross_user_resource_access_ownership_check():
    """Test ownership check helper enforcing user-level data isolation."""
    patient1 = User(id="user_111", email="u1@example.com", role=UserRole.PATIENT)
    admin = User(id="admin_999", email="admin@example.com", role=UserRole.ADMIN)

    # Same user -> OK
    check_resource_ownership(patient1, "user_111")

    # Admin -> OK for any user resource
    check_resource_ownership(admin, "user_111")

    # Different patient -> raises ForbiddenError
    with pytest.raises(ForbiddenError):
        check_resource_ownership(patient1, "user_222")
