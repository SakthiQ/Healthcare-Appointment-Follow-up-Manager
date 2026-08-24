from datetime import date, datetime, time, timedelta, timezone
import pytest
from app.exceptions import ForbiddenError, ValidationError, ConflictError
from services.hold_service import hold_service
from schemas.slot import HoldCreateRequest


def setup_doctor_and_patient(client):
    """Helper to set up an admin, a doctor with working hours, and two patients."""
    # Admin
    client.post("/api/v1/auth/register", json={
        "email": "admin_slot@example.com", "password": "password123", "full_name": "Admin", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_slot@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Doctor
    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_slot@example.com", "password": "password123", "full_name": "Dr. Slot",
        "specialization": "Cardiology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    # Configure Doctor Working Hours (Monday = 0, 09:00 - 11:00 = 4 slots)
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "11:00:00", "is_active": True}
        ]
    }, headers=admin_headers)

    # Patient 1
    client.post("/api/v1/auth/register", json={
        "email": "patient1_slot@example.com", "password": "password123", "full_name": "Patient 1", "role": "PATIENT"
    })
    token1 = client.post("/api/v1/auth/login", json={"email": "patient1_slot@example.com", "password": "password123"}).json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Patient 2
    client.post("/api/v1/auth/register", json={
        "email": "patient2_slot@example.com", "password": "password123", "full_name": "Patient 2", "role": "PATIENT"
    })
    token2 = client.post("/api/v1/auth/login", json={"email": "patient2_slot@example.com", "password": "password123"}).json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    return doc, admin_headers, headers1, headers2


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def test_slot_generation(client):
    """Test generating slots from working hours and slot duration."""
    doc, _, _, _ = setup_doctor_and_patient(client)
    next_monday = get_next_monday()

    response = client.get(f"/api/v1/doctors/{doc['id']}/slots?date={next_monday.isoformat()}")
    assert response.status_code == 200
    data = response.json()
    assert data["total_slots"] == 4
    assert data["available_slots"] == 4
    assert len(data["slots"]) == 4


def test_slots_outside_working_hours(client):
    """Test target date on day with no configured working hours returns 0 slots."""
    doc, _, _, _ = setup_doctor_and_patient(client)
    next_tuesday = get_next_monday() + timedelta(days=1)

    response = client.get(f"/api/v1/doctors/{doc['id']}/slots?date={next_tuesday.isoformat()}")
    assert response.status_code == 200
    data = response.json()
    assert data["total_slots"] == 0
    assert data["available_slots"] == 0


def test_leave_exclusion(client):
    """Test that doctor leave date excludes all slots."""
    doc, admin_headers, _, _ = setup_doctor_and_patient(client)
    next_monday = get_next_monday()

    # Admin adds leave for Monday
    client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat(),
        "reason": "Personal Leave"
    }, headers=admin_headers)

    response = client.get(f"/api/v1/doctors/{doc['id']}/slots?date={next_monday.isoformat()}")
    assert response.status_code == 200
    assert response.json()["available_slots"] == 0


def test_valid_hold_and_duplicate_hold_conflict(client):
    """Test creating a valid hold and rejecting duplicate hold on the same slot."""
    doc, _, headers1, headers2 = setup_doctor_and_patient(client)
    next_monday = get_next_monday()

    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    hold_payload = {
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }

    # Patient 1 creates hold -> 201 Created
    r_hold1 = client.post("/api/v1/slots/holds", json=hold_payload, headers=headers1)
    assert r_hold1.status_code == 201
    hold_data = r_hold1.json()
    assert hold_data["is_active"] is True

    # Slot generation now shows 3 available slots (1 held)
    r_slots = client.get(f"/api/v1/doctors/{doc['id']}/slots?date={next_monday.isoformat()}")
    assert r_slots.json()["available_slots"] == 3

    # Patient 2 attempts duplicate hold on same slot -> 409 Conflict
    r_hold2 = client.post("/api/v1/slots/holds", json=hold_payload, headers=headers2)
    assert r_hold2.status_code == 409
    assert r_hold2.json()["error_code"] == "CONFLICT"


def test_expired_hold_behavior(db_session, client):
    """Test expired holds no longer block slots and cannot be confirmed."""
    doc, _, headers1, _ = setup_doctor_and_patient(client)
    next_monday = get_next_monday()

    # Query patient user id
    me = client.get("/api/v1/auth/me", headers=headers1).json()
    patient_id = me["id"]

    start_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(10, 0), tzinfo=timezone.utc)

    # Manually create hold expiring 5 minutes in the past
    req = HoldCreateRequest(doctor_id=doc["id"], start_time=start_dt, end_time=end_dt)
    hold_resp = hold_service.create_hold(db_session, patient_id=patient_id, req=req, hold_duration_minutes=-5)

    # Confirming expired hold raises ValidationError
    with pytest.raises(ValidationError):
        hold_service.confirm_hold(db_session, hold_resp.id, patient_id=patient_id)

    # Slot remains available after expiry
    slots_resp = client.get(f"/api/v1/doctors/{doc['id']}/slots?date={next_monday.isoformat()}")
    assert slots_resp.json()["available_slots"] == 4


def test_successful_and_invalid_hold_confirmation(db_session, client):
    """Test correct patient can confirm hold while wrong patient is rejected with 403 Forbidden."""
    doc, _, headers1, headers2 = setup_doctor_and_patient(client)
    next_monday = get_next_monday()

    p1 = client.get("/api/v1/auth/me", headers=headers1).json()
    p2 = client.get("/api/v1/auth/me", headers=headers2).json()

    start_dt = datetime.combine(next_monday, time(10, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(10, 30), tzinfo=timezone.utc)

    # Patient 1 creates hold
    hold_data = client.post("/api/v1/slots/holds", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1).json()

    # Patient 1 confirms hold -> Success
    confirmed_hold = hold_service.confirm_hold(db_session, hold_data["id"], patient_id=p1["id"])
    assert confirmed_hold.id == hold_data["id"]

    # Patient 2 attempts to confirm Patient 1's hold -> ForbiddenError
    with pytest.raises(ForbiddenError):
        hold_service.confirm_hold(db_session, hold_data["id"], patient_id=p2["id"])
