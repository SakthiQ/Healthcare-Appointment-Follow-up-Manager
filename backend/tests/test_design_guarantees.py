"""Regression tests for three design guarantees:

1. Background workers actually run in a single-service deployment.
2. Confirming a hold is atomic: a lost race keeps the patient's hold.
3. The database itself rejects overlapping active appointments for one doctor,
   not just identical start times.

Tests 2 and 3 use a file-backed SQLite database with an independent session per
request. The shared-connection fixtures in conftest.py wrap everything in one
outer transaction, which would make a rollback wipe the test's own setup and
hide exactly the commit-boundary bug test 2 guards against.
"""
import threading
from datetime import date, datetime, time, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base, get_db
from app.main import app
from models.appointment import Appointment, AppointmentHold, AppointmentStatus
from repositories.appointment_repository import appointment_repository
from workers.runner import WorkerRunner


@pytest.fixture
def isolated_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'isolated.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    engine.dispose()


@pytest.fixture
def isolated_client(isolated_db):
    def override_get_db():
        db = isolated_db()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


# --------------------------------------------------------------------------
# 2. Hold confirmation is atomic
# --------------------------------------------------------------------------

def _next_monday() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


def _register(client, email, role):
    client.post("/api/v1/auth/register", json={
        "email": email, "password": "password123", "full_name": email.split("@")[0], "role": role})
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_failed_hold_confirmation_keeps_the_hold(isolated_client, isolated_db, monkeypatch):
    client = isolated_client
    admin = _register(client, "admin_atomic@example.com", "ADMIN")
    doctor = client.post("/api/v1/admin/doctors", json={
        "email": "doc_atomic@example.com", "password": "password123", "full_name": "Dr Atomic",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin).json()
    client.post(f"/api/v1/admin/doctors/{doctor['id']}/schedule", json={"working_hours": [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}]}, headers=admin)
    holder = _register(client, "holder_atomic@example.com", "PATIENT")
    rival = _register(client, "rival_atomic@example.com", "PATIENT")

    start = datetime.combine(_next_monday(), time(9, 0), tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)
    hold = client.post("/api/v1/slots/holds", json={
        "doctor_id": doctor["id"], "start_time": start.isoformat(), "end_time": end.isoformat()},
        headers=holder).json()

    # A rival booking for the same slot lands first.
    rival_id = client.get("/api/v1/auth/me", headers=rival).json()["id"]
    with isolated_db() as session:
        session.add(Appointment(
            patient_id=rival_id, doctor_id=rival_id, doctor_profile_id=doctor["id"],
            start_time=start, end_time=end, status=AppointmentStatus.CONFIRMED))
        session.commit()

    # Hide it from the application-level overlap check to reproduce the window
    # where two transactions both see "free" and the database has to decide.
    monkeypatch.setattr(appointment_repository, "get_active_overlapping", lambda *a, **k: [])

    response = client.post("/api/v1/appointments", json={"doctor_id": doctor["id"], "hold_id": hold["id"]}, headers=holder)

    assert response.status_code == 409
    with isolated_db() as session:
        assert session.get(AppointmentHold, hold["id"]).is_active is True, (
            "a failed confirmation must not consume the patient's hold")


# --------------------------------------------------------------------------
# 3. Database-level overlap guard
# --------------------------------------------------------------------------

def _appt(doctor, start_minute, minutes=30, status=AppointmentStatus.CONFIRMED, hour=9):
    start = datetime(2030, 1, 7, hour, start_minute, tzinfo=timezone.utc)
    return Appointment(
        patient_id="patient-1", doctor_id="doctor-user-1", doctor_profile_id=doctor,
        start_time=start, end_time=start + timedelta(minutes=minutes), status=status)


def test_db_rejects_overlapping_active_appointments(isolated_db):
    with isolated_db() as session:
        session.add(_appt("doc-1", 0))  # 09:00-09:30
        session.commit()

        session.add(_appt("doc-1", 15))  # 09:15-09:45: different start, overlapping
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_db_allows_adjacent_other_doctor_and_inactive_appointments(isolated_db):
    with isolated_db() as session:
        session.add(_appt("doc-1", 0))                                      # 09:00-09:30
        session.add(_appt("doc-1", 30))                                     # back-to-back
        session.add(_appt("doc-2", 0))                                      # other doctor, same time
        session.add(_appt("doc-1", 15, status=AppointmentStatus.CANCELLED))  # inactive overlap
        session.add(_appt("doc-1", 15, status=AppointmentStatus.CONFLICTED))
        session.commit()
        assert session.query(Appointment).count() == 5


def test_db_rejects_reschedule_or_reactivation_into_an_overlap(isolated_db):
    with isolated_db() as session:
        first, second = _appt("doc-1", 0), _appt("doc-1", 0, hour=10)  # 09:00 and 10:00
        cancelled = _appt("doc-1", 15, status=AppointmentStatus.CANCELLED)  # 09:15, inactive
        session.add_all([first, second, cancelled])
        session.commit()

        second.start_time = datetime(2030, 1, 7, 9, 15, tzinfo=timezone.utc)
        second.end_time = datetime(2030, 1, 7, 9, 45, tzinfo=timezone.utc)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        cancelled.status = AppointmentStatus.CONFIRMED
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_db_allows_status_change_on_an_appointment_that_overlaps_only_itself(isolated_db):
    with isolated_db() as session:
        appt = _appt("doc-1", 0)
        session.add(appt)
        session.commit()
        appt.status = AppointmentStatus.RESCHEDULED
        session.commit()  # must not collide with its own previous row


# --------------------------------------------------------------------------
# 5. At most one active hold per slot
# --------------------------------------------------------------------------

def _hold(doctor, minute=0, active=True):
    start = datetime(2030, 1, 7, 9, minute, tzinfo=timezone.utc)
    return AppointmentHold(
        doctor_id=doctor, patient_id="patient-1", start_time=start,
        end_time=start + timedelta(minutes=30),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10), is_active=active)


def test_db_allows_only_one_active_hold_per_slot(isolated_db):
    with isolated_db() as session:
        first = _hold("doc-1")
        session.add(first)
        session.commit()

        session.add(_hold("doc-1"))  # same doctor and slot, also active
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add_all([_hold("doc-1", minute=30), _hold("doc-2"), _hold("doc-1", active=False)])
        session.commit()  # other slot, other doctor, and an inactive duplicate are all fine

        session.get(AppointmentHold, first.id).is_active = False
        session.add(_hold("doc-1"))
        session.commit()  # once the first hold is released the slot can be held again


def test_losing_a_hold_race_returns_409(isolated_client, isolated_db, monkeypatch):
    from repositories.hold_repository import hold_repository

    client = isolated_client
    admin = _register(client, "admin_holdrace@example.com", "ADMIN")
    doctor = client.post("/api/v1/admin/doctors", json={
        "email": "doc_holdrace@example.com", "password": "password123", "full_name": "Dr Race",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin).json()
    client.post(f"/api/v1/admin/doctors/{doctor['id']}/schedule", json={"working_hours": [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}]}, headers=admin)
    first = _register(client, "first_holdrace@example.com", "PATIENT")
    second = _register(client, "second_holdrace@example.com", "PATIENT")

    start = datetime.combine(_next_monday(), time(9, 0), tzinfo=timezone.utc)
    body = {"doctor_id": doctor["id"], "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat()}
    assert client.post("/api/v1/slots/holds", json=body, headers=first).status_code == 201

    # Both requests passed the "is it held?" check before either inserted.
    monkeypatch.setattr(hold_repository, "get_active_hold_for_slot", lambda *a, **k: None)
    assert client.post("/api/v1/slots/holds", json=body, headers=second).status_code == 409

    with isolated_db() as session:
        assert session.query(AppointmentHold).filter_by(is_active=True).count() == 1


# --------------------------------------------------------------------------
# 1. Workers run in-process
# --------------------------------------------------------------------------

class _FakeWorker:
    def __init__(self, fail_first=False):
        self.calls = 0
        self.fail_first = fail_first
        self.ran_twice = threading.Event()

    def run_once(self, db):
        self.calls += 1
        if self.calls >= 2:
            self.ran_twice.set()
        if self.fail_first and self.calls == 1:
            raise RuntimeError("boom")
        return {"claimed": 0}


class _FakeSession:
    closed = 0

    def close(self):
        _FakeSession.closed += 1


def test_worker_runner_polls_repeatedly_survives_errors_and_stops():
    _FakeSession.closed = 0
    healthy, flaky = _FakeWorker(), _FakeWorker(fail_first=True)
    runner = WorkerRunner(_FakeSession, {"healthy": healthy, "flaky": flaky}, poll_interval_seconds=0.01)

    runner.start()
    try:
        assert healthy.ran_twice.wait(5), "healthy worker never polled twice"
        assert flaky.ran_twice.wait(5), "an exception in one batch must not kill the worker loop"
    finally:
        runner.stop()

    assert not any(t.is_alive() for t in runner._threads) and runner._threads == []
    settled = healthy.calls
    threading.Event().wait(0.1)
    assert healthy.calls == settled, "workers must not poll after stop()"
    assert _FakeSession.closed >= healthy.calls + flaky.calls, "every iteration must close its session"


class _FakeRunner:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_app_lifespan_starts_and_stops_workers_only_when_enabled(monkeypatch):
    started = []

    def fake_start():
        runner = _FakeRunner()
        started.append(runner)
        return runner

    monkeypatch.setattr("workers.runner.start_background_workers", fake_start)

    monkeypatch.setattr(settings, "RUN_WORKERS_IN_PROCESS", False)
    with TestClient(app):
        pass
    assert started == []

    monkeypatch.setattr(settings, "RUN_WORKERS_IN_PROCESS", True)
    with TestClient(app):
        assert len(started) == 1 and not started[0].stopped
    assert started[0].stopped


# --------------------------------------------------------------------------
# Leave handling, notifications, auth hardening
# --------------------------------------------------------------------------

def _bookable_slot(client, tag):
    """Admin, a doctor open Monday 09:00-12:00, and one patient. Returns
    (admin_headers, doctor, patient_headers, start, end)."""
    admin = _register(client, f"admin_{tag}@example.com", "ADMIN")
    doctor = client.post("/api/v1/admin/doctors", json={
        "email": f"doc_{tag}@example.com", "password": "password123", "full_name": f"Dr {tag}",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin).json()
    client.post(f"/api/v1/admin/doctors/{doctor['id']}/schedule", json={"working_hours": [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}]}, headers=admin)
    patient = _register(client, f"patient_{tag}@example.com", "PATIENT")
    start = datetime.combine(_next_monday(), time(9, 0), tzinfo=timezone.utc)
    return admin, doctor, patient, start, start + timedelta(minutes=30)


def _book(client, doctor, patient, start, end):
    response = client.post("/api/v1/appointments", json={
        "doctor_id": doctor["id"], "start_time": start.isoformat(), "end_time": end.isoformat()}, headers=patient)
    assert response.status_code == 201, response.text
    return response.json()


def _jobs(isolated_db, appointment_id, notification_type):
    from models.notification import NotificationJob, NotificationStatus
    with isolated_db() as session:
        rows = session.query(NotificationJob).filter_by(
            appointment_id=appointment_id, notification_type=notification_type).all()
        return [r.status for r in rows], NotificationStatus


def test_duplicate_leave_race_returns_409_not_500(isolated_client, monkeypatch):
    from repositories.doctor_repository import doctor_repository

    admin, doctor, _, start, _ = _bookable_slot(isolated_client, "leaverace")
    body = {"leave_date": (start.date() + timedelta(days=14)).isoformat(), "reason": "conference"}
    url = f"/api/v1/admin/doctors/{doctor['id']}/leaves"
    assert isolated_client.post(url, json=body, headers=admin).status_code == 201

    # A second admin passed the "already on leave?" check before the first committed.
    monkeypatch.setattr(doctor_repository, "get_leave_by_date", lambda *a, **k: None)
    assert isolated_client.post(url, json=body, headers=admin).status_code == 409


def test_cancelling_retires_an_unsent_booking_confirmation(isolated_client, isolated_db):
    from models.notification import NotificationType

    _, doctor, patient, start, end = _bookable_slot(isolated_client, "cancelconf")
    appt = _book(isolated_client, doctor, patient, start, end)
    statuses, NotificationStatus = _jobs(isolated_db, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    assert statuses and all(s == NotificationStatus.PENDING for s in statuses)

    assert isolated_client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient).status_code == 200

    statuses, _ = _jobs(isolated_db, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    assert NotificationStatus.PENDING not in statuses, "an unsent confirmation must not go out for a cancelled appointment"
    assert NotificationStatus.PENDING in _jobs(isolated_db, appt["id"], NotificationType.CANCELLATION)[0]


def test_leave_conflict_retires_an_unsent_booking_confirmation(isolated_client, isolated_db):
    from models.notification import NotificationType

    admin, doctor, patient, start, end = _bookable_slot(isolated_client, "leaveconf")
    appt = _book(isolated_client, doctor, patient, start, end)

    response = isolated_client.post(f"/api/v1/admin/doctors/{doctor['id']}/leaves", json={
        "leave_date": start.date().isoformat(), "reason": "sick"}, headers=admin)
    assert response.status_code == 201, response.text

    statuses, NotificationStatus = _jobs(isolated_db, appt["id"], NotificationType.BOOKING_CONFIRMATION)
    assert NotificationStatus.PENDING not in statuses


def test_public_leave_listing_hides_the_reason_from_non_admins(client):
    admin, doctor, patient, start, _ = _bookable_slot(client, "leavepriv")
    leave_date = (start.date() + timedelta(days=21)).isoformat()
    assert client.post(f"/api/v1/admin/doctors/{doctor['id']}/leaves", json={
        "leave_date": leave_date, "reason": "surgery"}, headers=admin).status_code == 201
    url = f"/api/v1/doctors/{doctor['id']}/leaves"

    for headers in (None, patient, {"Authorization": "Bearer not-a-real-token"}):
        rows = client.get(url, headers=headers).json()
        assert [r["leave_date"] for r in rows] == [leave_date]
        assert rows[0]["reason"] is None
    assert client.get(url, headers=admin).json()[0]["reason"] == "surgery"


def test_registration_rejects_passwords_bcrypt_would_truncate(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "longpw@example.com", "password": "x" * 73, "full_name": "Long Pw", "role": "PATIENT"})
    assert response.status_code == 422
    ok = client.post("/api/v1/auth/register", json={
        "email": "okpw@example.com", "password": "x" * 72, "full_name": "Ok Pw", "role": "PATIENT"})
    assert ok.status_code == 201


def test_login_for_unknown_email_still_spends_a_bcrypt_check(client, monkeypatch):
    import services.auth_service as auth_module

    calls = []
    real = auth_module.verify_password
    monkeypatch.setattr(auth_module, "verify_password", lambda p, h: calls.append(h) or real(p, h))

    response = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    assert response.status_code == 401
    assert len(calls) == 1, "unknown emails must cost the same bcrypt work as a wrong password"
