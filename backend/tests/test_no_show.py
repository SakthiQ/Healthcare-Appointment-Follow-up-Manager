"""Marking an appointment as a no-show (#68)."""
from datetime import datetime, time, timedelta, timezone

from models.appointment import Appointment, AppointmentStatus
from models.audit import AuditLog
from models.notification import NotificationJob, NotificationStatus, NotificationType
from tests.test_appointments import get_next_monday, setup_appointment_test_env


def _login(client, email):
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _book(client, doc, headers, hour=9):
    monday = get_next_monday()
    return client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": datetime.combine(monday, time(hour, 0), tzinfo=timezone.utc).isoformat(),
        "end_time": datetime.combine(monday, time(hour, 30), tzinfo=timezone.utc).isoformat(),
    }, headers=headers).json()


def _move_into_past(db, appointment_id):
    appt = db.get(Appointment, appointment_id)
    appt.start_time = datetime.now(timezone.utc) - timedelta(hours=2)
    appt.end_time = appt.start_time + timedelta(minutes=30)
    db.commit()


def test_doctor_marks_a_past_appointment_as_no_show(client, db_session):
    doc, _, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)
    _move_into_past(db_session, appt["id"])

    r = client.post(f"/api/v1/appointments/{appt['id']}/no-show", headers=_login(client, "doc_appt@example.com"))

    assert r.status_code == 200
    assert r.json()["status"] == "NO_SHOW"
    db_session.expire_all()
    reminders = db_session.query(NotificationJob).filter(
        NotificationJob.appointment_id == appt["id"],
        NotificationJob.notification_type == NotificationType.APPOINTMENT_REMINDER).all()
    assert reminders and all(j.status == NotificationStatus.FAILED and "did not attend" in j.last_error for j in reminders)
    audit = db_session.query(AuditLog).filter(AuditLog.action == "appointment.no_show").all()
    assert len(audit) == 1 and audit[0].resource_id == appt["id"]


def test_admin_may_mark_a_no_show(client, db_session):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)
    _move_into_past(db_session, appt["id"])

    assert client.post(f"/api/v1/appointments/{appt['id']}/no-show", headers=admin).status_code == 200


def test_patients_and_other_doctors_may_not(client, db_session):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    client.post("/api/v1/admin/doctors", json={
        "email": "other_doc@example.com", "password": "password123", "full_name": "Dr. Other",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin)
    appt = _book(client, doc, patient)
    _move_into_past(db_session, appt["id"])
    url = f"/api/v1/appointments/{appt['id']}/no-show"

    assert client.post(url, headers=patient).status_code == 403
    assert client.post(url, headers=_login(client, "other_doc@example.com")).status_code == 403
    assert client.post(url).status_code == 401


def test_not_before_the_start_time(client):
    doc, _, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)  # next Monday: still in the future

    r = client.post(f"/api/v1/appointments/{appt['id']}/no-show", headers=_login(client, "doc_appt@example.com"))

    assert r.status_code == 422


def test_only_from_confirmed_or_rescheduled(client, db_session):
    doc, _, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)
    client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient)
    _move_into_past(db_session, appt["id"])
    doctor = _login(client, "doc_appt@example.com")

    assert client.post(f"/api/v1/appointments/{appt['id']}/no-show", headers=doctor).status_code == 409

    db_session.get(Appointment, appt["id"]).status = AppointmentStatus.RESCHEDULED
    db_session.commit()
    assert client.post(f"/api/v1/appointments/{appt['id']}/no-show", headers=doctor).status_code == 200
    # And not twice.
    assert client.post(f"/api/v1/appointments/{appt['id']}/no-show", headers=doctor).status_code == 409


def test_a_no_show_does_not_hold_the_slot(client, db_session):
    """NO_SHOW is not an active booking: the same slot can be booked again."""
    doc, _, patient, other_patient = setup_appointment_test_env(client)
    first = _book(client, doc, patient)
    db_session.get(Appointment, first["id"]).status = AppointmentStatus.NO_SHOW
    db_session.commit()

    again = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": first["start_time"], "end_time": first["end_time"],
    }, headers=other_patient)

    assert again.status_code == 201
