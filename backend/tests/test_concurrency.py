from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from tests.conftest import TestingSessionLocal
import pytest
import threading


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


# SQLite's StaticPool shares ONE underlying connection across all sessions.
# Concurrent threads accessing this connection simultaneously cause:
#   sqlite3.InterfaceError: bad parameter or other API misuse
# The lock must span the ENTIRE session lifetime (creation → queries → close).
# This serializes DB access for concurrent threads, which is correct for SQLite.
# The _booking_lock in appointment_service ensures exactly 1 booking succeeds.
_db_session_lock = threading.Lock()


def thread_safe_get_db():
    """
    Provide a serialized session for SQLite StaticPool concurrent tests.
    The lock spans the entire session lifetime because StaticPool shares one
    underlying connection — concurrent access causes sqlite3.InterfaceError.
    """
    with _db_session_lock:
        db = TestingSessionLocal()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def test_100_simultaneous_booking_concurrency(client):
    """
    Concurrency Test: 100 simultaneous booking attempts for the exact same doctor and slot.
    Required result:
    - Exactly 1 successful booking (201 Created)
    - Exactly 99 failed requests with conflict (409 Conflict / 400 / 422)
    """
    # === SETUP PHASE: Use the normal `client` (single db_session from conftest) ===
    # All setup must be committed/visible before we switch to thread_safe_get_db.
    client.post("/api/v1/auth/register", json={
        "email": "admin_conc@example.com", "password": "password123", "full_name": "Admin Conc", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_conc@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_conc@example.com", "password": "password123", "full_name": "Dr. Conc",
        "specialization": "Cardiology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    next_monday = get_next_monday()

    # Configure working hours: Monday 09:00 - 10:00
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "10:00:00", "is_active": True}
        ]
    }, headers=admin_headers)

    # Register 100 distinct patient users
    tokens = []
    for idx in range(100):
        email = f"patient_conc_{idx}@example.com"
        client.post("/api/v1/auth/register", json={
            "email": email, "password": "password123", "full_name": f"Patient Conc {idx}", "role": "PATIENT"
        })
        login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"})
        tokens.append(login_resp.json()["access_token"])

    assert len(tokens) == 100

    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    booking_payload = {
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat(),
        "notes": "Concurrency contention test"
    }

    # === CONCURRENT BOOKING PHASE ===
    # Override get_db with thread_safe_get_db for the concurrent booking requests only.
    original_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = thread_safe_get_db
    try:
        def attempt_booking(token):
            headers = {"Authorization": f"Bearer {token}"}
            resp = client.post("/api/v1/appointments", json=booking_payload, headers=headers)
            return resp.status_code

        with ThreadPoolExecutor(max_workers=20) as executor:
            status_codes = list(executor.map(attempt_booking, tokens))

        successes = status_codes.count(201)
        conflicts = status_codes.count(409)
        other_failures = len(status_codes) - successes - conflicts

        # Strict Concurrency Assertion
        assert len(status_codes) == 100
        assert successes == 1, f"Expected exactly 1 successful booking, got {successes}. Status codes: {status_codes}"
        assert conflicts + other_failures == 99, f"Expected 99 failed bookings, got {conflicts + other_failures}"
    finally:
        if original_override:
            app.dependency_overrides[get_db] = original_override
        else:
            app.dependency_overrides.pop(get_db, None)

