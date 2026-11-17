"""Admins can list failed email/calendar jobs and put them back in the queue (issue #34)."""
from datetime import datetime, time, timezone

import pytest

import workers.calendar_worker as calendar_worker_module
import workers.notification_worker as notification_worker_module
from models.audit import AuditLog
from models.calendar import CalendarEvent, CalendarOperation, CalendarSyncStatus
from models.notification import NotificationJob, NotificationStatus, NotificationType
from providers.calendar_provider import MockCalendarProvider
from providers.email_provider import MockEmailProvider
from services.calendar_service import CalendarService
from services.notification_service import NotificationService
from tests.test_notifications import book_appointment, get_next_monday, setup_notification_test_env
from workers.calendar_worker import CalendarWorker
from workers.notification_worker import NotificationWorker


@pytest.fixture
def booked(client, db_session):
    doc, admin_headers, patient_headers, doc_headers = setup_notification_test_env(client)
    monday = get_next_monday()
    appt = book_appointment(
        client, patient_headers, doc["id"],
        datetime.combine(monday, time(9, 0), tzinfo=timezone.utc),
        datetime.combine(monday, time(9, 30), tzinfo=timezone.utc),
    )
    return {"appt": appt, "admin": admin_headers, "patient": patient_headers, "doctor": doc_headers}


def _fail(db, row, error="SMTP said no"):
    row.status = NotificationStatus.FAILED if isinstance(row, NotificationJob) else CalendarSyncStatus.FAILED
    row.attempts = 5
    row.last_error = error
    db.commit()
    return row


def _confirmation(db, appt_id):
    return db.query(NotificationJob).filter_by(
        appointment_id=appt_id, notification_type=NotificationType.BOOKING_CONFIRMATION
    ).first()


def _retries_audited(db, action, resource_id):
    return db.query(AuditLog).filter_by(action=action, resource_id=resource_id).count()


def test_endpoints_need_an_admin(client, booked):
    for method, url in [("get", "/api/v1/admin/failed-jobs"),
                        ("post", "/api/v1/admin/notifications/x/retry"),
                        ("post", "/api/v1/admin/calendar-events/x/retry")]:
        assert getattr(client, method)(url).status_code == 401
        assert getattr(client, method)(url, headers=booked["patient"]).status_code == 403
        assert getattr(client, method)(url, headers=booked["doctor"]).status_code == 403


def test_failed_email_is_listed_retried_and_sent_on_the_next_worker_run(client, db_session, booked):
    job = _fail(db_session, _confirmation(db_session, booked["appt"]["id"]))

    listed = client.get("/api/v1/admin/failed-jobs", params={"kind": "notification"}, headers=booked["admin"])
    assert listed.status_code == 200
    mine = [j for j in listed.json() if j["id"] == job.id]
    assert mine and mine[0]["retryable"] is True and mine[0]["last_error"] == "SMTP said no"
    assert int(listed.headers["X-Total-Count"]) >= 1

    r = client.post(f"/api/v1/admin/notifications/{job.id}/retry", headers=booked["admin"])
    assert r.status_code == 200, r.text
    db_session.refresh(job)
    assert (job.status, job.attempts, job.last_error) == (NotificationStatus.PENDING, 0, None)
    assert _retries_audited(db_session, "notification.retry", job.id) == 1

    provider = MockEmailProvider()
    original = notification_worker_module.notification_service
    notification_worker_module.notification_service = NotificationService(provider=provider)
    try:
        NotificationWorker(batch_size=500).run_once(db_session)
    finally:
        notification_worker_module.notification_service = original
    db_session.refresh(job)
    assert job.status == NotificationStatus.SENT
    assert any(e["subject"] == "Appointment Confirmed" for e in provider.sent_emails)


def test_failed_calendar_sync_is_retried_and_synced_on_the_next_worker_run(client, db_session, booked):
    row = db_session.query(CalendarEvent).filter_by(appointment_id=booked["appt"]["id"]).first()
    assert row.pending_operation == CalendarOperation.CREATE
    _fail(db_session, row, "invalid OAuth credentials")

    listed = client.get("/api/v1/admin/failed-jobs", params={"kind": "calendar"}, headers=booked["admin"]).json()
    assert any(j["id"] == row.id and j["retryable"] for j in listed)

    r = client.post(f"/api/v1/admin/calendar-events/{row.id}/retry", headers=booked["admin"])
    assert r.status_code == 200, r.text
    assert _retries_audited(db_session, "calendar.retry", row.id) == 1

    original = calendar_worker_module.calendar_service
    calendar_worker_module.calendar_service = CalendarService(provider=MockCalendarProvider())
    try:
        CalendarWorker(batch_size=500).run_once(db_session)
    finally:
        calendar_worker_module.calendar_service = original
    db_session.refresh(row)
    assert row.status == CalendarSyncStatus.SYNCED
    assert row.external_event_id


def test_only_failed_rows_can_be_retried(client, db_session, booked):
    job = _confirmation(db_session, booked["appt"]["id"])
    for state in (NotificationStatus.PENDING, NotificationStatus.PROCESSING, NotificationStatus.SENT):
        job.status = state
        db_session.commit()
        r = client.post(f"/api/v1/admin/notifications/{job.id}/retry", headers=booked["admin"])
        assert r.status_code == 409, state
    assert _retries_audited(db_session, "notification.retry", job.id) == 0

    row = db_session.query(CalendarEvent).filter_by(appointment_id=booked["appt"]["id"]).first()
    assert client.post(f"/api/v1/admin/calendar-events/{row.id}/retry", headers=booked["admin"]).status_code == 409

    assert client.post("/api/v1/admin/notifications/no-such-job/retry", headers=booked["admin"]).status_code == 404
    assert client.post("/api/v1/admin/calendar-events/no-such-row/retry", headers=booked["admin"]).status_code == 404


def test_jobs_that_must_not_be_sent_again_are_refused(client, db_session, booked):
    appt_id = booked["appt"]["id"]

    # A reminder retired on purpose (the appointment moved or was cancelled).
    reminder = db_session.query(NotificationJob).filter_by(
        appointment_id=appt_id, notification_type=NotificationType.APPOINTMENT_REMINDER
    ).first()
    _fail(db_session, reminder, "Superseded: appointment rescheduled.")
    listed = client.get("/api/v1/admin/failed-jobs", headers=booked["admin"]).json()
    entry = next(j for j in listed if j["id"] == reminder.id)
    assert entry["retryable"] is False and "retired on purpose" in entry["not_retryable_reason"]
    assert client.post(f"/api/v1/admin/notifications/{reminder.id}/retry", headers=booked["admin"]).status_code == 409

    # A password-reset email: its link is wiped once the job finishes.
    reset = NotificationJob(
        recipient_id=booked["appt"]["patient_id"], notification_type=NotificationType.PASSWORD_RESET,
        status=NotificationStatus.FAILED, attempts=5, last_error="SMTP said no", payload='{"redacted": true}',
    )
    db_session.add(reset)
    db_session.commit()
    assert client.post(f"/api/v1/admin/notifications/{reset.id}/retry", headers=booked["admin"]).status_code == 409

    # A booking confirmation for an appointment that has been cancelled since.
    confirmation = _fail(db_session, _confirmation(db_session, appt_id))
    assert client.post(f"/api/v1/appointments/{appt_id}/cancel", json={}, headers=booked["patient"]).status_code == 200
    r = client.post(f"/api/v1/admin/notifications/{confirmation.id}/retry", headers=booked["admin"])
    assert r.status_code == 409 and "cancelled" in r.json()["detail"]
