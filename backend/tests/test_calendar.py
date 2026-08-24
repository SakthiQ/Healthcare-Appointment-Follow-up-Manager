from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from app.core.datetime_utils import ensure_utc
from models.calendar import CalendarEvent, CalendarOperation, CalendarSyncStatus
from providers.calendar_provider import (
    CalendarProvider,
    CalendarProviderTransientError,
    CalendarProviderPermanentError,
    CalendarEventNotFoundError,
    MockCalendarProvider,
)
from repositories.calendar_repository import calendar_repository
from services.calendar_service import CalendarService
from workers.calendar_worker import CalendarWorker


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def setup_calendar_test_env(client):
    client.post("/api/v1/auth/register", json={
        "email": "admin_cal@example.com", "password": "password123", "full_name": "Admin Cal", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_cal@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_cal@example.com", "password": "password123", "full_name": "Dr. Cal",
        "specialization": "Cardiology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True},
        ]
    }, headers=admin_headers)

    client.post("/api/v1/auth/register", json={
        "email": "patient_cal@example.com", "password": "password123", "full_name": "Patient Cal", "role": "PATIENT"
    })
    patient_token = client.post("/api/v1/auth/login", json={"email": "patient_cal@example.com", "password": "password123"}).json()["access_token"]
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    return doc, admin_headers, patient_headers


def book_appointment(client, headers, doctor_id, start_dt, end_dt):
    r = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def calendar_rows(db_session, appointment_id):
    return db_session.query(CalendarEvent).filter(
        CalendarEvent.appointment_id == appointment_id
    ).order_by(CalendarEvent.recipient_type).all()


class _FailingProvider(CalendarProvider):
    """Always raises the given exception for every operation."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls = 0

    def create_event(self, event_id, summary, description, start_time, end_time, attendee_email=None):
        self.calls += 1
        raise self._exc

    def update_event(self, external_event_id, summary, description, start_time, end_time):
        self.calls += 1
        raise self._exc

    def delete_event(self, external_event_id):
        self.calls += 1
        raise self._exc


class _CountingMockProvider(MockCalendarProvider):
    """MockCalendarProvider that also counts operations, to prove idempotency."""

    def __init__(self):
        super().__init__()
        self.create_calls = 0
        self.update_calls = 0
        self.delete_calls = 0

    def create_event(self, event_id, summary, description, start_time, end_time, attendee_email=None):
        self.create_calls += 1
        return super().create_event(event_id, summary, description, start_time, end_time, attendee_email)

    def update_event(self, external_event_id, summary, description, start_time, end_time):
        self.update_calls += 1
        return super().update_event(external_event_id, summary, description, start_time, end_time)

    def delete_event(self, external_event_id):
        self.delete_calls += 1
        return super().delete_event(external_event_id)


def run_worker_with(provider, db_session, batch_size=200):
    """Run CalendarWorker once with a specific provider injected."""
    import workers.calendar_worker as worker_module
    original = worker_module.calendar_service
    worker_module.calendar_service = CalendarService(provider=provider)
    try:
        return CalendarWorker(batch_size=batch_size).run_once(db_session)
    finally:
        worker_module.calendar_service = original


# ---------------------------------------------------------------------------
# Event creation on booking
# ---------------------------------------------------------------------------

def test_booking_creates_pending_calendar_rows_for_patient_and_doctor(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    rows = calendar_rows(db_session, appt["id"])
    assert len(rows) == 2
    assert {r.recipient_type for r in rows} == {"DOCTOR", "PATIENT"}
    for row in rows:
        assert row.status == CalendarSyncStatus.PENDING_SYNC
        assert row.pending_operation == CalendarOperation.CREATE
        assert row.external_event_id is None  # not yet pushed — worker does that
        assert row.idempotency_key


def test_worker_creates_external_events(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    assert len(rows) == 2
    for row in rows:
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.pending_operation == CalendarOperation.NONE
        assert row.external_event_id is not None
    assert provider.create_calls == 2
    assert len(provider.events) == 2


# ---------------------------------------------------------------------------
# Update on reschedule
# ---------------------------------------------------------------------------

def test_reschedule_updates_external_events(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)
    original_external_ids = {r.recipient_type: r.external_event_id for r in calendar_rows(db_session, appt["id"])}

    new_start = datetime.combine(next_monday, time(10, 0), tzinfo=timezone.utc)
    new_end = datetime.combine(next_monday, time(10, 30), tzinfo=timezone.utc)
    r = client.post(f"/api/v1/appointments/{appt['id']}/reschedule", json={
        "new_start_time": new_start.isoformat(),
        "new_end_time": new_end.isoformat()
    }, headers=patient_headers)
    assert r.status_code == 200

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.pending_operation == CalendarOperation.UPDATE
        assert row.status == CalendarSyncStatus.PENDING_SYNC

    run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.SYNCED
        # Same external event updated in place, NOT a new duplicate event.
        assert row.external_event_id == original_external_ids[row.recipient_type]
    assert provider.update_calls == 2
    assert provider.create_calls == 2  # unchanged: no extra creates
    assert len(provider.events) == 2
    for event in provider.events.values():
        # SQLite hands datetimes back tz-naive; normalise before comparing.
        assert ensure_utc(event["start_time"]) == new_start


# ---------------------------------------------------------------------------
# Delete on cancellation
# ---------------------------------------------------------------------------

def test_cancellation_deletes_external_events(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)
    assert len(provider.events) == 2

    r = client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient_headers)
    assert r.status_code == 200

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.pending_operation == CalendarOperation.DELETE

    run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.pending_operation == CalendarOperation.NONE
        assert row.external_event_id is None
    assert provider.delete_calls == 2
    assert len(provider.events) == 0


# ---------------------------------------------------------------------------
# Provider unavailable / retry / permanent failure
# ---------------------------------------------------------------------------

def test_calendar_provider_unavailable_does_not_invalidate_appointment(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _FailingProvider(CalendarProviderTransientError("Google Calendar unreachable"))
    run_worker_with(provider, db_session)

    # Calendar sync failed but is queued for retry...
    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.PENDING_SYNC
        assert row.attempts == 1
        assert "unreachable" in row.last_error
        assert row.next_retry_at is not None
        assert row.next_retry_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    # ...and the appointment itself is completely unaffected.
    r_appt = client.get(f"/api/v1/appointments/{appt['id']}", headers=patient_headers)
    assert r_appt.status_code == 200
    assert r_appt.json()["status"] == "CONFIRMED"


def test_calendar_retry_eventually_succeeds(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    # First attempt fails transiently.
    failing = _FailingProvider(CalendarProviderTransientError("temporary outage"))
    run_worker_with(failing, db_session)

    rows = calendar_rows(db_session, appt["id"])
    assert all(r.status == CalendarSyncStatus.PENDING_SYNC and r.attempts == 1 for r in rows)

    # Clear the backoff so the rows are due again, then retry with a healthy provider.
    for row in rows:
        row.next_retry_at = None
    db_session.commit()

    working = _CountingMockProvider()
    run_worker_with(working, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.external_event_id is not None
        assert row.last_error is None
    assert working.create_calls == 2


def test_calendar_permanent_error_marks_failed_without_retry(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _FailingProvider(CalendarProviderPermanentError("invalid OAuth credentials"))
    run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.FAILED
        assert row.attempts == 1
        assert "invalid OAuth" in row.last_error

    # FAILED rows are terminal — the worker must not pick them up again.
    due = calendar_repository.get_due_syncs(db_session, limit=200)
    failed_ids = {r.id for r in rows}
    assert failed_ids.isdisjoint({r.id for r in due})


def test_calendar_retries_are_bounded_by_max_attempts(client, db_session):
    from app.config import settings
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _FailingProvider(CalendarProviderTransientError("persistent outage"))
    for _ in range(settings.CALENDAR_MAX_ATTEMPTS):
        # Clear backoff each round so the rows are immediately due again.
        for row in calendar_rows(db_session, appt["id"]):
            row.next_retry_at = None
        db_session.commit()
        run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.FAILED
        assert row.attempts == settings.CALENDAR_MAX_ATTEMPTS


# ---------------------------------------------------------------------------
# Repeated operations / duplicate prevention
# ---------------------------------------------------------------------------

def test_repeated_create_does_not_duplicate_events(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)
    assert provider.create_calls == 2
    assert len(provider.events) == 2

    # Re-arming a create (e.g. reconciliation or a duplicate sync trigger) and
    # re-running must reuse the same idempotency key, not make a 3rd event.
    rows = calendar_rows(db_session, appt["id"])
    keys_before = {r.recipient_type: r.idempotency_key for r in rows}

    from repositories.appointment_repository import appointment_repository
    from services.calendar_service import calendar_service as real_calendar_service

    appointment = appointment_repository.get_by_id(db_session, appt["id"])
    real_calendar_service.sync_appointment_created(db_session, appointment)

    run_worker_with(provider, db_session)

    rows_after = calendar_rows(db_session, appt["id"])
    assert len(rows_after) == 2  # still exactly 2 DB rows (unique constraint)
    assert {r.recipient_type: r.idempotency_key for r in rows_after} == keys_before
    assert len(provider.events) == 2  # still exactly 2 external events


def test_worker_does_not_reprocess_synced_rows(client, db_session):
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)
    creates_after_first_run = provider.create_calls

    run_worker_with(provider, db_session)

    assert provider.create_calls == creates_after_first_run  # no re-processing
    rows = calendar_rows(db_session, appt["id"])
    assert all(r.status == CalendarSyncStatus.SYNCED for r in rows)


def test_repeated_delete_is_treated_as_success(client, db_session):
    """A delete for an event that is already gone externally must settle as
    synced, not fail — repeated/duplicate deletes are a no-op."""
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)

    # Wipe the provider's events behind our back, simulating "already deleted".
    provider.events.clear()

    r = client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient_headers)
    assert r.status_code == 200
    run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.pending_operation == CalendarOperation.NONE
        assert row.last_error is None


def test_update_recreates_event_when_missing_externally(client, db_session):
    """Reconciliation: if the external event vanished, an update recreates it
    rather than leaving the appointment unrepresented."""
    doc, _, patient_headers = setup_calendar_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patient_headers, doc["id"], start_dt, end_dt)

    provider = _CountingMockProvider()
    run_worker_with(provider, db_session)
    provider.events.clear()  # event disappeared externally

    new_start = datetime.combine(next_monday, time(11, 0), tzinfo=timezone.utc)
    new_end = datetime.combine(next_monday, time(11, 30), tzinfo=timezone.utc)
    r = client.post(f"/api/v1/appointments/{appt['id']}/reschedule", json={
        "new_start_time": new_start.isoformat(),
        "new_end_time": new_end.isoformat()
    }, headers=patient_headers)
    assert r.status_code == 200

    run_worker_with(provider, db_session)

    rows = calendar_rows(db_session, appt["id"])
    for row in rows:
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.external_event_id is not None
    assert len(provider.events) == 2  # recreated both


# ---------------------------------------------------------------------------
# Calendar failure never blocks the appointment transaction
# ---------------------------------------------------------------------------

def test_booking_succeeds_even_if_calendar_arming_raises(client):
    import services.appointment_service as appt_service_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated calendar subsystem outage")

    original = appt_service_module.calendar_service.sync_appointment_created
    appt_service_module.calendar_service.sync_appointment_created = boom
    try:
        doc, _, patient_headers = setup_calendar_test_env(client)
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
        appt_service_module.calendar_service.sync_appointment_created = original


def test_demo_mode_uses_mock_calendar_provider():
    """DEMO_MODE must resolve to MockCalendarProvider so the whole flow works
    with no Google credentials present."""
    from app.config import settings
    from providers.calendar_provider import get_calendar_provider, GoogleCalendarProvider

    original = settings.DEMO_MODE
    try:
        settings.DEMO_MODE = True
        assert isinstance(get_calendar_provider(), MockCalendarProvider)
        settings.DEMO_MODE = False
        assert isinstance(get_calendar_provider(), GoogleCalendarProvider)
    finally:
        settings.DEMO_MODE = original


def test_google_provider_without_credentials_raises_permanent_error():
    """A misconfigured real provider must fail with a permanent (non-retrying)
    error rather than burning retries against an endpoint it can't authorise."""
    from app.config import settings
    from providers.calendar_provider import GoogleCalendarProvider

    original = settings.GOOGLE_CLIENT_ID
    try:
        settings.GOOGLE_CLIENT_ID = None
        provider = GoogleCalendarProvider()
        try:
            provider.create_event("id", "s", "d", datetime.now(timezone.utc), datetime.now(timezone.utc))
            assert False, "expected CalendarProviderPermanentError"
        except CalendarProviderPermanentError as exc:
            assert "not configured" in str(exc)
    finally:
        settings.GOOGLE_CLIENT_ID = original
