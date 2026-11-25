"""Waitlist for fully booked days (#71)."""
from datetime import date, datetime, time, timedelta, timezone

from app.config import settings
from models.appointment import AppointmentHold
from models.notification import NotificationJob, NotificationType
from models.waitlist import WaitlistEntry
from services.maintenance_service import maintenance_service
from services.notification_service import notification_service
from services.waitlist_service import waitlist_service
from tests.test_appointments import get_next_monday, setup_appointment_test_env
from workers.hold_worker import hold_expiry_worker

SLOT_HOURS = [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0), (11, 30)]  # Monday 09:00-12:00, 30 min


def _at(h, m):
    return datetime.combine(get_next_monday(), time(h, m), tzinfo=timezone.utc)


def _book(client, doc, headers, h, m):
    r = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"], "start_time": _at(h, m).isoformat(),
        "end_time": (_at(h, m) + timedelta(minutes=30)).isoformat(),
    }, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _fill_monday(client, doc, headers, skip=()):
    return [_book(client, doc, headers, h, m) for (h, m) in SLOT_HOURS if (h, m) not in skip]


def _join(client, doc, headers, day=None):
    return client.post(f"/api/v1/doctors/{doc['id']}/waitlist", json={"date": (day or get_next_monday()).isoformat()},
                       headers=headers)


def _slot_open_jobs(db):
    return db.query(NotificationJob).filter(NotificationJob.notification_type == NotificationType.WAITLIST_SLOT_OPEN).all()


def test_join_only_a_fully_booked_future_day(client):
    doc, _, patient, other = setup_appointment_test_env(client)

    assert _join(client, doc, other).status_code == 409  # Monday still has free slots
    assert _join(client, doc, other, day=date.today()).status_code == 422
    assert _join(client, doc, other, day=date.today() - timedelta(days=3)).status_code == 422

    _fill_monday(client, doc, patient)
    joined = _join(client, doc, other)
    assert joined.status_code == 201
    assert joined.json()["doctor_name"] == "Dr. Appt" and joined.json()["notified_at"] is None
    assert _join(client, doc, other).status_code == 409  # already waiting

    mine = client.get("/api/v1/patients/me/waitlist", headers=other).json()
    assert [(e["doctor_id"], e["date"]) for e in mine] == [(doc["id"], get_next_monday().isoformat())]

    left = client.delete(f"/api/v1/doctors/{doc['id']}/waitlist", params={"date": get_next_monday().isoformat()}, headers=other)
    assert left.status_code == 204
    assert client.get("/api/v1/patients/me/waitlist", headers=other).json() == []
    assert client.delete(f"/api/v1/doctors/{doc['id']}/waitlist", params={"date": get_next_monday().isoformat()},
                         headers=other).status_code == 404


def test_only_patients_can_join(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    _fill_monday(client, doc, patient)
    assert _join(client, doc, admin).status_code == 403
    assert client.get("/api/v1/patients/me/waitlist", headers=admin).status_code == 403


def test_capped_active_entries_per_patient(client, monkeypatch):
    doc, _, patient, other = setup_appointment_test_env(client)
    _fill_monday(client, doc, patient)
    monkeypatch.setattr(settings, "MAX_ACTIVE_WAITLIST_PER_PATIENT", 0)

    r = _join(client, doc, other)

    assert r.status_code == 409 and "at most 0 waitlists" in r.text


def test_a_cancellation_tells_everyone_waiting(client, db_session):
    doc, _, patient, other = setup_appointment_test_env(client)
    booked = _fill_monday(client, doc, patient)
    _join(client, doc, other)

    client.post(f"/api/v1/appointments/{booked[2]['id']}/cancel", headers=patient)

    db_session.expire_all()
    jobs = _slot_open_jobs(db_session)
    assert len(jobs) == 1 and jobs[0].recipient_id == client.get("/api/v1/auth/me", headers=other).json()["id"]
    assert db_session.query(WaitlistEntry).one().notified_at is not None
    # The waitlist reserves nothing: the slot is simply free for whoever books first.
    assert any(s["is_available"] for s in client.get(
        f"/api/v1/doctors/{doc['id']}/slots", params={"date": get_next_monday().isoformat()}).json()["slots"])


def test_no_email_while_the_day_is_still_full(client, db_session):
    doc, _, patient, other = setup_appointment_test_env(client)
    _fill_monday(client, doc, patient)
    _join(client, doc, other)

    told = waitlist_service.notify_if_slot_open(db_session, doc["id"], get_next_monday())

    assert told == 0 and _slot_open_jobs(db_session) == []


def test_an_expiring_hold_opens_a_slot(client, db_session):
    doc, _, patient, other = setup_appointment_test_env(client)
    _fill_monday(client, doc, patient, skip={(11, 30)})
    hold = client.post("/api/v1/slots/holds", json={
        "doctor_id": doc["id"], "start_time": _at(11, 30).isoformat(),
        "end_time": (_at(11, 30) + timedelta(minutes=30)).isoformat()}, headers=patient)
    assert hold.status_code == 201, hold.text
    assert _join(client, doc, other).status_code == 201  # the hold makes the day full

    db_session.get(AppointmentHold, hold.json()["id"]).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()
    hold_expiry_worker.run_once(db_session)

    assert len(_slot_open_jobs(db_session)) == 1


def test_past_dates_are_cleaned_up(client, db_session):
    doc, _, _, _ = setup_appointment_test_env(client)
    patient_id = client.get("/api/v1/auth/me", headers=_patient_headers(client)).json()["id"]
    db_session.add_all([
        WaitlistEntry(patient_id=patient_id, doctor_id=doc["id"], date=date.today() - timedelta(days=1)),
        WaitlistEntry(patient_id=patient_id, doctor_id=doc["id"], date=date.today() + timedelta(days=10)),
    ])
    db_session.commit()

    counts = maintenance_service.purge_expired(db_session)

    assert counts["waitlist_entries"] == 1
    assert db_session.query(WaitlistEntry).count() == 1


def test_the_email_names_the_doctor_and_links_to_booking(client, monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.example.com")
    job = NotificationJob(notification_type=NotificationType.WAITLIST_SLOT_OPEN, appointment_id=None,
                          payload='{"doctor_id": "d1", "date": "2030-01-07", "doctor_name": "Dr Ada"}')

    content = notification_service._build_content(None, job)

    assert content.subject == "A slot has opened up"
    assert "Dr Ada on 2030-01-07" in content.text and "first" in content.text
    assert "https://app.example.com/patient/doctors/d1" in content.html


def _patient_headers(client):
    token = client.post("/api/v1/auth/login", json={"email": "patient1_appt@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {token.json()['access_token']}"}
