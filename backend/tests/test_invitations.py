"""Tests for staff invitations: one signup page, with the role coming from an emailed invitation."""
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import settings
from models.audit import AuditLog
from models.doctor import Doctor
from models.invitation import Invitation
from models.notification import NotificationJob, NotificationStatus, NotificationType
from models.user import User, UserRole
from tests.test_design_guarantees import _register, isolated_client, isolated_db  # noqa: F401  (fixtures are used by name)


def _api(client, method, path, json_body=None, headers=None):
    return client.request(method, "/api/v1" + path, json=json_body, headers=headers)


def _invite(client, admin, email, role="DOCTOR", **extra):
    body = {"email": email, "role": role}
    if role == "DOCTOR":
        body.setdefault("specialization", "Cardiology")
    body.update(extra)
    return _api(client, "POST", "/admin/invitations", body, headers=admin)


def _token_of(created_response):
    return parse_qs(urlparse(created_response.json()["invite_link"]).query)["invite"][0]


def _accept(client, token, email, role="PATIENT", password="password123"):
    return _api(client, "POST", "/auth/register", {
        "email": email, "password": password, "full_name": "Invited Person", "role": role, "invite_token": token,
    })


@pytest.fixture
def admin(client):
    return _register(client, "inviter@example.com", "ADMIN")


def test_an_admin_can_invite_a_doctor_who_signs_up_on_the_normal_page(client, db_session, admin):
    created = _invite(client, admin, "newdoc@example.com", specialization="Neurology", slot_duration_minutes=20, timezone="Asia/Kolkata")

    assert created.status_code == 201, created.text
    assert created.json()["invitation"]["status"] == "PENDING"
    assert created.json()["email_queued"] is True
    token = _token_of(created)

    signup = _accept(client, token, "newdoc@example.com")

    assert signup.status_code == 201, signup.text
    assert signup.json()["role"] == "DOCTOR" and signup.json()["email_verified"] is True
    user = db_session.query(User).filter_by(email="newdoc@example.com").one()
    doctor = db_session.query(Doctor).filter_by(user_id=user.id).one()
    assert (doctor.specialization, doctor.slot_duration_minutes, doctor.timezone) == ("Neurology", 20, "Asia/Kolkata")
    assert _api(client, "POST", "/auth/login", {"email": "newdoc@example.com", "password": "password123"}).status_code == 200


def test_the_form_cannot_choose_the_role_when_an_invitation_is_used(client, db_session, admin):
    token = _token_of(_invite(client, admin, "second.admin@example.com", role="ADMIN"))

    signup = _accept(client, token, "second.admin@example.com", role="PATIENT")  # the form says PATIENT

    assert signup.status_code == 201 and signup.json()["role"] == "ADMIN"
    login = _api(client, "POST", "/auth/login", {"email": "second.admin@example.com", "password": "password123"})
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert _api(client, "GET", "/admin/invitations", headers=headers).status_code == 200  # a working admin


def test_an_invitation_can_be_used_only_once(client, db_session, admin):
    token = _token_of(_invite(client, admin, "once@example.com"))
    assert _accept(client, token, "once@example.com").status_code == 201

    again = _accept(client, token, "once@example.com")

    assert again.status_code == 422
    assert db_session.query(User).filter_by(email="once@example.com").count() == 1
    status = _api(client, "GET", "/admin/invitations", headers=admin).json()[0]["status"]
    assert status == "ACCEPTED"


def test_the_invitation_only_works_for_the_address_it_was_sent_to(client, db_session, admin):
    token = _token_of(_invite(client, admin, "right@example.com"))

    wrong = _accept(client, token, "wrong@example.com")

    assert wrong.status_code == 422
    assert db_session.query(User).filter_by(email="wrong@example.com").count() == 0
    assert _accept(client, token, "RIGHT@example.com").status_code == 201  # the link still works; case is ignored


def test_a_made_up_token_is_rejected(client):
    assert _accept(client, "x" * 43, "nobody@example.com").status_code == 422
    assert _api(client, "POST", "/auth/invitations/lookup", {"token": "x" * 43}).status_code == 422


def test_expired_and_revoked_invitations_do_not_work(client, db_session, admin):
    expired_token = _token_of(_invite(client, admin, "late@example.com"))
    db_session.query(Invitation).filter_by(email="late@example.com").update(
        {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)})
    db_session.commit()
    revoked = _invite(client, admin, "withdrawn@example.com")
    assert _api(client, "DELETE", f"/admin/invitations/{revoked.json()['invitation']['id']}", headers=admin).status_code == 204

    assert _accept(client, expired_token, "late@example.com").status_code == 422
    assert _accept(client, _token_of(revoked), "withdrawn@example.com").status_code == 422
    statuses = {i["email"]: i["status"] for i in _api(client, "GET", "/admin/invitations", headers=admin).json()}
    assert statuses == {"late@example.com": "EXPIRED", "withdrawn@example.com": "REVOKED"}
    assert _api(client, "DELETE", f"/admin/invitations/{revoked.json()['invitation']['id']}", headers=admin).status_code == 404


def test_a_new_invitation_replaces_the_older_one_to_the_same_address(client, admin):
    first = _token_of(_invite(client, admin, "twice@example.com"))
    second = _token_of(_invite(client, admin, "twice@example.com"))

    assert _accept(client, first, "twice@example.com").status_code == 422
    assert _accept(client, second, "twice@example.com").status_code == 201


def test_only_admins_can_manage_invitations(client, admin):
    patient = _register(client, "pat@example.com", "PATIENT")
    body = {"email": "x@example.com", "role": "ADMIN"}

    assert _api(client, "POST", "/admin/invitations", body, headers=patient).status_code == 403
    assert _api(client, "GET", "/admin/invitations", headers=patient).status_code == 403
    assert _api(client, "POST", "/admin/invitations", body).status_code == 401


def test_you_cannot_invite_someone_who_already_has_an_account(client, admin):
    _register(client, "member@example.com", "PATIENT")

    assert _invite(client, admin, "member@example.com").status_code == 409


def test_an_invitation_cannot_create_a_second_account_for_an_existing_address(client, db_session, admin):
    token = _token_of(_invite(client, admin, "raced@example.com"))
    _register(client, "raced@example.com", "PATIENT")  # signed up on their own in the meantime

    result = _accept(client, token, "raced@example.com")

    assert result.status_code == 409
    assert db_session.query(User).filter_by(email="raced@example.com").count() == 1
    assert _api(client, "POST", "/auth/invitations/lookup", {"token": token}).status_code == 409


def test_a_failed_signup_leaves_the_invitation_usable(isolated_client, isolated_db, monkeypatch):
    from repositories.doctor_repository import doctor_repository
    client = isolated_client
    admin = _register(client, "inviter_retry@example.com", "ADMIN")
    token = _token_of(_invite(client, admin, "retry@example.com"))
    real_create_doctor = doctor_repository.create_doctor

    def boom(*args, **kwargs):
        raise RuntimeError("database hiccup")
    monkeypatch.setattr(doctor_repository, "create_doctor", boom)
    with pytest.raises(RuntimeError):
        _accept(client, token, "retry@example.com")
    monkeypatch.setattr(doctor_repository, "create_doctor", real_create_doctor)

    with isolated_db() as check:
        assert check.query(User).filter_by(email="retry@example.com").count() == 0  # no half-made account
    assert _accept(client, token, "retry@example.com").status_code == 201


def test_lookup_shows_the_signup_page_what_it_needs(client, admin):
    token = _token_of(_invite(client, admin, "peek@example.com", full_name="Dr Peek"))

    looked_up = _api(client, "POST", "/auth/invitations/lookup", {"token": token})

    assert looked_up.status_code == 200
    assert {k: looked_up.json()[k] for k in ("email", "role", "full_name")} == {
        "email": "peek@example.com", "role": "DOCTOR", "full_name": "Dr Peek"}


def test_invitation_requests_are_validated(client, admin):
    assert _api(client, "POST", "/admin/invitations", {"email": "a@example.com", "role": "PATIENT"}, headers=admin).status_code == 422
    assert _api(client, "POST", "/admin/invitations", {"email": "a@example.com", "role": "DOCTOR"}, headers=admin).status_code == 422  # no specialization
    assert _api(client, "POST", "/admin/invitations", {"email": "a@example.com", "role": "ADMIN", "specialization": "x" * 5}, headers=admin).status_code == 422
    bad_zone = {"email": "a@example.com", "role": "DOCTOR", "specialization": "ENT", "timezone": "Mars/Base"}
    assert _api(client, "POST", "/admin/invitations", bad_zone, headers=admin).status_code == 422


def test_the_invitation_email_goes_to_the_address_and_the_link_is_scrubbed_after_sending(client, db_session, admin, monkeypatch):
    import workers.notification_worker as worker_module
    from providers.email_provider import MockEmailProvider
    from services.notification_service import NotificationService

    created = _invite(client, admin, "mailed@example.com")
    token = _token_of(created)
    job = (db_session.query(NotificationJob).filter_by(notification_type=NotificationType.INVITATION).one())
    assert job.recipient_id is None and job.recipient_email == "mailed@example.com"
    # The worker handles a limited batch per run, oldest first. Jobs left pending by earlier
    # tests would fill it before reaching ours, so make this test independent of them.
    db_session.query(NotificationJob).filter(NotificationJob.id != job.id).delete(synchronize_session=False)
    db_session.commit()
    provider = MockEmailProvider()
    monkeypatch.setattr(worker_module, "notification_service", NotificationService(provider=provider))

    worker_module.NotificationWorker().run_once(db_session)

    sent = [m for m in provider.sent_emails if m["to"] == "mailed@example.com"]
    assert len(sent) == 1 and token in sent[0]["body"] and "doctor" in sent[0]["body"]
    db_session.refresh(job)
    assert job.status == NotificationStatus.SENT
    assert json.loads(job.payload) == {"redacted": True} and token not in job.payload


def test_only_a_hash_of_the_token_is_stored(client, db_session, admin):
    token = _token_of(_invite(client, admin, "hashed@example.com"))

    stored = db_session.query(Invitation).filter_by(email="hashed@example.com").one()

    assert token not in (stored.token_hash or "") and len(stored.token_hash) == 64


def test_inviting_and_accepting_are_audited(client, db_session, admin):
    token = _token_of(_invite(client, admin, "trail@example.com"))
    _accept(client, token, "trail@example.com")
    created = db_session.query(AuditLog).filter_by(action="invitation.create").one()
    accepted = db_session.query(AuditLog).filter_by(action="invitation.accept").one()

    assert created.actor_role == "ADMIN" and token not in (created.detail or "")
    assert accepted.actor_role == "DOCTOR"


def test_invitations_are_rate_limited_per_admin(client, admin, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMITING_ENABLED", True)
    monkeypatch.setattr(settings, "INVITE_RATE_LIMIT_PER_HOUR", 2)
    other_admin = _register(client, "other.inviter@example.com", "ADMIN")
    assert _invite(client, admin, "r1@example.com").status_code == 201
    assert _invite(client, admin, "r2@example.com").status_code == 201

    blocked = _invite(client, admin, "r3@example.com")

    assert blocked.status_code == 429
    assert _invite(client, other_admin, "r4@example.com").status_code == 201  # the budget is per admin


def test_maintenance_purges_long_expired_unaccepted_invitations(client, db_session, admin):
    from services.maintenance_service import maintenance_service
    _invite(client, admin, "stale@example.com")
    _invite(client, admin, "recent@example.com")
    db_session.query(Invitation).filter_by(email="stale@example.com").update(
        {"expires_at": datetime.now(timezone.utc) - timedelta(days=40)})
    db_session.commit()

    assert maintenance_service.purge_expired(db_session)["invitations"] == 1

    assert {i.email for i in db_session.query(Invitation).all()} == {"recent@example.com"}
