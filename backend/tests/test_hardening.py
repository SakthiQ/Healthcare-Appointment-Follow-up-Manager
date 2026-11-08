"""Tests for: per-doctor timezones, holds that no longer write on read, login
throttling and token revocation, the AI summary cap, SMTP certificate checking,
generic medication reminders, and calendar cleanup when a leave conflicts a booking.

Fixtures and helpers come from test_design_guarantees (file-backed SQLite with an
independent session per request, so rollbacks and commits behave honestly)."""
import ssl
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.datetime_utils import get_zone, local_to_utc
from app.database import get_db
from app.main import app
from models.appointment import AppointmentHold
from tests.test_design_guarantees import (  # noqa: F401  (fixtures are used by name)
    _book, _bookable_slot, _next_monday, _register, isolated_client, isolated_db,
)


def _doctor_in(client, admin, tag, tz, day_of_week, start="09:00:00", end="10:00:00"):
    doctor = client.post("/api/v1/admin/doctors", json={
        "email": f"doc_{tag}@example.com", "password": "password123", "full_name": f"Dr {tag}",
        "specialization": "Cardiology", "slot_duration_minutes": 30, "timezone": tz}, headers=admin)
    assert doctor.status_code == 201, doctor.text
    doctor = doctor.json()
    client.post(f"/api/v1/admin/doctors/{doctor['id']}/schedule", json={"working_hours": [
        {"day_of_week": day_of_week, "start_time": start, "end_time": end, "is_active": True}]}, headers=admin)
    return doctor


# --------------------------------------------------------------------------
# Timezones
# --------------------------------------------------------------------------

def test_slots_are_generated_in_the_doctors_timezone(isolated_client):
    client = isolated_client
    admin = _register(client, "admin_tzslots@example.com", "ADMIN")
    doctor = _doctor_in(client, admin, "tzslots", "Asia/Kolkata", 0)  # Monday 09:00-10:00 IST
    assert doctor["timezone"] == "Asia/Kolkata"

    monday = _next_monday()
    body = client.get(f"/api/v1/doctors/{doctor['id']}/slots", params={"date": monday.isoformat()}).json()

    starts = [datetime.fromisoformat(s["start_time"]).astimezone(timezone.utc) for s in body["slots"]]
    day = datetime.combine(monday, time(0, 0), tzinfo=timezone.utc)
    assert starts == [day + timedelta(hours=3, minutes=30), day + timedelta(hours=4)]  # 09:00 / 09:30 IST
    assert body["timezone"] == "Asia/Kolkata"


def test_booking_boundaries_use_the_doctors_timezone(isolated_client):
    client = isolated_client
    admin = _register(client, "admin_tzbook@example.com", "ADMIN")
    doctor = _doctor_in(client, admin, "tzbook", "Asia/Kolkata", 0)
    patient = _register(client, "patient_tzbook@example.com", "PATIENT")
    monday = _next_monday()

    # 09:00 UTC is 14:30 in Kolkata: outside 09:00-10:00 local.
    wrong = datetime.combine(monday, time(9, 0), tzinfo=timezone.utc)
    rejected = client.post("/api/v1/appointments", json={
        "doctor_id": doctor["id"], "start_time": wrong.isoformat(),
        "end_time": (wrong + timedelta(minutes=30)).isoformat()}, headers=patient)
    assert rejected.status_code == 422

    right = local_to_utc(monday, time(9, 0), get_zone("Asia/Kolkata"))
    booked = _book(client, doctor, patient, right, right + timedelta(minutes=30))
    assert booked["doctor_timezone"] == "Asia/Kolkata"


def test_leave_covers_the_doctors_local_day_not_the_utc_day(isolated_client):
    """Tuesday 00:00-00:30 in Kolkata is Monday 18:30 UTC. A leave on Tuesday must
    conflict it, which a UTC-day window would miss."""
    client = isolated_client
    admin = _register(client, "admin_tzleave@example.com", "ADMIN")
    doctor = _doctor_in(client, admin, "tzleave", "Asia/Kolkata", 1, start="00:00:00", end="02:00:00")
    patient = _register(client, "patient_tzleave@example.com", "PATIENT")
    tuesday = _next_monday() + timedelta(days=1)

    start = local_to_utc(tuesday, time(0, 0), get_zone("Asia/Kolkata"))
    assert start.date() == tuesday - timedelta(days=1)  # the UTC date really is Monday
    appt = _book(client, doctor, patient, start, start + timedelta(minutes=30))

    leave = client.post(f"/api/v1/admin/doctors/{doctor['id']}/leaves", json={
        "leave_date": tuesday.isoformat(), "reason": "conference"}, headers=admin)
    assert leave.status_code == 201, leave.text
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=patient).json()["status"] == "CONFLICTED"


def test_unknown_timezone_is_rejected(isolated_client):
    client = isolated_client
    admin = _register(client, "admin_tzbad@example.com", "ADMIN")
    bad = client.post("/api/v1/admin/doctors", json={
        "email": "doc_tzbad@example.com", "password": "password123", "full_name": "Dr Bad",
        "specialization": "Cardiology", "timezone": "Mars/Olympus"}, headers=admin)
    assert bad.status_code == 422

    doctor = _doctor_in(client, admin, "tzgood", "UTC", 0)
    updated = client.put(f"/api/v1/admin/doctors/{doctor['id']}", json={"timezone": "Europe/London"}, headers=admin)
    assert updated.status_code == 200 and updated.json()["timezone"] == "Europe/London"
    assert client.put(f"/api/v1/admin/doctors/{doctor['id']}", json={"timezone": "nope"}, headers=admin).status_code == 422


def test_dst_day_is_the_right_length():
    from datetime import date
    from app.core.datetime_utils import local_day_bounds_utc

    start, end = local_day_bounds_utc(date(2030, 3, 10), get_zone("America/New_York"))  # clocks go forward
    assert end - start == timedelta(hours=23)


# --------------------------------------------------------------------------
# Emails
# --------------------------------------------------------------------------

def test_booking_confirmation_email_shows_the_doctors_local_time(isolated_client, isolated_db, monkeypatch):
    import workers.notification_worker as worker_module
    from providers.email_provider import MockEmailProvider
    from services.notification_service import NotificationService

    client = isolated_client
    admin = _register(client, "admin_mail@example.com", "ADMIN")
    doctor = _doctor_in(client, admin, "mail", "Asia/Kolkata", 0)
    patient = _register(client, "patient_mail@example.com", "PATIENT")
    start = local_to_utc(_next_monday(), time(9, 0), get_zone("Asia/Kolkata"))
    _book(client, doctor, patient, start, start + timedelta(minutes=30))

    provider = MockEmailProvider()
    monkeypatch.setattr(worker_module, "notification_service", NotificationService(provider=provider))
    with isolated_db() as session:
        worker_module.NotificationWorker().run_once(session)

    confirmations = [m for m in provider.sent_emails if m["subject"] == "Appointment Confirmed"]
    assert confirmations and all("09:00 IST" in m["body"] for m in confirmations)


def test_medication_reminder_email_does_not_name_the_drug():
    from services.notification_service import notification_service

    job = SimpleNamespace(
        notification_type="MEDICATION_REMINDER", appointment_id=None,
        payload='{"medication_name": "Sertraline", "dosage": "50mg", "frequency": "Once daily"}')
    from models.notification import NotificationType
    job.notification_type = NotificationType.MEDICATION_REMINDER

    subject, body = notification_service._build_content(None, job)
    assert subject == "Medication Reminder"
    for secret in ("Sertraline", "50mg", "Once daily"):
        assert secret not in body


def test_smtp_connection_verifies_the_server_certificate(monkeypatch):
    import smtplib
    from providers.email_provider import RealEmailProvider

    seen = {}

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **kwargs): seen.update(kwargs)
        def login(self, *a): pass
        def sendmail(self, *a): pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    RealEmailProvider().send("someone@example.com", "subject", "body")

    context = seen.get("context")
    assert isinstance(context, ssl.SSLContext), "starttls must be given an explicit context"
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname is True


# --------------------------------------------------------------------------
# Holds
# --------------------------------------------------------------------------

def _hold_body(doctor, start):
    return {"doctor_id": doctor["id"], "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat()}


def _expire_in_db(isolated_db, hold_id):
    with isolated_db() as session:
        session.get(AppointmentHold, hold_id).expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()


def test_reading_an_expired_hold_does_not_write(isolated_client, isolated_db):
    admin, doctor, patient, start, _ = _bookable_slot(isolated_client, "holdread")
    hold = isolated_client.post("/api/v1/slots/holds", json=_hold_body(doctor, start), headers=patient).json()
    _expire_in_db(isolated_db, hold["id"])

    shown = isolated_client.get(f"/api/v1/slots/holds/{hold['id']}", headers=patient).json()

    assert shown["is_active"] is False  # reported as what it effectively is
    with isolated_db() as session:
        assert session.get(AppointmentHold, hold["id"]).is_active is True  # but the read changed nothing


def test_an_expired_hold_does_not_block_a_new_hold_on_the_slot(isolated_client, isolated_db):
    admin, doctor, first, start, _ = _bookable_slot(isolated_client, "holdreuse")
    second = _register(isolated_client, "second_holdreuse@example.com", "PATIENT")
    hold = isolated_client.post("/api/v1/slots/holds", json=_hold_body(doctor, start), headers=first).json()
    _expire_in_db(isolated_db, hold["id"])

    again = isolated_client.post("/api/v1/slots/holds", json=_hold_body(doctor, start), headers=second)

    assert again.status_code == 201, again.text


def test_hold_expiry_worker_sweeps_expired_holds(isolated_client, isolated_db):
    from workers.hold_worker import hold_expiry_worker

    admin, doctor, patient, start, _ = _bookable_slot(isolated_client, "holdsweep")
    hold = isolated_client.post("/api/v1/slots/holds", json=_hold_body(doctor, start), headers=patient).json()
    _expire_in_db(isolated_db, hold["id"])

    with isolated_db() as session:
        assert hold_expiry_worker.run_once(session)["expired"] == 1
        assert hold_expiry_worker.run_once(session)["expired"] == 0
    with isolated_db() as session:
        assert session.get(AppointmentHold, hold["id"]).is_active is False


# --------------------------------------------------------------------------
# Login throttling and token revocation
# --------------------------------------------------------------------------

def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_repeated_failed_logins_lock_the_client_out(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 3)
    _register(client, "throttle@example.com", "PATIENT")
    _register(client, "bystander@example.com", "PATIENT")

    for _ in range(3):
        assert _login(client, "throttle@example.com", "wrong-password").status_code == 401

    locked = _login(client, "throttle@example.com", "password123")  # even the right password
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert _login(client, "bystander@example.com", "password123").status_code == 200  # other accounts unaffected


def test_unknown_emails_are_throttled_too(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 3)
    for _ in range(3):
        assert _login(client, "nobody@example.com", "whatever1").status_code == 401
    assert _login(client, "nobody@example.com", "whatever1").status_code == 429  # same response shape as a real account


def test_a_successful_login_resets_the_failure_count(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 3)
    _register(client, "reset@example.com", "PATIENT")

    for _ in range(2):
        assert _login(client, "reset@example.com", "wrong-password").status_code == 401
    assert _login(client, "reset@example.com", "password123").status_code == 200
    for _ in range(2):  # would be the 3rd and 4th failure had the count survived
        assert _login(client, "reset@example.com", "wrong-password").status_code == 401
    assert _login(client, "reset@example.com", "password123").status_code == 200


def test_the_lockout_ends(client, db_session, monkeypatch):
    from models.security import LoginThrottle

    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 2)
    _register(client, "expiry@example.com", "PATIENT")
    for _ in range(2):
        _login(client, "expiry@example.com", "wrong-password")
    assert _login(client, "expiry@example.com", "password123").status_code == 429

    for row in db_session.query(LoginThrottle).all():
        row.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    assert _login(client, "expiry@example.com", "password123").status_code == 200


def test_logout_revokes_the_token(client):
    _register(client, "logout@example.com", "PATIENT")
    token = _login(client, "logout@example.com", "password123").json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401  # the copied token is dead
    fresh = _login(client, "logout@example.com", "password123").json()["access_token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {fresh}"}).status_code == 200


def test_tokens_issued_before_revocation_existed_still_work(client):
    from app.core.security import create_access_token

    user = _register(client, "legacy@example.com", "PATIENT")
    me = client.get("/api/v1/auth/me", headers=user).json()
    legacy = create_access_token({"sub": me["id"], "email": me["email"], "role": me["role"]})  # no "tv"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"}).status_code == 200


# --------------------------------------------------------------------------
# AI
# --------------------------------------------------------------------------

def _appointment_with_symptoms(client, tag):
    admin, doctor, patient, start, end = _bookable_slot(client, tag)
    appt = _book(client, doctor, patient, start, end)
    assert client.post(f"/api/v1/appointments/{appt['id']}/symptom-report",
                       json={"symptoms": "mild headache for two days"}, headers=patient).status_code == 201
    return appt, patient


def test_ai_summaries_are_capped_per_appointment(isolated_client, monkeypatch):
    monkeypatch.setattr(settings, "AI_MAX_SUMMARIES_PER_APPOINTMENT", 2)
    appt, patient = _appointment_with_symptoms(isolated_client, "aicap")
    url = f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary"

    assert isolated_client.post(url, headers=patient).status_code == 200
    assert isolated_client.post(url, headers=patient).status_code == 200
    capped = isolated_client.post(url, headers=patient)
    assert capped.status_code == 429


def test_no_database_transaction_is_held_during_the_llm_call(isolated_client, isolated_db, monkeypatch):
    from services.ai_service import ai_service

    appt, patient = _appointment_with_symptoms(isolated_client, "aiconn")

    sessions = []

    def capturing_get_db():
        db = isolated_db()
        sessions.append(db)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = capturing_get_db

    in_transaction = []

    class WatchingProvider:
        def generate_pre_visit_summary(self, symptoms):
            in_transaction.append(sessions[-1].in_transaction())
            return {"urgency": "Low", "chief_complaint": symptoms,
                    "suggested_questions": ["a?", "b?", "c?"]}

    monkeypatch.setattr(ai_service, "_injected_provider", WatchingProvider())
    response = isolated_client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=patient)

    assert response.status_code == 200, response.text
    assert in_transaction == [False], "the pooled connection must be free while waiting on the LLM"


def test_losing_a_consultation_race_is_a_409(isolated_client, monkeypatch):
    from repositories.clinical_repository import clinical_repository

    admin, doctor, patient, start, end = _bookable_slot(isolated_client, "consrace")
    appt = _book(isolated_client, doctor, patient, start, end)
    doctor_headers = _register_login(isolated_client, f"doc_consrace@example.com")
    body = {"notes": "Routine check.", "prescription_instructions": None, "medications": []}
    url = f"/api/v1/appointments/{appt['id']}/consultation"
    assert isolated_client.post(url, json=body, headers=doctor_headers).status_code == 201

    # A second submission that passed the "already submitted?" check before the first committed.
    monkeypatch.setattr(clinical_repository, "get_consultation", lambda *a, **k: None)
    assert isolated_client.post(url, json=body, headers=doctor_headers).status_code == 409


def _register_login(client, email):
    token = _login(client, email, "password123").json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Calendar
# --------------------------------------------------------------------------

def test_a_leave_conflict_removes_the_calendar_events(isolated_client, isolated_db, monkeypatch):
    import workers.calendar_worker as worker_module
    from providers.calendar_provider import MockCalendarProvider
    from services.calendar_service import CalendarService

    provider = MockCalendarProvider()
    monkeypatch.setattr(worker_module, "calendar_service", CalendarService(provider=provider))
    calendar_worker = worker_module.CalendarWorker()

    admin, doctor, patient, start, end = _bookable_slot(isolated_client, "calleave")
    _book(isolated_client, doctor, patient, start, end)
    with isolated_db() as session:
        calendar_worker.run_once(session)
    assert len(provider.events) == 2  # one per side: patient and doctor

    response = isolated_client.post(f"/api/v1/admin/doctors/{doctor['id']}/leaves", json={
        "leave_date": start.date().isoformat(), "reason": "sick"}, headers=admin)
    assert response.status_code == 201, response.text
    with isolated_db() as session:
        calendar_worker.run_once(session)

    assert provider.events == {}, "events for a conflicted appointment must not stay on anyone's calendar"


# --------------------------------------------------------------------------
# Cookie sessions (opt-in) and the consultation timing rule
# --------------------------------------------------------------------------

@pytest.fixture
def cookie_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_COOKIE_MODE", True)
    monkeypatch.setattr(settings, "AUTH_COOKIE_SECURE", False)  # the test client speaks plain http


def _cookie_login(client, email, password="password123"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_cookie_mode_keeps_the_token_out_of_the_response_body(client, cookie_mode):
    _register(client, "cookie@example.com", "PATIENT")
    client.cookies.clear()

    response = _cookie_login(client, "cookie@example.com")

    assert response.status_code == 200
    assert response.json()["access_token"] == "", "the token must only travel in the httpOnly cookie"
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie and "samesite=lax" in set_cookie
    assert client.get("/api/v1/auth/me").status_code == 200  # the cookie alone authenticates reads


def test_cookie_authenticated_writes_need_the_csrf_header(client, cookie_mode):
    _register(client, "csrf@example.com", "PATIENT")
    client.cookies.clear()
    _cookie_login(client, "csrf@example.com")

    # A cross-site form post would carry the cookie but could not add this header.
    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200  # and it did nothing

    allowed = client.post("/api/v1/auth/logout", headers={"X-CSRF-Protection": "1"})
    assert allowed.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401  # cookie cleared and token revoked


def test_bearer_tokens_need_no_csrf_header_even_in_cookie_mode(client, monkeypatch):
    headers = _register(client, "bearer@example.com", "PATIENT")  # cookie mode off: the body carries the token
    monkeypatch.setattr(settings, "AUTH_COOKIE_MODE", True)
    client.cookies.clear()
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204


def test_without_cookie_mode_a_cookie_is_ignored(client):
    _register(client, "nocookie@example.com", "PATIENT")
    token = _cookie_login(client, "nocookie@example.com").json()["access_token"]
    assert token  # default mode still returns the token in the body
    client.cookies.clear()
    client.cookies.set(settings.AUTH_COOKIE_NAME, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_cookie_mode_allows_credentialed_cors_only_for_allowed_origins(monkeypatch, cookie_mode):
    from app.main import create_app

    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGIN_REGEX", None)
    app_in_cookie_mode = TestClient(create_app())

    def preflight(origin):
        return app_in_cookie_mode.options("/api/v1/auth/login", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-csrf-protection,content-type"})

    ok = preflight("https://app.example.com")
    assert ok.headers.get("access-control-allow-credentials") == "true"
    assert ok.headers.get("access-control-allow-origin") == "https://app.example.com"
    assert "access-control-allow-origin" not in preflight("https://evil.example.com").headers


def test_consultation_cannot_be_recorded_early_when_the_rule_is_on(isolated_client, monkeypatch):
    admin, doctor, patient, start, end = _bookable_slot(isolated_client, "tooearly")
    appt = _book(isolated_client, doctor, patient, start, end)  # next Monday: days away
    doctor_headers = _register_login(isolated_client, "doc_tooearly@example.com")
    body = {"notes": "Routine check.", "prescription_instructions": None, "medications": []}
    url = f"/api/v1/appointments/{appt['id']}/consultation"

    monkeypatch.setattr(settings, "CONSULTATION_EARLY_SUBMIT_MINUTES", 15)
    early = isolated_client.post(url, json=body, headers=doctor_headers)
    assert early.status_code == 409 and "not started" in early.json()["detail"]

    monkeypatch.setattr(settings, "CONSULTATION_EARLY_SUBMIT_MINUTES", None)  # the default: demo flow
    assert isolated_client.post(url, json=body, headers=doctor_headers).status_code == 201


def test_consultation_is_allowed_inside_the_early_window(isolated_client, isolated_db, monkeypatch):
    from models.appointment import Appointment

    admin, doctor, patient, start, end = _bookable_slot(isolated_client, "inwindow")
    appt = _book(isolated_client, doctor, patient, start, end)
    with isolated_db() as session:  # move the appointment to 5 minutes from now
        row = session.get(Appointment, appt["id"])
        row.start_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        row.end_time = row.start_time + timedelta(minutes=30)
        session.commit()
    doctor_headers = _register_login(isolated_client, "doc_inwindow@example.com")

    monkeypatch.setattr(settings, "CONSULTATION_EARLY_SUBMIT_MINUTES", 15)
    response = isolated_client.post(f"/api/v1/appointments/{appt['id']}/consultation", headers=doctor_headers,
                                    json={"notes": "Routine check.", "prescription_instructions": None, "medications": []})
    assert response.status_code == 201, response.text
