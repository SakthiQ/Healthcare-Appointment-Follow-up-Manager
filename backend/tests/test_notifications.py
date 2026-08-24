from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List

from models.notification import NotificationJob, NotificationType, NotificationStatus
from providers.email_provider import (
    EmailProvider,
    EmailProviderTransientError,
    EmailProviderPermanentError,
)
from services.notification_service import NotificationService
from workers.notification_worker import NotificationWorker


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def setup_notification_test_env(client):
    """Admin, one doctor with Monday working hours, one patient."""
    client.post("/api/v1/auth/register", json={
        "email": "admin_notif@example.com", "password": "password123", "full_name": "Admin Notif", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_notif@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_notif@example.com", "password": "password123", "full_name": "Dr. Notif",
        "specialization": "Pediatrics", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True},
        ]
    }, headers=admin_headers)

    client.post("/api/v1/auth/register", json={
        "email": "patient_notif@example.com", "password": "password123", "full_name": "Patient Notif", "role": "PATIENT"
    })
    patient_token = client.post("/api/v1/auth/login", json={"email": "patient_notif@example.com", "password": "password123"}).json()["access_token"]
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    doc_user_token = client.post("/api/v1/auth/login", json={"email": "doc_notif@example.com", "password": "password123"}).json()["access_token"]
    doc_headers = {"Authorization": f"Bearer {doc_user_token}"}

    return doc, admin_headers, patient_headers, doc_headers


def book_appointment(client, headers, doctor_id, start_dt, end_dt):
    r = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class _RecordingEmailProvider(EmailProvider):
    """Always succeeds; records every send for assertions."""

    def __init__(self):
        self.sent: List[Dict[str, Any]] = []

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.sent.append({"to": to_email, "subject": subject, "body": body})


class _AlwaysFailingProvider(EmailProvider):
    def __init__(self, exc: Exception):
        self._exc = exc

    def send(self, to_email: str, subject: str, body: str) -> None:
        raise self._exc


class _FlakyThenSucceedsProvider(EmailProvider):
    """Fails transiently N times, then succeeds."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.attempts = 0

    def send(self, to_email: str, subject: str, body: str) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise EmailProviderTransientError("temporary SMTP outage")


def get_jobs_for_appointment(db_session, appointment_id, notification_type=None):
    query = db_session.query(NotificationJob).filter(NotificationJob.appointment_id == appointment_id)
    if notification_type:
        query = query.filter(NotificationJob.notification_type == notification_type)
    return query.all()


# ---------------------------------------------------------------------------
# Booking / cancellation / leave-conflict notifications go to the right recipients
# ---------------------------------------------------------------------------

def test_booking_creates_confirmation_jobs_for_patient_and_doctor(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    assert len(jobs) == 2
    recipient_ids = {j.recipient_id for j in jobs}
    assert recipient_ids == {appt["patient_id"], appt["doctor_id"]}
    assert all(j.status == NotificationStatus.PENDING for j in jobs)


def test_booking_also_schedules_appointment_reminder_for_patient_and_doctor(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.APPOINTMENT_REMINDER)
    assert len(jobs) == 2
    recipient_ids = {j.recipient_id for j in jobs}
    assert recipient_ids == {appt["patient_id"], appt["doctor_id"]}
    for job in jobs:
        assert job.next_retry_at is not None
        # Scheduled ~24h before the appointment start time.
        expected = start_dt - timedelta(hours=24)
        assert abs((job.next_retry_at.replace(tzinfo=timezone.utc) - expected).total_seconds()) < 5


def test_cancellation_creates_jobs_for_patient_and_doctor(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)
    r = client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient_headers)
    assert r.status_code == 200

    jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.CANCELLATION)
    assert len(jobs) == 2
    recipient_ids = {j.recipient_id for j in jobs}
    assert recipient_ids == {appt["patient_id"], appt["doctor_id"]}


def test_leave_conflict_notification_goes_to_affected_patient_only(client, db_session):
    doc, admin_headers, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)
    client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)

    jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.DOCTOR_LEAVE_CONFLICT)
    assert len(jobs) == 1
    assert jobs[0].recipient_id == appt["patient_id"]


# ---------------------------------------------------------------------------
# Medication reminder generation
# ---------------------------------------------------------------------------

def test_medication_reminder_generation_from_prescription(client, db_session):
    doc, _, patient_headers, doc_headers = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    r = client.post(f"/api/v1/appointments/{appt['id']}/consultation", json={
        "notes": "Mild ear infection.",
        "prescription_instructions": "Take with food.",
        "medications": [
            {"name": "Amoxicillin", "dosage": "250mg", "frequency": "Twice daily", "duration_days": 5},
            {"name": "Paracetamol", "dosage": "500mg", "frequency": "As needed", "duration_days": None},
        ]
    }, headers=doc_headers)
    assert r.status_code == 201

    jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.MEDICATION_REMINDER)
    patient_jobs = [j for j in jobs if j.recipient_id == appt["patient_id"]]
    assert len(patient_jobs) == 6  # 5 days (Amoxicillin) + 1 day (Paracetamol default)
    for job in jobs:
        assert job.status == NotificationStatus.PENDING
        assert job.next_retry_at is not None


def test_medication_reminder_bounded_by_max_cap(client, db_session):
    import services.reminder_service as reminder_module
    doc, _, patient_headers, doc_headers = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    r = client.post(f"/api/v1/appointments/{appt['id']}/consultation", json={
        "notes": "Long-term medication.",
        "medications": [
            {"name": "LongTermMed", "dosage": "10mg", "frequency": "Once daily", "duration_days": 9999},
        ]
    }, headers=doc_headers)
    assert r.status_code == 201

    jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.MEDICATION_REMINDER)
    assert len(jobs) == reminder_module.MAX_MEDICATION_REMINDERS_PER_MEDICATION


# ---------------------------------------------------------------------------
# Worker processing: successful email, transient failure + retry, permanent failure
# ---------------------------------------------------------------------------

def test_successful_email_marks_job_sent(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _RecordingEmailProvider()
    service = NotificationService(provider=provider)
    job = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)[0]

    result = service.process_job(db_session, job)

    assert result.status == NotificationStatus.SENT
    assert result.attempts == 1
    assert result.last_error is None
    assert len(provider.sent) == 1
    assert "Confirmed" in provider.sent[0]["subject"]


def test_transient_email_failure_is_retryable(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _AlwaysFailingProvider(EmailProviderTransientError("smtp timeout"))
    service = NotificationService(provider=provider)
    job = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)[0]

    result = service.process_job(db_session, job)

    assert result.status == NotificationStatus.PENDING  # retryable -> back to PENDING
    assert result.attempts == 1
    assert "smtp timeout" in result.last_error
    assert result.next_retry_at is not None
    assert result.next_retry_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


def test_retry_eventually_succeeds(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _FlakyThenSucceedsProvider(fail_times=2)
    service = NotificationService(provider=provider)
    job = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)[0]

    job = service.process_job(db_session, job)
    assert job.status == NotificationStatus.PENDING
    assert job.attempts == 1

    job = service.process_job(db_session, job)
    assert job.status == NotificationStatus.PENDING
    assert job.attempts == 2

    job = service.process_job(db_session, job)
    assert job.status == NotificationStatus.SENT
    assert job.attempts == 3


def test_permanent_failure_after_max_attempts_is_bounded(client, db_session):
    from app.config import settings
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _AlwaysFailingProvider(EmailProviderTransientError("permanently down"))
    service = NotificationService(provider=provider)
    job = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)[0]

    for _ in range(settings.NOTIFICATION_MAX_ATTEMPTS):
        job = service.process_job(db_session, job)

    assert job.status == NotificationStatus.FAILED
    assert job.attempts == settings.NOTIFICATION_MAX_ATTEMPTS
    assert "permanently down" in job.last_error

    # Bounded: FAILED jobs are terminal, no further retries are attempted by the worker.
    from repositories.notification_repository import notification_repository
    due = notification_repository.get_due_jobs(db_session, limit=100)
    assert job.id not in [j.id for j in due]


def test_permanent_provider_error_skips_retry_immediately(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _AlwaysFailingProvider(EmailProviderPermanentError("invalid recipient address"))
    service = NotificationService(provider=provider)
    job = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)[0]

    result = service.process_job(db_session, job)

    assert result.status == NotificationStatus.FAILED
    assert result.attempts == 1
    assert "invalid recipient" in result.last_error


# ---------------------------------------------------------------------------
# NotificationWorker: claims due jobs, respects scheduling, avoids double-processing
# ---------------------------------------------------------------------------

def test_worker_processes_due_jobs_and_ignores_future_scheduled_ones(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    # Two weeks out so the reminder's (start - 24h) scheduling is guaranteed
    # to still be in the future regardless of which weekday tests run on.
    far_monday = get_next_monday() + timedelta(days=7)
    start_dt = datetime.combine(far_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(far_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    # This test's DB session is shared with the rest of the suite (see
    # tests/conftest.py's db_session fixture — it isn't a per-test SAVEPOINT),
    # so other tests' due jobs can already be sitting in the same table. The
    # worker's aggregate stats would include those, so assert on THIS test's
    # own job rows specifically rather than on the aggregate counts.
    provider = _RecordingEmailProvider()
    import workers.notification_worker as worker_module
    original_service = worker_module.notification_service
    worker_module.notification_service = NotificationService(provider=provider)
    try:
        worker = NotificationWorker(batch_size=200)
        worker.run_once(db_session)
    finally:
        worker_module.notification_service = original_service

    confirmation_jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    assert len(confirmation_jobs) == 2
    assert all(j.status == NotificationStatus.SENT for j in confirmation_jobs)

    reminder_jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.APPOINTMENT_REMINDER)
    assert len(reminder_jobs) == 2
    assert all(j.status == NotificationStatus.PENDING for j in reminder_jobs)  # not yet due


def test_worker_does_not_reprocess_already_sent_jobs(client, db_session):
    doc, _, patient_headers, _ = setup_notification_test_env(client)
    far_monday = get_next_monday() + timedelta(days=7)
    start_dt = datetime.combine(far_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(far_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _RecordingEmailProvider()
    import workers.notification_worker as worker_module
    original_service = worker_module.notification_service
    worker_module.notification_service = NotificationService(provider=provider)
    try:
        worker = NotificationWorker(batch_size=200)
        worker.run_once(db_session)
        confirmation_jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
        sent_ids_after_first_run = {j.id for j in confirmation_jobs if j.status == NotificationStatus.SENT}
        sends_after_first_run = len(provider.sent)

        worker.run_once(db_session)
        confirmation_jobs = get_jobs_for_appointment(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
        sent_ids_after_second_run = {j.id for j in confirmation_jobs if j.status == NotificationStatus.SENT}
    finally:
        worker_module.notification_service = original_service

    assert len(sent_ids_after_first_run) == 2
    assert sent_ids_after_second_run == sent_ids_after_first_run  # unchanged: no re-send, no re-processing
    assert len(provider.sent) == sends_after_first_run  # second run added zero new sends for this appointment's jobs


# ---------------------------------------------------------------------------
# appointment success is independent of email/notification success
# ---------------------------------------------------------------------------

def test_booking_succeeds_even_if_notification_queueing_raises(client):
    """AppointmentService swallows notification-queueing failures so a
    booking always succeeds regardless of the notification subsystem."""
    import services.appointment_service as appt_service_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated notification outage")

    original = appt_service_module.notification_service.queue_notification
    appt_service_module.notification_service.queue_notification = boom
    try:
        doc, _, patient_headers, _ = setup_notification_test_env(client)
        next_monday = get_next_monday()
        start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
        end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
        r = client.post("/api/v1/appointments", json={
            "doctor_id": doc["id"],
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat()
        }, headers=patient_headers)
        assert r.status_code == 201
        assert r.json()["status"] == "CONFIRMED"
    finally:
        appt_service_module.notification_service.queue_notification = original
