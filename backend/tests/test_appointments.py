from datetime import date, datetime, time, timedelta, timezone
import pytest
from models.appointment import AppointmentStatus


def setup_appointment_test_env(client):
    """Helper fixture to set up Admin, Doctor, and 2 Patients."""
    # Admin
    client.post("/api/v1/auth/register", json={
        "email": "admin_appt@example.com", "password": "password123", "full_name": "Admin Appt", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_appt@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Doctor
    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_appt@example.com", "password": "password123", "full_name": "Dr. Appt",
        "specialization": "Neurology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    # Doctor working hours: Monday (day 0) 09:00 - 12:00
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}
        ]
    }, headers=admin_headers)

    # Patient 1
    client.post("/api/v1/auth/register", json={
        "email": "patient1_appt@example.com", "password": "password123", "full_name": "Patient One", "role": "PATIENT"
    })
    token1 = client.post("/api/v1/auth/login", json={"email": "patient1_appt@example.com", "password": "password123"}).json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # Patient 2
    client.post("/api/v1/auth/register", json={
        "email": "patient2_appt@example.com", "password": "password123", "full_name": "Patient Two", "role": "PATIENT"
    })
    token2 = client.post("/api/v1/auth/login", json={"email": "patient2_appt@example.com", "password": "password123"}).json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    return doc, admin_headers, headers1, headers2


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def test_normal_booking_from_hold(client):
    """Test creating hold and confirming appointment successfully."""
    doc, _, headers1, _ = setup_appointment_test_env(client)
    next_monday = get_next_monday()

    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    # 1. Create Hold
    hold = client.post("/api/v1/slots/holds", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1).json()

    # 2. Confirm Appointment
    r_appt = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "hold_id": hold["id"],
        "notes": "Severe headaches"
    }, headers=headers1)
    assert r_appt.status_code == 201
    data = r_appt.json()
    assert data["status"] == AppointmentStatus.CONFIRMED.value
    assert data["doctor_profile_id"] == doc["id"]


def test_booking_unavailable_slot_and_double_booking_rejection(client):
    """Test that attempting to book an already booked slot fails with 409 Conflict."""
    doc, _, headers1, headers2 = setup_appointment_test_env(client)
    next_monday = get_next_monday()

    start_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(10, 0), tzinfo=timezone.utc)

    # Patient 1 direct books slot 09:30 - 10:00
    r1 = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1)
    assert r1.status_code == 201

    # Patient 2 attempts to book exact same slot -> 409 Conflict
    r2 = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers2)
    assert r2.status_code == 409
    assert r2.json()["error_code"] == "CONFLICT"


def test_reschedule_appointment_and_reschedule_to_unavailable_slot(client):
    """Test rescheduling appointment and rejecting reschedule to an unavailable slot."""
    doc, _, headers1, headers2 = setup_appointment_test_env(client)
    next_monday = get_next_monday()

    s1_start = datetime.combine(next_monday, time(10, 0), tzinfo=timezone.utc)
    s1_end = datetime.combine(next_monday, time(10, 30), tzinfo=timezone.utc)
    s2_start = datetime.combine(next_monday, time(10, 30), tzinfo=timezone.utc)
    s2_end = datetime.combine(next_monday, time(11, 0), tzinfo=timezone.utc)

    # Patient 1 books 10:00 - 10:30
    appt1 = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": s1_start.isoformat(),
        "end_time": s1_end.isoformat()
    }, headers=headers1).json()

    # Patient 2 books 10:30 - 11:00
    client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": s2_start.isoformat(),
        "end_time": s2_end.isoformat()
    }, headers=headers2)

    # Patient 1 attempts to reschedule to 10:30 - 11:00 (which is booked by Patient 2) -> 409 Conflict
    r_resch_fail = client.post(f"/api/v1/appointments/{appt1['id']}/reschedule", json={
        "new_start_time": s2_start.isoformat(),
        "new_end_time": s2_end.isoformat()
    }, headers=headers1)
    assert r_resch_fail.status_code == 409

    # Patient 1 reschedules to 11:00 - 11:30 -> 200 OK
    s3_start = datetime.combine(next_monday, time(11, 0), tzinfo=timezone.utc)
    s3_end = datetime.combine(next_monday, time(11, 30), tzinfo=timezone.utc)
    r_resch_success = client.post(f"/api/v1/appointments/{appt1['id']}/reschedule", json={
        "new_start_time": s3_start.isoformat(),
        "new_end_time": s3_end.isoformat()
    }, headers=headers1)
    assert r_resch_success.status_code == 200
    assert r_resch_success.json()["status"] == AppointmentStatus.RESCHEDULED.value

    # Regression: reschedule must mutate the existing appointment, not create
    # a second one. Patient 1 should still have exactly one appointment.
    listed = client.get("/api/v1/appointments", headers=headers1).json()
    patient1_appts = [a for a in listed if a["id"] == appt1["id"]]
    assert len(listed) == 1
    assert len(patient1_appts) == 1
    assert listed[0]["start_time"].startswith(s3_start.isoformat()[:16])


def test_cancel_appointment_and_repeated_cancellation_rejection(client):
    """Test cancelling appointment and rejecting repeated cancellation attempts."""
    doc, _, headers1, _ = setup_appointment_test_env(client)
    next_monday = get_next_monday()

    start_dt = datetime.combine(next_monday, time(11, 30), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(12, 0), tzinfo=timezone.utc)

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1).json()

    # Cancel appointment -> 200 OK
    r_cancel = client.post(f"/api/v1/appointments/{appt['id']}/cancel", json={
        "cancellation_reason": "Feeling better"
    }, headers=headers1)
    assert r_cancel.status_code == 200
    assert r_cancel.json()["status"] == AppointmentStatus.CANCELLED.value

    # Repeat cancel -> 422 Unprocessable Entity
    r_repeat = client.post(f"/api/v1/appointments/{appt['id']}/cancel", json={}, headers=headers1)
    assert r_repeat.status_code == 422


def test_unauthorized_appointment_access(client):
    """Test Patient 2 cannot access or cancel Patient 1's appointment."""
    doc, _, headers1, headers2 = setup_appointment_test_env(client)
    next_monday = get_next_monday()

    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1).json()

    # Patient 2 attempting to view Patient 1's appt -> 403 Forbidden
    r_get = client.get(f"/api/v1/appointments/{appt['id']}", headers=headers2)
    assert r_get.status_code == 403

    # Patient 2 attempting to cancel Patient 1's appt -> 403 Forbidden
    r_cancel = client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=headers2)
    assert r_cancel.status_code == 403


def test_expired_hold_cannot_be_confirmed_into_appointment(client, db_session):
    """
    Regression test: an appointment must not be confirmable from an expired
    hold. Slot must remain bookable afterwards, and the DB is the final
    authority for hold validity, not the frontend.
    """
    from models.appointment import AppointmentHold

    doc, _, headers1, headers2 = setup_appointment_test_env(client)
    next_monday = get_next_monday()

    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    hold = client.post("/api/v1/slots/holds", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1).json()

    # Force the hold to be expired directly in the DB (simulating time passing).
    hold_row = db_session.query(AppointmentHold).filter(AppointmentHold.id == hold["id"]).first()
    hold_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    r_appt = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "hold_id": hold["id"],
        "notes": "Should fail, hold expired"
    }, headers=headers1)
    assert r_appt.status_code == 422

    # The slot must still be bookable by another patient since the expired
    # hold never resulted in a confirmed appointment.
    r_appt2 = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers2)
    assert r_appt2.status_code == 201
