"""Tests for rate limiting, password change/reset, email verification and the audit log."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from models.audit import AuditLog
from models.notification import NotificationJob, NotificationStatus, NotificationType
from models.security import AuthToken, RateLimit
from tests.test_design_guarantees import _book, _bookable_slot, _register
from tests.test_hardening import _appointment_with_symptoms, _register_login


@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMITING_ENABLED", True)


def _api(client, method, path, json_body=None, headers=None):
    return client.request(method, "/api/v1" + path, json=json_body, headers=headers)


def _sign_up(client, email, password="password123"):
    response = _api(client, "POST", "/auth/register", {"email": email, "password": password, "full_name": "Test Person", "role": "PATIENT"})
    assert response.status_code == 201, response.text
    return response.json()


def _login(client, email, password="password123"):
    return _api(client, "POST", "/auth/login", {"email": email, "password": password})


def _bearer(client, email, password="password123"):
    return {"Authorization": "Bearer " + _login(client, email, password).json()["access_token"]}


def _latest_job(db_session, notification_type):
    return (db_session.query(NotificationJob).filter_by(notification_type=notification_type)
            .order_by(NotificationJob.created_at.desc()).first())


def _token_from_job(job):
    link = json.loads(job.payload)["link"]
    return parse_qs(urlparse(link).query)["token"][0]


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

def test_registration_is_limited_per_client_ip(client, limits_on, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_RATE_LIMIT_PER_HOUR", 3)
    for i in range(3):
        _sign_up(client, f"limit{i}@example.com")

    blocked = _api(client, "POST", "/auth/register", {"email": "limit4@example.com", "password": "password123", "full_name": "Test Person"})

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_a_rate_limit_window_resets(client, db_session, limits_on, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_RATE_LIMIT_PER_HOUR", 1)
    _sign_up(client, "window1@example.com")
    assert _api(client, "POST", "/auth/register", {"email": "window2@example.com", "password": "password123", "full_name": "Test Person"}).status_code == 429

    for row in db_session.query(RateLimit).all():
        row.window_started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()

    _sign_up(client, "window3@example.com")  # a fresh window


def test_rate_limits_can_be_turned_off(client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTER_RATE_LIMIT_PER_HOUR", 1)
    for i in range(3):  # RATE_LIMITING_ENABLED is False in the test suite
        _sign_up(client, f"off{i}@example.com")


def test_rate_limit_rows_hold_no_plain_identifiers(client, db_session, limits_on):
    _sign_up(client, "private@example.com")
    keys = [row.key for row in db_session.query(RateLimit).all()]
    assert keys and all(len(k) == 64 and "testclient" not in k for k in keys)


def test_ai_generation_is_limited_per_user(client, limits_on, monkeypatch):
    appt, patient = _appointment_with_symptoms(client, "airate")
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_PER_HOUR", 1)
    url = f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary"

    assert client.post(url, headers=patient).status_code == 200
    limited = client.post(url, headers=patient)

    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0


def test_forgot_password_is_limited_per_email_and_per_ip(client, limits_on, monkeypatch):
    monkeypatch.setattr(settings, "PASSWORD_RESET_RATE_LIMIT_PER_HOUR", 100)
    monkeypatch.setattr(settings, "PASSWORD_RESET_EMAIL_RATE_LIMIT_PER_HOUR", 2)
    for _ in range(2):
        assert _api(client, "POST", "/auth/forgot-password", {"email": "flood@example.com"}).status_code == 202
    assert _api(client, "POST", "/auth/forgot-password", {"email": "flood@example.com"}).status_code == 429
    assert _api(client, "POST", "/auth/forgot-password", {"email": "other@example.com"}).status_code == 202

    monkeypatch.setattr(settings, "PASSWORD_RESET_RATE_LIMIT_PER_HOUR", 3)  # 3 already counted for this IP
    assert _api(client, "POST", "/auth/forgot-password", {"email": "third@example.com"}).status_code == 429


# --------------------------------------------------------------------------
# Changing a password
# --------------------------------------------------------------------------

def test_change_password_signs_out_other_sessions_but_not_this_one(client):
    _sign_up(client, "change@example.com")
    other_session = _bearer(client, "change@example.com")
    this_session = _bearer(client, "change@example.com")

    response = _api(client, "POST", "/auth/change-password",
                    {"current_password": "password123", "new_password": "a-new-password"}, headers=this_session)

    assert response.status_code == 200
    fresh = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert _api(client, "GET", "/auth/me", headers=fresh).status_code == 200
    assert _api(client, "GET", "/auth/me", headers=other_session).status_code == 401
    assert _api(client, "GET", "/auth/me", headers=this_session).status_code == 401  # the old token is dead too
    assert _login(client, "change@example.com", "a-new-password").status_code == 200
    assert _login(client, "change@example.com", "password123").status_code == 401


@pytest.mark.parametrize("body, reason", [
    ({"current_password": "wrong-password", "new_password": "a-new-password"}, "wrong current password"),
    ({"current_password": "password123", "new_password": "password123"}, "same as the current one"),
    ({"current_password": "password123", "new_password": "short"}, "too short"),
    ({"current_password": "password123", "new_password": "x" * 73}, "over bcrypt's 72 bytes"),
])
def test_change_password_rejects_bad_input_without_signing_the_user_out(client, body, reason):
    _sign_up(client, "badchange@example.com")
    headers = _bearer(client, "badchange@example.com")

    response = _api(client, "POST", "/auth/change-password", body, headers=headers)

    assert response.status_code == 422, reason
    assert _api(client, "GET", "/auth/me", headers=headers).status_code == 200  # still signed in


def test_change_password_needs_a_session(client):
    response = _api(client, "POST", "/auth/change-password", {"current_password": "password123", "new_password": "a-new-password"})
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Forgot / reset password
# --------------------------------------------------------------------------

def test_forgot_password_answers_identically_for_known_and_unknown_addresses(client, db_session):
    _sign_up(client, "known@example.com")

    known = _api(client, "POST", "/auth/forgot-password", {"email": "known@example.com"})
    unknown = _api(client, "POST", "/auth/forgot-password", {"email": "nobody@example.com"})

    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (202, known.json())
    jobs = db_session.query(NotificationJob).filter_by(notification_type=NotificationType.PASSWORD_RESET).all()
    assert len(jobs) == 1  # only the real account got an email


def test_only_a_hash_of_the_reset_token_is_stored(client, db_session):
    _sign_up(client, "hashed@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "hashed@example.com"})

    token = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))
    stored = [t.token_hash for t in db_session.query(AuthToken).filter_by(purpose="PASSWORD_RESET").all()]

    assert stored == [hashlib.sha256(token.encode()).hexdigest()] and token not in stored


def test_password_reset_end_to_end(client, db_session):
    _sign_up(client, "reset@example.com")
    old_session = _bearer(client, "reset@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "reset@example.com"})
    token = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))

    done = _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "brand-new-pass"})

    assert done.status_code == 204
    assert _login(client, "reset@example.com", "brand-new-pass").status_code == 200
    assert _login(client, "reset@example.com", "password123").status_code == 401
    assert _api(client, "GET", "/auth/me", headers=old_session).status_code == 401  # signed out everywhere
    again = _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "another-pass1"})
    assert again.status_code == 422  # single use


def test_an_expired_reset_link_is_refused(client, db_session):
    _sign_up(client, "expired@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "expired@example.com"})
    token = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))
    for row in db_session.query(AuthToken).all():
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "brand-new-pass"}).status_code == 422
    assert _login(client, "expired@example.com", "password123").status_code == 200  # password unchanged


def test_a_new_reset_request_replaces_the_older_link(client, db_session):
    _sign_up(client, "twice@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "twice@example.com"})
    first = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))
    _api(client, "POST", "/auth/forgot-password", {"email": "twice@example.com"})
    second = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))

    assert first != second
    assert _api(client, "POST", "/auth/reset-password", {"token": first, "new_password": "brand-new-pass"}).status_code == 422
    assert _api(client, "POST", "/auth/reset-password", {"token": second, "new_password": "brand-new-pass"}).status_code == 204


def test_reset_rejects_garbage_and_weak_passwords(client, db_session):
    _sign_up(client, "weak@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "weak@example.com"})
    token = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))

    assert _api(client, "POST", "/auth/reset-password", {"token": "not-a-real-token-at-all", "new_password": "brand-new-pass"}).status_code == 422
    assert _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "short"}).status_code == 422
    assert _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "brand-new-pass"}).status_code == 204  # token survived the bad tries


def test_a_deactivated_account_cannot_reset_its_password(client, db_session):
    from models.user import User

    _sign_up(client, "gone@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "gone@example.com"})
    token = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))
    db_session.query(User).filter_by(email="gone@example.com").one().is_active = False
    db_session.commit()

    assert _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "brand-new-pass"}).status_code == 422
    assert _api(client, "POST", "/auth/forgot-password", {"email": "gone@example.com"}).status_code == 202
    assert db_session.query(NotificationJob).filter_by(notification_type=NotificationType.PASSWORD_RESET).count() == 1


def test_the_reset_link_is_scrubbed_from_the_job_once_the_email_is_sent(client, db_session, monkeypatch):
    import workers.notification_worker as worker_module
    from providers.email_provider import MockEmailProvider
    from services.notification_service import NotificationService

    _sign_up(client, "scrub@example.com")
    _api(client, "POST", "/auth/forgot-password", {"email": "scrub@example.com"})
    job = _latest_job(db_session, NotificationType.PASSWORD_RESET)
    token = _token_from_job(job)
    provider = MockEmailProvider()
    monkeypatch.setattr(worker_module, "notification_service", NotificationService(provider=provider))

    worker_module.NotificationWorker().run_once(db_session)

    sent = [m for m in provider.sent_emails if m["subject"] == "Reset your password"]
    assert len(sent) == 1 and token in sent[0]["body"] and "30 minutes" in sent[0]["body"]
    db_session.refresh(job)
    assert job.status == NotificationStatus.SENT
    assert json.loads(job.payload) == {"redacted": True} and token not in job.payload


# --------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------

def test_registration_sends_a_verification_link_and_following_it_verifies(client, db_session):
    created = _sign_up(client, "verify@example.com")
    assert created["email_verified"] is False
    token = _token_from_job(_latest_job(db_session, NotificationType.EMAIL_VERIFICATION))
    headers = _bearer(client, "verify@example.com")

    assert _api(client, "POST", "/auth/verify-email", {"token": token}).status_code == 204

    assert _api(client, "GET", "/auth/me", headers=headers).json()["email_verified"] is True
    assert _api(client, "POST", "/auth/verify-email", {"token": token}).status_code == 422  # single use


def test_login_can_require_a_verified_email(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)
    _sign_up(client, "gated@example.com")

    blocked = _login(client, "gated@example.com")
    assert blocked.status_code == 403 and "verify" in blocked.json()["detail"].lower()
    assert _login(client, "gated@example.com", "wrong-password").status_code == 401  # a wrong password is still just a 401

    token = _token_from_job(_latest_job(db_session, NotificationType.EMAIL_VERIFICATION))
    _api(client, "POST", "/auth/verify-email", {"token": token})
    assert _login(client, "gated@example.com").status_code == 200


def test_verification_is_not_required_by_default_and_admin_made_doctors_are_verified(client):
    _sign_up(client, "default@example.com")
    assert _login(client, "default@example.com").status_code == 200  # the demo flow keeps working

    admin = _register(client, "admin_verified@example.com", "ADMIN")
    doctor = _api(client, "POST", "/admin/doctors", {"email": "doc_verified@example.com", "password": "password123",
                  "full_name": "Dr Verified", "specialization": "Cardiology"}, headers=admin).json()
    assert doctor["id"]
    assert _api(client, "GET", "/auth/me", headers=_bearer(client, "doc_verified@example.com")).json()["email_verified"] is True


def test_resend_verification_replaces_the_link_and_ignores_verified_or_unknown_addresses(client, db_session):
    _sign_up(client, "resend@example.com")
    first = _token_from_job(_latest_job(db_session, NotificationType.EMAIL_VERIFICATION))
    jobs_before = db_session.query(NotificationJob).filter_by(notification_type=NotificationType.EMAIL_VERIFICATION).count()

    assert _api(client, "POST", "/auth/resend-verification", {"email": "resend@example.com"}).status_code == 202
    assert _api(client, "POST", "/auth/resend-verification", {"email": "nobody@example.com"}).status_code == 202
    second = _token_from_job(_latest_job(db_session, NotificationType.EMAIL_VERIFICATION))

    assert second != first
    assert db_session.query(NotificationJob).filter_by(notification_type=NotificationType.EMAIL_VERIFICATION).count() == jobs_before + 1
    assert _api(client, "POST", "/auth/verify-email", {"token": first}).status_code == 422
    assert _api(client, "POST", "/auth/verify-email", {"token": second}).status_code == 204
    assert _api(client, "POST", "/auth/resend-verification", {"email": "resend@example.com"}).status_code == 202
    assert db_session.query(NotificationJob).filter_by(notification_type=NotificationType.EMAIL_VERIFICATION).count() == jobs_before + 1


def test_a_failing_verification_email_never_fails_registration(client, monkeypatch):
    import services.auth_service as auth_module

    def boom(*args, **kwargs):
        raise RuntimeError("simulated notification outage")

    monkeypatch.setattr(auth_module.notification_service, "queue_notification", boom)
    assert _sign_up(client, "outage@example.com")["email"] == "outage@example.com"
    assert _login(client, "outage@example.com").status_code == 200


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------

def _audit(db_session, action=None):
    query = db_session.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    return query.order_by(AuditLog.occurred_at).all()


def test_login_and_logout_are_audited_with_the_client_ip(client, db_session):
    _sign_up(client, "audited@example.com")
    headers = _bearer(client, "audited@example.com")
    _api(client, "POST", "/auth/logout", headers=headers)

    login, logout = _audit(db_session, "auth.login")[-1], _audit(db_session, "auth.logout")[-1]
    assert login.actor_role == "PATIENT" and login.actor_user_id == logout.actor_user_id
    assert login.ip == "testclient" and logout.ip == "testclient"
    assert _audit(db_session, "user.register")


def test_a_lockout_is_audited_without_auditing_every_failure(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILED_ATTEMPTS", 3)
    _sign_up(client, "locked@example.com")
    for _ in range(3):
        _login(client, "locked@example.com", "wrong-password")

    assert len(_audit(db_session, "auth.login.lockout")) == 1
    assert not [e for e in _audit(db_session) if e.action == "auth.login.failed"]


def test_password_changes_and_resets_are_audited(client, db_session):
    _sign_up(client, "pwaudit@example.com")
    headers = _bearer(client, "pwaudit@example.com")
    _api(client, "POST", "/auth/change-password", {"current_password": "password123", "new_password": "a-new-password"}, headers=headers)
    _api(client, "POST", "/auth/forgot-password", {"email": "pwaudit@example.com"})
    token = _token_from_job(_latest_job(db_session, NotificationType.PASSWORD_RESET))
    _api(client, "POST", "/auth/reset-password", {"token": token, "new_password": "reset-password-1"})

    assert [e.action for e in _audit(db_session) if e.action.startswith("auth.password")] == [
        "auth.password.change", "auth.password.reset.request", "auth.password.reset"]
    assert token not in json.dumps([e.detail for e in _audit(db_session)])  # secrets never reach the log


def test_reading_a_patients_appointment_is_audited_unless_it_is_their_own(client, db_session):
    admin, doctor, patient, start, end = _bookable_slot(client, "auditview")
    appt = _book(client, doctor, patient, start, end)
    doctor_headers = _register_login(client, "doc_auditview@example.com")

    client.get(f"/api/v1/appointments/{appt['id']}", headers=patient)       # their own record
    client.get(f"/api/v1/appointments/{appt['id']}", headers=doctor_headers)  # someone else reading it

    views = _audit(db_session, "appointment.view")
    assert len(views) == 1
    assert views[0].actor_role == "DOCTOR" and views[0].patient_id == appt["patient_id"]
    assert views[0].resource_id == appt["id"] and views[0].resource_type == "appointment"


def test_clinical_actions_are_audited_without_clinical_content(client, db_session):
    admin, doctor, patient, start, end = _bookable_slot(client, "auditclin")
    appt = _book(client, doctor, patient, start, end)
    doctor_headers = _register_login(client, "doc_auditclin@example.com")
    note = "Patient reports sertraline side effects"
    client.post(f"/api/v1/appointments/{appt['id']}/consultation", headers=doctor_headers, json={
        "notes": note, "prescription_instructions": None,
        "medications": [{"name": "Sertraline", "dosage": "50mg", "frequency": "daily", "duration_days": 5}]})
    client.get(f"/api/v1/appointments/{appt['id']}/consultation", headers=doctor_headers)
    client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doctor_headers)

    actions = {e.action for e in _audit(db_session)}
    assert {"consultation.submit", "consultation.view", "ai.post_visit.generate"} <= actions
    everything = json.dumps([[e.detail, e.resource_id, e.action] for e in _audit(db_session)])
    assert "Sertraline" not in everything and note not in everything


def test_admin_actions_are_audited(client, db_session):
    admin = _register(client, "admin_audit@example.com", "ADMIN")
    doctor = _api(client, "POST", "/admin/doctors", {"email": "doc_audit@example.com", "password": "password123",
                  "full_name": "Dr Audit", "specialization": "Cardiology"}, headers=admin).json()
    _api(client, "PUT", f"/admin/doctors/{doctor['id']}", {"specialization": "Neurology"}, headers=admin)
    _api(client, "PATCH", f"/admin/doctors/{doctor['id']}/status?is_active=false", headers=admin)
    _api(client, "POST", f"/admin/doctors/{doctor['id']}/schedule", {"working_hours": [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}]}, headers=admin)
    leave = _api(client, "POST", f"/admin/doctors/{doctor['id']}/leaves", {"leave_date": "2031-01-06", "reason": "x"}, headers=admin).json()
    _api(client, "DELETE", f"/admin/doctors/{doctor['id']}/leaves/{leave['id']}", headers=admin)

    actions = [e.action for e in _audit(db_session) if e.action.startswith("doctor.")]
    assert actions == ["doctor.create", "doctor.update", "doctor.status", "doctor.schedule.update",
                       "doctor.leave.create", "doctor.leave.delete"]
    assert all(e.actor_role == "ADMIN" and e.resource_id == doctor["id"] for e in _audit(db_session) if e.action.startswith("doctor."))


def test_the_audit_log_endpoint_is_admin_only_and_filterable(client, db_session):
    admin = _register(client, "admin_logs@example.com", "ADMIN")
    patient = _register(client, "patient_logs@example.com", "PATIENT")
    for i in range(3):
        _api(client, "POST", "/auth/forgot-password", {"email": f"someone{i}@example.com"})

    assert _api(client, "GET", "/admin/audit-logs", headers=patient).status_code == 403
    assert _api(client, "GET", "/admin/audit-logs").status_code == 401

    everything = _api(client, "GET", "/admin/audit-logs?limit=200", headers=admin).json()
    assert everything["total"] >= 6 and everything["items"][0]["occurred_at"] >= everything["items"][-1]["occurred_at"]

    auth_only = _api(client, "GET", "/admin/audit-logs?action=auth.password.&limit=200", headers=admin).json()
    assert auth_only["total"] == 3 and {i["action"] for i in auth_only["items"]} == {"auth.password.reset.request"}

    exact = _api(client, "GET", "/admin/audit-logs?action=user.register", headers=admin).json()
    assert exact["total"] == 2 and {i["action"] for i in exact["items"]} == {"user.register"}

    page = _api(client, "GET", "/admin/audit-logs?limit=2&offset=2", headers=admin).json()
    assert len(page["items"]) == 2 and page["limit"] == 2 and page["offset"] == 2
    assert _api(client, "GET", "/admin/audit-logs?limit=500", headers=admin).status_code == 422

    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert _api(client, "GET", "/admin/audit-logs", headers=admin, json_body=None).status_code == 200
    assert _api(client, "GET", "/admin/audit-logs", headers=admin).json()["total"] > 0
    assert client.get("/api/v1/admin/audit-logs", params={"since": future}, headers=admin).json()["total"] == 0


def test_filtering_the_audit_log_by_patient(client, db_session):
    admin, doctor, patient, start, end = _bookable_slot(client, "bypatient")
    appt = _book(client, doctor, patient, start, end)
    doctor_headers = _register_login(client, "doc_bypatient@example.com")
    client.get(f"/api/v1/appointments/{appt['id']}", headers=doctor_headers)

    found = client.get("/api/v1/admin/audit-logs", params={"patient_id": appt["patient_id"]}, headers=admin).json()

    assert found["total"] == 1 and found["items"][0]["action"] == "appointment.view"


def test_reading_the_audit_log_is_itself_audited(client, db_session):
    admin = _register(client, "admin_meta@example.com", "ADMIN")
    client.get("/api/v1/admin/audit-logs", params={"patient_id": "abc"}, headers=admin)

    entry = _audit(db_session, "audit.view")[-1]
    assert entry.actor_role == "ADMIN" and json.loads(entry.detail) == {"patient_id": "abc"}


def test_a_broken_audit_write_never_breaks_the_request(client, monkeypatch, caplog):
    import services.audit_service as audit_module

    def boom(*args, **kwargs):
        raise RuntimeError("audit table is down")

    admin, doctor, patient, start, end = _bookable_slot(client, "auditdown")
    appt = _book(client, doctor, patient, start, end)
    doctor_headers = _register_login(client, "doc_auditdown@example.com")
    monkeypatch.setattr(audit_module, "Session", boom)

    with caplog.at_level("ERROR"):
        response = client.get(f"/api/v1/appointments/{appt['id']}", headers=doctor_headers)

    assert response.status_code == 200
    assert any("AUDIT WRITE FAILED" in r.getMessage() for r in caplog.records)


def test_the_audit_log_cannot_be_changed_through_the_api(client):
    admin = _register(client, "admin_ro@example.com", "ADMIN")
    for method in ("PUT", "PATCH", "DELETE", "POST"):
        assert _api(client, method, "/admin/audit-logs", {}, headers=admin).status_code == 405


# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------

def test_maintenance_purges_expired_rows_but_never_the_audit_log(client, db_session):
    from models.security import LoginThrottle
    from workers.maintenance_worker import MaintenanceWorker

    _sign_up(client, "housekeeping@example.com")
    old = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.add_all([
        RateLimit(key="a" * 64, count=3, window_started_at=old),
        LoginThrottle(key="b" * 64, failed_count=2, window_started_at=old),
    ])
    user_id = _audit(db_session, "user.register")[0].actor_user_id
    db_session.add(AuthToken(user_id=user_id, purpose="PASSWORD_RESET", token_hash="c" * 64,
                             expires_at=old, created_at=old))
    db_session.commit()
    audit_rows = db_session.query(AuditLog).count()

    stats = MaintenanceWorker().run_once(db_session)

    assert stats["rate_limits"] >= 1 and stats["login_throttles"] >= 1 and stats["auth_tokens"] >= 1
    assert db_session.query(RateLimit).filter_by(key="a" * 64).count() == 0
    assert db_session.query(AuditLog).count() == audit_rows
    fresh = MaintenanceWorker().run_once(db_session)
    assert fresh["claimed"] == 0
