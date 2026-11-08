"""Recovery from database failures after a change has already committed.

These tests use one session per request on a file database instead of the shared
`client`/`db_session` fixtures: those bind everything to one outer transaction, so
the rollback under test would also discard the committed rows being asserted on.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from models.appointment import Appointment, AppointmentStatus
from models.calendar import CalendarEvent, CalendarOperation, CalendarSyncStatus
from models.notification import NotificationJob, NotificationStatus, NotificationType
from models.user import User, UserRole
from repositories.notification_repository import notification_repository
import workers.calendar_worker as calendar_worker_module
import workers.notification_worker as notification_worker_module
from workers.calendar_worker import CalendarWorker
from workers.notification_worker import NotificationWorker


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)

    def per_request_session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = per_request_session
    yield factory
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def api(sessions):
    # Default raise_server_exceptions=True: an escaped exception fails the test outright.
    with TestClient(app) as test_client:
        yield test_client


def _login(api, email):
    token = api.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _clinic(api):
    """Returns (doctor profile, patient headers, doctor headers)."""
    suffix = uuid.uuid4().hex[:8]
    api.post("/api/v1/auth/register", json={
        "email": f"admin_{suffix}@example.com", "password": "password123", "full_name": "Admin User", "role": "ADMIN"
    })
    admin = _login(api, f"admin_{suffix}@example.com")
    doctor = api.post("/api/v1/admin/doctors", json={
        "email": f"doc_{suffix}@example.com", "password": "password123", "full_name": "Dr. Recovery",
        "specialization": "Cardiology", "slot_duration_minutes": 30
    }, headers=admin).json()
    api.post(f"/api/v1/admin/doctors/{doctor['id']}/schedule", json={
        "working_hours": [{"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}]
    }, headers=admin)
    api.post("/api/v1/auth/register", json={
        "email": f"patient_{suffix}@example.com", "password": "password123", "full_name": "Patient One"
    })
    return doctor, _login(api, f"patient_{suffix}@example.com"), _login(api, f"doc_{suffix}@example.com")


def _slot(hour=9):
    today = date.today()
    monday = today + timedelta(days=(7 - today.weekday()) + 7)
    start = datetime(monday.year, monday.month, monday.day, hour, tzinfo=timezone.utc)
    return {"start_time": start.isoformat(), "end_time": (start + timedelta(minutes=30)).isoformat()}


def _book(api, doctor, patient, hour=9):
    r = api.post("/api/v1/appointments", json={"doctor_id": doctor["id"], **_slot(hour)}, headers=patient)
    assert r.status_code == 201, r.text
    return r.json()


def _break_job_queueing(monkeypatch):
    """A genuine flush failure (the "has a recipient" CHECK), standing in for any database error at
    this point, which leaves the session unusable until rollback."""
    def broken_create_job(db, appointment_id, recipient_id, notification_type, payload=None, scheduled_for=None):
        db.add(NotificationJob(
            appointment_id=appointment_id, recipient_id=None,
            notification_type=notification_type, status=NotificationStatus.PENDING,
        ))
        db.commit()

    monkeypatch.setattr(notification_repository, "create_job", broken_create_job)


# ---------------------------------------------------------------------------
# A failed post-commit step must not fail a request whose change committed
# ---------------------------------------------------------------------------

def test_booking_succeeds_when_queueing_notifications_hits_a_database_error(api, sessions, monkeypatch):
    doctor, patient, _ = _clinic(api)
    _break_job_queueing(monkeypatch)

    r = api.post("/api/v1/appointments", json={"doctor_id": doctor["id"], **_slot()}, headers=patient)

    assert r.status_code == 201
    assert r.json()["status"] == "CONFIRMED"
    db = sessions()
    assert db.get(Appointment, r.json()["id"]).status == AppointmentStatus.CONFIRMED
    # The notification failure must not take the separate calendar step down with it.
    assert db.query(CalendarEvent).filter_by(appointment_id=r.json()["id"]).count() == 2
    db.close()


def test_reschedule_succeeds_when_queueing_notifications_hits_a_database_error(api, sessions, monkeypatch):
    doctor, patient, _ = _clinic(api)
    appt = _book(api, doctor, patient)
    _break_job_queueing(monkeypatch)

    slot = _slot(10)
    r = api.post(f"/api/v1/appointments/{appt['id']}/reschedule", json={
        "new_start_time": slot["start_time"], "new_end_time": slot["end_time"]
    }, headers=patient)

    assert r.status_code == 200
    assert r.json()["status"] == "RESCHEDULED"


def test_cancel_succeeds_when_queueing_notifications_hits_a_database_error(api, sessions, monkeypatch):
    doctor, patient, _ = _clinic(api)
    appt = _book(api, doctor, patient)
    _break_job_queueing(monkeypatch)

    r = api.post(f"/api/v1/appointments/{appt['id']}/cancel", json={}, headers=patient)

    assert r.status_code == 200
    assert r.json()["status"] == "CANCELLED"
    db = sessions()
    assert db.get(Appointment, appt["id"]).status == AppointmentStatus.CANCELLED
    db.close()


def test_consultation_succeeds_when_queueing_reminders_hits_a_database_error(api, sessions, monkeypatch):
    doctor, patient, doctor_headers = _clinic(api)
    appt = _book(api, doctor, patient)
    _break_job_queueing(monkeypatch)

    r = api.post(f"/api/v1/appointments/{appt['id']}/consultation", json={
        "notes": "Seasonal allergies.",
        "medications": [{"name": "Cetirizine", "dosage": "10mg", "frequency": "Once daily", "duration_days": 2}],
    }, headers=doctor_headers)

    assert r.status_code == 201
    assert [m["name"] for m in r.json()["medications"]] == ["Cetirizine"]
    db = sessions()
    assert db.get(Appointment, appt["id"]).status == AppointmentStatus.COMPLETED
    db.close()


# ---------------------------------------------------------------------------
# Workers: one bad job must not strand the batch, and nothing stays stuck
# ---------------------------------------------------------------------------

def _queue_due_jobs(db, count):
    user = User(email=f"{uuid.uuid4().hex}@example.com", full_name="Recipient", password_hash="x", role=UserRole.PATIENT)
    db.add(user)
    db.commit()
    return [
        notification_repository.create_job(
            db, None, user.id, NotificationType.MEDICATION_REMINDER,
            payload='{"medication_name": "Cetirizine", "dosage": "10mg", "frequency": "Once daily"}',
        ).id
        for _ in range(count)
    ]


def _age_processing_job(db, job_id, attempts=0):
    """Make a job look claimed long ago by a worker that then died."""
    job = db.get(NotificationJob, job_id)
    job.status = NotificationStatus.PROCESSING
    job.attempts = attempts
    job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=settings.NOTIFICATION_PROCESSING_TIMEOUT_MINUTES + 1)
    db.commit()


def test_worker_finishes_batch_when_one_job_hits_a_database_error(sessions, monkeypatch):
    db = sessions()
    bad_id, *good_ids = _queue_due_jobs(db, 3)
    service = notification_worker_module.notification_service
    real_process_job = service.process_job

    def process_job(session, job):
        if job.id == bad_id:
            raise RuntimeError("database connection lost")
        return real_process_job(session, job)

    monkeypatch.setattr(service, "process_job", process_job)
    stats = NotificationWorker().run_once(db)

    assert stats["claimed"] == 3
    assert stats["sent"] == 2
    assert stats["errored"] == 1
    db.expire_all()
    assert all(db.get(NotificationJob, i).status == NotificationStatus.SENT for i in good_ids)
    assert db.get(NotificationJob, bad_id).status == NotificationStatus.PROCESSING
    db.close()


def test_job_abandoned_by_a_dead_worker_is_recovered_and_sent(sessions):
    db = sessions()
    job_id = _queue_due_jobs(db, 1)[0]
    _age_processing_job(db, job_id)

    stats = NotificationWorker().run_once(db)

    assert stats["sent"] == 1
    db.expire_all()
    job = db.get(NotificationJob, job_id)
    assert job.status == NotificationStatus.SENT
    assert job.attempts == 2  # the abandoned attempt counts, then the successful one
    db.close()


def test_job_that_keeps_killing_its_worker_ends_failed(sessions):
    db = sessions()
    job_id = _queue_due_jobs(db, 1)[0]
    _age_processing_job(db, job_id, attempts=settings.NOTIFICATION_MAX_ATTEMPTS - 1)

    stats = NotificationWorker().run_once(db)

    assert stats["claimed"] == 0
    db.expire_all()
    job = db.get(NotificationJob, job_id)
    assert job.status == NotificationStatus.FAILED
    assert job.last_error
    db.close()


def test_job_claimed_recently_is_left_to_its_worker(sessions):
    db = sessions()
    job_id = _queue_due_jobs(db, 1)[0]
    job = db.get(NotificationJob, job_id)
    job.status = NotificationStatus.PROCESSING
    db.commit()

    stats = NotificationWorker().run_once(db)

    assert stats["claimed"] == 0
    db.expire_all()
    assert db.get(NotificationJob, job_id).status == NotificationStatus.PROCESSING
    db.close()


def test_calendar_worker_finishes_batch_when_one_row_hits_a_database_error(api, sessions, monkeypatch):
    doctor, patient, _ = _clinic(api)
    appt = _book(api, doctor, patient)
    db = sessions()
    bad_id, good_id = [r.id for r in db.query(CalendarEvent).filter_by(appointment_id=appt["id"]).all()]
    service = calendar_worker_module.calendar_service
    real_process = service.process_pending_row

    def process(session, row):
        if row.id == bad_id:
            raise RuntimeError("database connection lost")
        return real_process(session, row)

    monkeypatch.setattr(service, "process_pending_row", process)
    stats = CalendarWorker().run_once(db)

    assert stats["errored"] == 1
    assert stats["synced"] == 1
    db.expire_all()
    assert db.get(CalendarEvent, good_id).status == CalendarSyncStatus.SYNCED
    bad = db.get(CalendarEvent, bad_id)
    assert bad.status == CalendarSyncStatus.PENDING_SYNC
    assert bad.pending_operation == CalendarOperation.CREATE
    db.close()
