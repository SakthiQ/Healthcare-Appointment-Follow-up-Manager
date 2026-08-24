"""
Phase 12 — end-to-end integration validation.

Each test drives a complete workflow through the HTTP API exactly as a real
client would, then asserts on all six dimensions the phase requires:
HTTP response, database state, authorization, background jobs, provider
interaction, and resulting state.

These tests deliberately go through the API rather than calling services
directly — that is what makes them integration tests and what proves no
module bypasses the service/business layer.
"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.core.datetime_utils import ensure_utc
from models.appointment import Appointment, AppointmentHold, AppointmentStatus
from models.calendar import CalendarEvent, CalendarOperation, CalendarSyncStatus
from models.clinical import AISummary, AISummaryStatus, AISummaryType, Consultation, Medication
from models.notification import NotificationJob, NotificationStatus, NotificationType
from providers.ai_provider import AIProvider, AIProviderTimeoutError, AIProviderUnavailableError
from providers.calendar_provider import CalendarProviderTransientError, MockCalendarProvider
from providers.email_provider import EmailProvider, EmailProviderTransientError
from services.ai_service import AIService
from services.calendar_service import CalendarService
from services.notification_service import NotificationService
from workers.calendar_worker import CalendarWorker
from workers.notification_worker import NotificationWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def next_weekday(target_weekday: int = 0, weeks_ahead: int = 1) -> date:
    """A future date guaranteed to fall on `target_weekday` (0=Monday)."""
    today = date.today()
    days_ahead = target_weekday - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead, weeks=weeks_ahead - 1)


def register_and_login(client, email, password, full_name, role):
    r = client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": full_name, "role": role
    })
    assert r.status_code in (200, 201), r.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def login(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user"]


def jobs_for(db, appointment_id, notification_type=None):
    q = db.query(NotificationJob).filter(NotificationJob.appointment_id == appointment_id)
    if notification_type:
        q = q.filter(NotificationJob.notification_type == notification_type)
    return q.all()


def calendar_rows_for(db, appointment_id):
    return db.query(CalendarEvent).filter(
        CalendarEvent.appointment_id == appointment_id
    ).order_by(CalendarEvent.recipient_type).all()


def assert_events_exist_for(db, provider, appointment_id, expected=2):
    """Assert THIS appointment's external events exist in the provider.

    Deliberately scoped rather than asserting on the provider's total size:
    the workers process every due row in the shared test database, so other
    tests' rows legitimately land in the same provider (see
    second-brain/05_KNOWN_ISSUES.md on test-DB leakage).
    """
    ids = {r.external_event_id for r in calendar_rows_for(db, appointment_id)}
    assert len(ids) == expected
    assert ids <= set(provider.events.keys()), "this appointment's events missing from provider"
    return ids


class RecordingEmailProvider(EmailProvider):
    def __init__(self):
        self.sent = []

    def send(self, to_email, subject, body):
        self.sent.append({"to": to_email, "subject": subject, "body": body})


class FailingEmailProvider(EmailProvider):
    def __init__(self, exc):
        self._exc = exc
        self.attempts = 0

    def send(self, to_email, subject, body):
        self.attempts += 1
        raise self._exc


class FailingAIProvider(AIProvider):
    def __init__(self, exc):
        self._exc = exc

    def generate_pre_visit_summary(self, symptoms):
        raise self._exc

    def generate_post_visit_summary(self, notes):
        raise self._exc


class FixedAIProvider(AIProvider):
    def __init__(self, pre=None, post=None):
        self._pre, self._post = pre, post

    def generate_pre_visit_summary(self, symptoms):
        return self._pre

    def generate_post_visit_summary(self, notes):
        return self._post


class FailingCalendarProvider(MockCalendarProvider):
    def __init__(self, exc):
        super().__init__()
        self._exc = exc

    def create_event(self, event_id, summary, description, start_time, end_time, attendee_email=None):
        raise self._exc

    def update_event(self, external_event_id, summary, description, start_time, end_time):
        raise self._exc

    def delete_event(self, external_event_id):
        raise self._exc


def run_notification_worker(db, provider):
    import workers.notification_worker as mod
    original = mod.notification_service
    mod.notification_service = NotificationService(provider=provider)
    try:
        return NotificationWorker(batch_size=500).run_once(db)
    finally:
        mod.notification_service = original


def run_calendar_worker(db, provider):
    import workers.calendar_worker as mod
    original = mod.calendar_service
    mod.calendar_service = CalendarService(provider=provider)
    try:
        return CalendarWorker(batch_size=500).run_once(db)
    finally:
        mod.calendar_service = original


def with_ai_provider(provider):
    """Swap the AIService used by the API layer for one bound to a test double."""
    import app.api.ai as mod
    original = mod.ai_service
    mod.ai_service = AIService(provider=provider)
    return original


def restore_ai_service(original):
    import app.api.ai as mod
    mod.ai_service = original


@pytest.fixture
def clinic(client):
    """Admin + configured doctor + patient, created through the real API."""
    suffix = datetime.now(timezone.utc).strftime("%H%M%S%f")
    admin_headers, admin = register_and_login(
        client, f"admin_e2e_{suffix}@example.com", "password123", "E2E Admin", "ADMIN"
    )

    doc = client.post("/api/v1/admin/doctors", json={
        "email": f"doc_e2e_{suffix}@example.com", "password": "password123",
        "full_name": "Dr. E2E", "specialization": "Cardiology", "slot_duration_minutes": 30,
    }, headers=admin_headers)
    assert doc.status_code == 201, doc.text
    doctor = doc.json()

    sched = client.post(f"/api/v1/admin/doctors/{doctor['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": d, "start_time": "09:00:00", "end_time": "13:00:00", "is_active": True}
            for d in range(5)
        ]
    }, headers=admin_headers)
    assert sched.status_code == 200, sched.text

    doctor_headers, doctor_user = login(client, f"doc_e2e_{suffix}@example.com", "password123")
    patient_headers, patient = register_and_login(
        client, f"patient_e2e_{suffix}@example.com", "password123", "E2E Patient", "PATIENT"
    )

    return {
        "admin_headers": admin_headers, "admin": admin,
        "doctor_headers": doctor_headers, "doctor": doctor, "doctor_user": doctor_user,
        "patient_headers": patient_headers, "patient": patient,
        "suffix": suffix,
    }


def pick_slot(client, doctor_id, day: date, index: int = 0):
    r = client.get(f"/api/v1/doctors/{doctor_id}/slots", params={"date": day.isoformat()})
    assert r.status_code == 200, r.text
    available = [s for s in r.json()["slots"] if s["is_available"]]
    assert len(available) > index, f"expected >{index} available slots, got {len(available)}"
    return available[index]


# ===========================================================================
# WORKFLOW 1 — PATIENT BOOKING
# register -> login -> search doctor -> select slot -> hold -> symptoms
# -> pre-visit AI summary -> confirm -> notification jobs -> calendar jobs
# ===========================================================================

def test_e2e_patient_booking_workflow(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    day = next_weekday(0)

    # --- search doctor by specialisation (HTTP + resulting state) ---
    search = client.get("/api/v1/doctors", params={"specialization": "Cardiology"})
    assert search.status_code == 200
    assert doctor_id in [d["id"] for d in search.json()]

    # --- select slot ---
    slot = pick_slot(client, doctor_id, day)

    # --- hold slot (HTTP + DB state) ---
    hold_resp = client.post("/api/v1/slots/holds", json={
        "doctor_id": doctor_id,
        "start_time": slot["start_time"],
        "end_time": slot["end_time"],
    }, headers=patient_headers)
    assert hold_resp.status_code == 201, hold_resp.text
    hold = hold_resp.json()

    hold_row = db_session.query(AppointmentHold).filter(AppointmentHold.id == hold["id"]).first()
    assert hold_row is not None and hold_row.is_active is True

    # the held slot must no longer be offered as available
    after_hold = client.get(f"/api/v1/doctors/{doctor_id}/slots", params={"date": day.isoformat()})
    still_available = [s["start_time"] for s in after_hold.json()["slots"] if s["is_available"]]
    assert slot["start_time"] not in still_available

    # --- confirm appointment from the hold ---
    appt_resp = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "hold_id": hold["id"],
    }, headers=patient_headers)
    assert appt_resp.status_code == 201, appt_resp.text
    appt = appt_resp.json()
    assert appt["status"] == AppointmentStatus.CONFIRMED.value

    # DB state: appointment persisted, hold consumed
    appt_row = db_session.query(Appointment).filter(Appointment.id == appt["id"]).first()
    assert appt_row is not None
    assert appt_row.status == AppointmentStatus.CONFIRMED
    db_session.refresh(hold_row)
    assert hold_row.is_active is False

    # --- symptoms + pre-visit AI summary ---
    sym = client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Severe chest pain and shortness of breath for two days.",
    }, headers=patient_headers)
    assert sym.status_code == 201, sym.text

    ai = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=patient_headers)
    assert ai.status_code == 200, ai.text
    ai_body = ai.json()
    assert ai_body["status"] == AISummaryStatus.SUCCESS.value
    assert ai_body["payload"]["urgency"] in ("Low", "Medium", "High")
    assert len(ai_body["payload"]["suggested_questions"]) == 3

    # DB state: summary persisted and linked to the appointment
    summary_row = db_session.query(AISummary).filter(
        AISummary.appointment_id == appt["id"], AISummary.type == AISummaryType.PRE_VISIT
    ).first()
    assert summary_row is not None and summary_row.status == AISummaryStatus.SUCCESS

    # --- background jobs: booking confirmation to BOTH parties + reminders ---
    confirmations = jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    assert len(confirmations) == 2
    assert {j.recipient_id for j in confirmations} == {appt["patient_id"], appt["doctor_id"]}
    assert all(j.status == NotificationStatus.PENDING for j in confirmations)

    reminders = jobs_for(db_session, appt["id"], NotificationType.APPOINTMENT_REMINDER)
    assert len(reminders) == 2

    # --- calendar jobs created for both participants ---
    cal_rows = calendar_rows_for(db_session, appt["id"])
    assert len(cal_rows) == 2
    assert {r.recipient_type for r in cal_rows} == {"PATIENT", "DOCTOR"}
    assert all(r.pending_operation == CalendarOperation.CREATE for r in cal_rows)

    # --- provider interaction: workers actually deliver ---
    email = RecordingEmailProvider()
    run_notification_worker(db_session, email)
    for job in jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION):
        db_session.refresh(job)
        assert job.status == NotificationStatus.SENT
    assert len(email.sent) >= 2

    calendar = MockCalendarProvider()
    run_calendar_worker(db_session, calendar)
    for row in calendar_rows_for(db_session, appt["id"]):
        db_session.refresh(row)
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.external_event_id is not None
    assert_events_exist_for(db_session, calendar, appt["id"])


# ===========================================================================
# WORKFLOW 2 — DOCTOR WORKFLOW
# login -> view appointment -> view pre-visit summary -> consultation
# -> prescription -> post-visit summary -> medication reminder jobs
# ===========================================================================

def test_e2e_doctor_workflow(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers, doctor_headers = clinic["patient_headers"], clinic["doctor_headers"]
    day = next_weekday(1)

    slot = pick_slot(client, doctor_id, day)
    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report",
                json={"symptoms": "Mild persistent cough."}, headers=patient_headers)
    client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=patient_headers)

    # --- doctor views the appointment and the pre-visit summary ---
    view = client.get(f"/api/v1/appointments/{appt['id']}", headers=doctor_headers)
    assert view.status_code == 200
    pre = client.get(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=doctor_headers)
    assert pre.status_code == 200
    assert pre.json()["status"] == AISummaryStatus.SUCCESS.value

    # --- consultation + prescription ---
    consult = client.post(f"/api/v1/appointments/{appt['id']}/consultation", json={
        "notes": "Viral upper respiratory infection. Rest and fluids advised.",
        "prescription_instructions": "Take after meals.",
        "medications": [
            {"name": "Paracetamol", "dosage": "500mg", "frequency": "Twice daily", "duration_days": 3},
            {"name": "Cough syrup", "dosage": "10ml", "frequency": "At night", "duration_days": 2},
        ],
    }, headers=doctor_headers)
    assert consult.status_code == 201, consult.text

    # DB state: consultation + prescription + medications persisted
    consult_row = db_session.query(Consultation).filter(
        Consultation.appointment_id == appt["id"]
    ).first()
    assert consult_row is not None
    assert consult_row.prescription is not None
    meds = db_session.query(Medication).filter(
        Medication.prescription_id == consult_row.prescription.id
    ).all()
    assert {m.name for m in meds} == {"Paracetamol", "Cough syrup"}

    # --- medication reminder jobs created from the prescription ---
    med_jobs = jobs_for(db_session, appt["id"], NotificationType.MEDICATION_REMINDER)
    assert len(med_jobs) == 5  # 3 days + 2 days
    assert all(j.recipient_id == appt["patient_id"] for j in med_jobs)
    assert all(j.next_retry_at is not None for j in med_jobs)  # scheduled for the future

    # --- post-visit AI summary ---
    post = client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doctor_headers)
    assert post.status_code == 200, post.text
    assert post.json()["status"] == AISummaryStatus.SUCCESS.value
    payload = post.json()["payload"]
    assert payload["summary"] and payload["medication_schedule"] and payload["follow_up_steps"]

    # resulting state: the patient can read their own post-visit summary
    patient_view = client.get(
        f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=patient_headers
    )
    assert patient_view.status_code == 200
    assert patient_view.json()["payload"] == payload


# ===========================================================================
# WORKFLOW 3 — ADMIN WORKFLOW
# login -> create doctor -> working hours -> slot duration -> leave
# -> detect conflicts -> notification jobs
# ===========================================================================

def test_e2e_admin_workflow(client, db_session, clinic):
    admin_headers = clinic["admin_headers"]
    patient_headers = clinic["patient_headers"]
    suffix = clinic["suffix"]

    # --- create + configure a brand new doctor ---
    created = client.post("/api/v1/admin/doctors", json={
        "email": f"newdoc_{suffix}@example.com", "password": "password123",
        "full_name": "Dr. Fresh", "specialization": "Neurology", "slot_duration_minutes": 60,
    }, headers=admin_headers)
    assert created.status_code == 201, created.text
    new_doc = created.json()
    assert new_doc["slot_duration_minutes"] == 60

    day = next_weekday(2)
    sched = client.post(f"/api/v1/admin/doctors/{new_doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 2, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}
        ]
    }, headers=admin_headers)
    assert sched.status_code == 200

    # slot duration is respected by the slot engine (60 min over 3h = 3 slots)
    slots = client.get(f"/api/v1/doctors/{new_doc['id']}/slots", params={"date": day.isoformat()})
    assert slots.json()["slot_duration_minutes"] == 60
    assert slots.json()["total_slots"] == 3

    # --- change slot duration and confirm it takes effect ---
    updated = client.put(f"/api/v1/admin/doctors/{new_doc['id']}", json={
        "slot_duration_minutes": 30
    }, headers=admin_headers)
    assert updated.status_code == 200
    slots = client.get(f"/api/v1/doctors/{new_doc['id']}/slots", params={"date": day.isoformat()})
    assert slots.json()["total_slots"] == 6

    # --- a patient books, then admin marks that day as leave ---
    slot = pick_slot(client, new_doc["id"], day)
    appt = client.post("/api/v1/appointments", json={
        "doctor_id": new_doc["id"], "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    leave = client.post(f"/api/v1/admin/doctors/{new_doc['id']}/leaves", json={
        "leave_date": day.isoformat(), "reason": "Conference",
    }, headers=admin_headers)
    assert leave.status_code == 201, leave.text

    # --- conflict detection: DB state + resulting state ---
    appt_row = db_session.query(Appointment).filter(Appointment.id == appt["id"]).first()
    db_session.refresh(appt_row)
    assert appt_row.status == AppointmentStatus.CONFLICTED
    # original booking information preserved, not deleted
    assert ensure_utc(appt_row.start_time) == ensure_utc(datetime.fromisoformat(slot["start_time"]))

    # admin can inspect conflicted appointments through the API
    listed = client.get("/api/v1/appointments", params={"status": "CONFLICTED"}, headers=admin_headers)
    assert listed.status_code == 200
    assert appt["id"] in [a["id"] for a in listed.json()]

    # --- notification jobs created for the affected patient ---
    conflict_jobs = jobs_for(db_session, appt["id"], NotificationType.DOCTOR_LEAVE_CONFLICT)
    assert len(conflict_jobs) == 1
    assert conflict_jobs[0].recipient_id == appt["patient_id"]
    assert conflict_jobs[0].status == NotificationStatus.PENDING

    # --- authorization: a patient cannot perform admin operations ---
    forbidden = client.post("/api/v1/admin/doctors", json={
        "email": f"nope_{suffix}@example.com", "password": "password123",
        "full_name": "Nope", "specialization": "X", "slot_duration_minutes": 30,
    }, headers=patient_headers)
    assert forbidden.status_code == 403


# ===========================================================================
# WORKFLOW 4 — RESCHEDULE
# existing appointment -> new slot -> revalidate -> update -> update calendar
# -> required notifications
# ===========================================================================

def test_e2e_reschedule_workflow(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    day = next_weekday(3)

    slot = pick_slot(client, doctor_id, day, 0)
    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    # sync the calendar so we have real external events to update
    calendar = MockCalendarProvider()
    run_calendar_worker(db_session, calendar)
    original_ids = {r.recipient_type: r.external_event_id for r in calendar_rows_for(db_session, appt["id"])}
    assert all(original_ids.values())

    new_slot = pick_slot(client, doctor_id, day, 1)

    # --- reschedule (HTTP + resulting state) ---
    resched = client.post(f"/api/v1/appointments/{appt['id']}/reschedule", json={
        "new_start_time": new_slot["start_time"], "new_end_time": new_slot["end_time"],
    }, headers=patient_headers)
    assert resched.status_code == 200, resched.text
    assert resched.json()["status"] == AppointmentStatus.RESCHEDULED.value

    # DB state: same row updated, not duplicated
    rows = db_session.query(Appointment).filter(Appointment.id == appt["id"]).all()
    assert len(rows) == 1
    db_session.refresh(rows[0])
    assert ensure_utc(rows[0].start_time) == ensure_utc(datetime.fromisoformat(new_slot["start_time"]))
    assert db_session.query(Appointment).filter(
        Appointment.patient_id == appt["patient_id"]
    ).count() == 1

    # --- calendar updated in place, not duplicated ---
    cal_rows = calendar_rows_for(db_session, appt["id"])
    assert all(r.pending_operation == CalendarOperation.UPDATE for r in cal_rows)
    run_calendar_worker(db_session, calendar)
    for row in calendar_rows_for(db_session, appt["id"]):
        db_session.refresh(row)
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.external_event_id == original_ids[row.recipient_type]
    # scoped to this appointment's events — the worker also processes other
    # tests' rows into the same provider (see assert_events_exist_for)
    our_ids = assert_events_exist_for(db_session, calendar, appt["id"])
    for event_id in our_ids:
        assert ensure_utc(calendar.events[event_id]["start_time"]) == ensure_utc(
            datetime.fromisoformat(new_slot["start_time"])
        )

    # --- required notifications for the new time (patient + doctor) ---
    confirmations = jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    # 2 from the original booking + 2 announcing the new time
    assert len(confirmations) == 4
    recent = sorted(confirmations, key=lambda j: j.created_at)[-2:]
    assert {j.recipient_id for j in recent} == {appt["patient_id"], appt["doctor_id"]}

    # --- stale reminders for the OLD time must not still be pending ---
    reminders = jobs_for(db_session, appt["id"], NotificationType.APPOINTMENT_REMINDER)
    pending = [j for j in reminders if j.status == NotificationStatus.PENDING]
    assert len(pending) == 2, "expected exactly the 2 reminders for the new time to be pending"
    for job in pending:
        assert ensure_utc(job.next_retry_at) == ensure_utc(
            datetime.fromisoformat(new_slot["start_time"])
        ) - timedelta(hours=24)


# ===========================================================================
# WORKFLOW 5 — CANCELLATION
# existing appointment -> cancel -> release slot -> state -> delete calendar
# -> cancellation notifications
# ===========================================================================

def test_e2e_cancellation_workflow(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    day = next_weekday(4)

    slot = pick_slot(client, doctor_id, day)
    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    calendar = MockCalendarProvider()
    run_calendar_worker(db_session, calendar)
    cancelled_event_ids = assert_events_exist_for(db_session, calendar, appt["id"])

    # --- cancel ---
    cancel = client.post(f"/api/v1/appointments/{appt['id']}/cancel",
                         json={"cancellation_reason": "Feeling better"}, headers=patient_headers)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == AppointmentStatus.CANCELLED.value

    # --- DB state ---
    appt_row = db_session.query(Appointment).filter(Appointment.id == appt["id"]).first()
    db_session.refresh(appt_row)
    assert appt_row.status == AppointmentStatus.CANCELLED

    # --- slot released: it is offered as available again ---
    after = client.get(f"/api/v1/doctors/{doctor_id}/slots", params={"date": day.isoformat()})
    available = [s["start_time"] for s in after.json()["slots"] if s["is_available"]]
    assert slot["start_time"] in available

    # ...and is genuinely re-bookable by someone else
    other_headers, _ = register_and_login(
        client, f"other_{clinic['suffix']}@example.com", "password123", "Other Patient", "PATIENT"
    )
    rebook = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=other_headers)
    assert rebook.status_code == 201, rebook.text

    # --- calendar events deleted ---
    cal_rows = calendar_rows_for(db_session, appt["id"])
    assert all(r.pending_operation == CalendarOperation.DELETE for r in cal_rows)
    run_calendar_worker(db_session, calendar)
    for row in calendar_rows_for(db_session, appt["id"]):
        db_session.refresh(row)
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.external_event_id is None
    # This appointment's external events are gone. (Events belonging to the
    # re-booking above legitimately remain in the provider, so assert on the
    # specific ids rather than on the provider being empty.)
    assert cancelled_event_ids.isdisjoint(set(calendar.events.keys()))

    # --- cancellation notifications to both parties ---
    cancels = jobs_for(db_session, appt["id"], NotificationType.CANCELLATION)
    assert len(cancels) == 2
    assert {j.recipient_id for j in cancels} == {appt["patient_id"], appt["doctor_id"]}

    # --- stale reminders for a cancelled appointment must not stay pending ---
    reminders = jobs_for(db_session, appt["id"], NotificationType.APPOINTMENT_REMINDER)
    assert not [j for j in reminders if j.status == NotificationStatus.PENDING], (
        "reminders for a cancelled appointment must not remain pending"
    )


# ===========================================================================
# FAILURE TESTS
# ===========================================================================

def test_e2e_failure_llm_unavailable_appointment_stays_valid(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    slot = pick_slot(client, doctor_id, next_weekday(0))

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report",
                json={"symptoms": "Headache."}, headers=patient_headers)

    original = with_ai_provider(FailingAIProvider(AIProviderUnavailableError("LLM down")))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=patient_headers)
    finally:
        restore_ai_service(original)

    assert r.status_code == 200
    assert r.json()["status"] == AISummaryStatus.FAILED.value

    # appointment untouched and still fully usable
    check = client.get(f"/api/v1/appointments/{appt['id']}", headers=patient_headers)
    assert check.json()["status"] == AppointmentStatus.CONFIRMED.value
    # booking notifications and calendar work were unaffected
    assert len(jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)) == 2
    assert len(calendar_rows_for(db_session, appt["id"])) == 2


def test_e2e_failure_invalid_ai_response_recorded_not_crashed(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    slot = pick_slot(client, doctor_id, next_weekday(1))

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report",
                json={"symptoms": "Fatigue."}, headers=patient_headers)

    bad = {"urgency": "Critical", "chief_complaint": "Fatigue", "suggested_questions": ["only one"]}
    original = with_ai_provider(FixedAIProvider(pre=bad))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=patient_headers)
    finally:
        restore_ai_service(original)

    assert r.status_code == 200
    assert r.json()["status"] == AISummaryStatus.FAILED.value
    assert "Invalid AI response schema" in r.json()["error_message"]

    row = db_session.query(AISummary).filter(
        AISummary.appointment_id == appt["id"], AISummary.type == AISummaryType.PRE_VISIT
    ).first()
    assert row.status == AISummaryStatus.FAILED
    assert row.payload is None


def test_e2e_failure_email_unavailable_retries_without_touching_appointment(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    slot = pick_slot(client, doctor_id, next_weekday(2))

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    failing = FailingEmailProvider(EmailProviderTransientError("SMTP unreachable"))
    run_notification_worker(db_session, failing)
    assert failing.attempts >= 2

    for job in jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION):
        db_session.refresh(job)
        assert job.status == NotificationStatus.PENDING  # queued for retry, not lost
        assert job.attempts == 1
        assert "unreachable" in job.last_error
        assert job.next_retry_at is not None

    # appointment integrity is untouched by the email outage
    assert client.get(f"/api/v1/appointments/{appt['id']}",
                      headers=patient_headers).json()["status"] == AppointmentStatus.CONFIRMED.value

    # and a later run with a healthy provider delivers
    for job in jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION):
        job.next_retry_at = None
    db_session.commit()

    healthy = RecordingEmailProvider()
    run_notification_worker(db_session, healthy)
    for job in jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION):
        db_session.refresh(job)
        assert job.status == NotificationStatus.SENT


def test_e2e_failure_calendar_unavailable_does_not_invalidate_appointment(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    slot = pick_slot(client, doctor_id, next_weekday(3))

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    run_calendar_worker(db_session, FailingCalendarProvider(CalendarProviderTransientError("Google down")))

    for row in calendar_rows_for(db_session, appt["id"]):
        db_session.refresh(row)
        assert row.status == CalendarSyncStatus.PENDING_SYNC  # retryable
        assert row.attempts == 1
        assert "Google down" in row.last_error

    assert client.get(f"/api/v1/appointments/{appt['id']}",
                      headers=patient_headers).json()["status"] == AppointmentStatus.CONFIRMED.value

    # recovery: a healthy provider completes the sync
    for row in calendar_rows_for(db_session, appt["id"]):
        row.next_retry_at = None
    db_session.commit()

    healthy = MockCalendarProvider()
    run_calendar_worker(db_session, healthy)
    for row in calendar_rows_for(db_session, appt["id"]):
        db_session.refresh(row)
        assert row.status == CalendarSyncStatus.SYNCED
    assert_events_exist_for(db_session, healthy, appt["id"])


def test_e2e_failure_expired_hold_cannot_be_confirmed(client, db_session, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    day = next_weekday(4)
    slot = pick_slot(client, doctor_id, day)

    hold = client.post("/api/v1/slots/holds", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    hold_row = db_session.query(AppointmentHold).filter(AppointmentHold.id == hold["id"]).first()
    hold_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    r = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "hold_id": hold["id"],
    }, headers=patient_headers)
    assert r.status_code == 422

    # no appointment, no jobs, no calendar rows were created by the failed attempt
    assert db_session.query(Appointment).filter(
        Appointment.patient_id == clinic["patient"]["id"]
    ).count() == 0

    # and the slot is free for someone else
    after = client.get(f"/api/v1/doctors/{doctor_id}/slots", params={"date": day.isoformat()})
    assert slot["start_time"] in [s["start_time"] for s in after.json()["slots"] if s["is_available"]]


def test_e2e_failure_simultaneous_booking_attempts(client, db_session, clinic):
    """Two sequential attempts on the same slot: exactly one wins.

    The 100-thread contention case lives in test_concurrency.py; this asserts
    the integration-level outcome — a losing booking produces a clean 409 and
    creates no partial state (no appointment, no jobs, no calendar rows).
    """
    doctor_id = clinic["doctor"]["id"]
    day = next_weekday(0)
    slot = pick_slot(client, doctor_id, day)

    first_headers = clinic["patient_headers"]
    second_headers, second_user = register_and_login(
        client, f"rival_{clinic['suffix']}@example.com", "password123", "Rival Patient", "PATIENT"
    )

    payload = {"doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"]}
    first = client.post("/api/v1/appointments", json=payload, headers=first_headers)
    second = client.post("/api/v1/appointments", json=payload, headers=second_headers)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error_code"] == "CONFLICT"

    # the loser created nothing at all
    assert db_session.query(Appointment).filter(
        Appointment.patient_id == second_user["id"]
    ).count() == 0
    assert db_session.query(NotificationJob).filter(
        NotificationJob.recipient_id == second_user["id"]
    ).count() == 0


def test_e2e_backend_restart_with_pending_jobs(client, db_session, clinic):
    """
    Red-team scenario: the backend process dies with notification/calendar
    jobs still PENDING, then a new process starts.

    Neither NotificationWorker nor CalendarWorker keep any in-memory queue —
    all state lives in the notification_jobs / calendar_events tables, and
    get_due_jobs()/get_due_syncs() re-derive "what's due" from that state on
    every call. A "restart" is therefore just: construct brand new Worker and
    Service instances (nothing carried over from before) and call run_once()
    against the same persisted rows. If any of this relied on in-memory state,
    the jobs created before the simulated restart would be silently lost here.
    """
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    slot = pick_slot(client, doctor_id, next_weekday(2))

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    # Jobs exist, PENDING, before "the process dies".
    pending_notifications = jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    pending_calendar = calendar_rows_for(db_session, appt["id"])
    assert len(pending_notifications) == 2
    assert all(j.status == NotificationStatus.PENDING for j in pending_notifications)
    assert len(pending_calendar) == 2
    assert all(r.status == CalendarSyncStatus.PENDING_SYNC for r in pending_calendar)

    # --- simulate restart: brand new worker/service/provider instances,
    # zero shared in-memory state with anything above ---
    fresh_email = RecordingEmailProvider()
    fresh_calendar = MockCalendarProvider()
    post_restart_notification_worker = NotificationWorker(batch_size=500)
    post_restart_calendar_worker = CalendarWorker(batch_size=500)

    import workers.notification_worker as notif_mod
    import workers.calendar_worker as cal_mod
    notif_mod.notification_service = NotificationService(provider=fresh_email)
    cal_mod.calendar_service = CalendarService(provider=fresh_calendar)

    notif_stats = post_restart_notification_worker.run_once(db_session)
    cal_stats = post_restart_calendar_worker.run_once(db_session)

    assert notif_stats["claimed"] >= 2
    assert cal_stats["claimed"] >= 2

    for job in jobs_for(db_session, appt["id"], NotificationType.BOOKING_CONFIRMATION):
        db_session.refresh(job)
        assert job.status == NotificationStatus.SENT
    for row in calendar_rows_for(db_session, appt["id"]):
        db_session.refresh(row)
        assert row.status == CalendarSyncStatus.SYNCED
        assert row.external_event_id is not None

    # the appointment itself was never at risk regardless of when the process died
    assert client.get(f"/api/v1/appointments/{appt['id']}",
                      headers=patient_headers).json()["status"] == AppointmentStatus.CONFIRMED.value


def test_e2e_no_external_service_required_for_appointment_integrity(client, db_session, clinic):
    """Acceptance criterion: no external service is required for core
    appointment integrity.

    Runs the complete book -> reschedule -> cancel lifecycle with the LLM,
    email, and calendar providers all failing simultaneously, and asserts the
    appointment state machine is unaffected end to end.
    """
    doctor_id = clinic["doctor"]["id"]
    patient_headers = clinic["patient_headers"]
    day = next_weekday(2)

    slot = pick_slot(client, doctor_id, day, 0)
    new_slot = pick_slot(client, doctor_id, day, 1)

    dead_ai = FailingAIProvider(AIProviderTimeoutError("LLM timeout"))
    dead_email = FailingEmailProvider(EmailProviderTransientError("SMTP down"))
    dead_calendar = FailingCalendarProvider(CalendarProviderTransientError("Calendar down"))

    original_ai = with_ai_provider(dead_ai)
    try:
        # --- BOOK ---
        booked = client.post("/api/v1/appointments", json={
            "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
        }, headers=patient_headers)
        assert booked.status_code == 201, booked.text
        appt = booked.json()
        assert appt["status"] == AppointmentStatus.CONFIRMED.value

        # AI fails, but the appointment does not
        client.post(f"/api/v1/appointments/{appt['id']}/symptom-report",
                    json={"symptoms": "Chest discomfort."}, headers=patient_headers)
        ai = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary",
                         headers=patient_headers)
        assert ai.status_code == 200
        assert ai.json()["status"] == AISummaryStatus.FAILED.value

        # both workers fail against dead providers
        run_notification_worker(db_session, dead_email)
        run_calendar_worker(db_session, dead_calendar)

        # --- RESCHEDULE ---
        resched = client.post(f"/api/v1/appointments/{appt['id']}/reschedule", json={
            "new_start_time": new_slot["start_time"], "new_end_time": new_slot["end_time"],
        }, headers=patient_headers)
        assert resched.status_code == 200, resched.text
        assert resched.json()["status"] == AppointmentStatus.RESCHEDULED.value

        # --- CANCEL ---
        cancelled = client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient_headers)
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == AppointmentStatus.CANCELLED.value
    finally:
        restore_ai_service(original_ai)

    # --- DB state: the appointment moved through the state machine correctly ---
    row = db_session.query(Appointment).filter(Appointment.id == appt["id"]).first()
    db_session.refresh(row)
    assert row.status == AppointmentStatus.CANCELLED
    assert ensure_utc(row.start_time) == ensure_utc(datetime.fromisoformat(new_slot["start_time"]))

    # the slot is released despite every external service being down
    after = client.get(f"/api/v1/doctors/{doctor_id}/slots", params={"date": day.isoformat()})
    assert new_slot["start_time"] in [s["start_time"] for s in after.json()["slots"] if s["is_available"]]

    # failed external work is retained for retry, not lost
    assert jobs_for(db_session, appt["id"], NotificationType.CANCELLATION)
    assert calendar_rows_for(db_session, appt["id"])


# ===========================================================================
# AUTHORIZATION — cross-cutting
# ===========================================================================

def test_e2e_authorization_boundaries(client, clinic):
    doctor_id = clinic["doctor"]["id"]
    patient_headers, doctor_headers = clinic["patient_headers"], clinic["doctor_headers"]
    slot = pick_slot(client, doctor_id, next_weekday(1))

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=patient_headers).json()

    intruder_headers, _ = register_and_login(
        client, f"intruder_{clinic['suffix']}@example.com", "password123", "Intruder", "PATIENT"
    )

    # another patient can neither read nor mutate this appointment
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=intruder_headers).status_code == 403
    assert client.post(f"/api/v1/appointments/{appt['id']}/cancel",
                       headers=intruder_headers).status_code == 403
    assert client.get(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary",
                      headers=intruder_headers).status_code == 403

    # a patient cannot submit a consultation (doctor-only)
    assert client.post(f"/api/v1/appointments/{appt['id']}/consultation",
                       json={"notes": "x", "medications": []},
                       headers=patient_headers).status_code == 403

    # a doctor cannot create a booking (patient-only)
    assert client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id, "start_time": slot["start_time"], "end_time": slot["end_time"],
    }, headers=doctor_headers).status_code == 403

    # unauthenticated access is rejected outright
    assert client.get(f"/api/v1/appointments/{appt['id']}").status_code == 401
