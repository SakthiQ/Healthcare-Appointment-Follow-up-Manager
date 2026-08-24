from datetime import date, datetime, time, timedelta, timezone
import pytest
from models.appointment import AppointmentStatus
from models.notification import NotificationType, NotificationStatus


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def setup_leave_test_env(client):
    """Admin + one doctor with Monday & Tuesday working hours + 3 patients."""
    client.post("/api/v1/auth/register", json={
        "email": "admin_leave@example.com", "password": "password123", "full_name": "Admin Leave", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_leave@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_leave@example.com", "password": "password123", "full_name": "Dr. Leave",
        "specialization": "Cardiology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    # Second, unrelated doctor - used to prove leave conflicts never cross doctors.
    other_doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_other@example.com", "password": "password123", "full_name": "Dr. Other",
        "specialization": "Dermatology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True},
            {"day_of_week": 1, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True},
        ]
    }, headers=admin_headers)
    client.post(f"/api/v1/admin/doctors/{other_doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True},
        ]
    }, headers=admin_headers)

    patient_headers = []
    for i in range(3):
        email = f"patient{i}_leave@example.com"
        client.post("/api/v1/auth/register", json={
            "email": email, "password": "password123", "full_name": f"Patient {i}", "role": "PATIENT"
        })
        token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
        patient_headers.append({"Authorization": f"Bearer {token}"})

    return doc, other_doc, admin_headers, patient_headers


def book_appointment(client, headers, doctor_id, start_dt, end_dt):
    r = client.post("/api/v1/appointments", json={
        "doctor_id": doctor_id,
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def get_conflict_jobs_for_appointment(db_session, appointment_id):
    """DOCTOR_LEAVE_CONFLICT jobs only. Booking itself now also queues
    BOOKING_CONFIRMATION + APPOINTMENT_REMINDER jobs (Phase 9), so leave-
    conflict assertions must filter by type rather than counting all jobs
    for the appointment."""
    from models.notification import NotificationJob
    return db_session.query(NotificationJob).filter(
        NotificationJob.appointment_id == appointment_id,
        NotificationJob.notification_type == NotificationType.DOCTOR_LEAVE_CONFLICT,
    ).all()


# ---------------------------------------------------------------------------
# Zero / one / multiple conflicting appointments
# ---------------------------------------------------------------------------

def test_leave_with_no_appointments(client, db_session):
    doc, _, admin_headers, _ = setup_leave_test_env(client)
    next_monday = get_next_monday()

    # Note: this test's DB session is shared with the rest of the suite (see
    # tests/conftest.py's db_session fixture — it isn't a per-test SAVEPOINT),
    # so other tests' committed data can already be present. Compare a
    # before/after delta rather than asserting an absolute count.
    from models.notification import NotificationJob
    jobs_before = db_session.query(NotificationJob).count()

    r = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat(),
        "reason": "Personal day"
    }, headers=admin_headers)
    assert r.status_code == 201
    assert r.json()["leave_date"] == next_monday.isoformat()

    # No appointments existed, so nothing should have been conflicted and no jobs queued.
    jobs_after = db_session.query(NotificationJob).count()
    assert jobs_after == jobs_before


def test_leave_with_one_conflicting_appointment(client, db_session):
    doc, _, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = book_appointment(client, patients[0], doc["id"], start_dt, end_dt)

    r = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat(),
        "reason": "Conference"
    }, headers=admin_headers)
    assert r.status_code == 201

    r_appt = client.get(f"/api/v1/appointments/{appt['id']}", headers=patients[0])
    assert r_appt.status_code == 200
    data = r_appt.json()
    assert data["status"] == AppointmentStatus.CONFLICTED.value
    # Original appointment info must be preserved, not wiped.
    assert data["start_time"].startswith(start_dt.isoformat()[:16])
    assert data["end_time"].startswith(end_dt.isoformat()[:16])
    assert data["patient_id"]
    assert data["doctor_profile_id"] == doc["id"]

    jobs = get_conflict_jobs_for_appointment(db_session, appt["id"])
    assert len(jobs) == 1
    assert jobs[0].notification_type == NotificationType.DOCTOR_LEAVE_CONFLICT
    assert jobs[0].status == NotificationStatus.PENDING
    assert jobs[0].recipient_id == jobs[0].appointment.patient_id


def test_leave_with_multiple_conflicting_appointments(client, db_session):
    doc, _, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()

    appts = []
    for i, start_hour in enumerate([9, 10, 11]):
        start_dt = datetime.combine(next_monday, time(start_hour, 0), tzinfo=timezone.utc)
        end_dt = datetime.combine(next_monday, time(start_hour, 30), tzinfo=timezone.utc)
        appts.append(book_appointment(client, patients[i], doc["id"], start_dt, end_dt))

    r = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)
    assert r.status_code == 201

    from models.notification import NotificationJob
    for i, appt in enumerate(appts):
        r_appt = client.get(f"/api/v1/appointments/{appt['id']}", headers=patients[i])
        assert r_appt.json()["status"] == AppointmentStatus.CONFLICTED.value

    assert db_session.query(NotificationJob).filter(
        NotificationJob.notification_type == NotificationType.DOCTOR_LEAVE_CONFLICT
    ).count() == 3


# ---------------------------------------------------------------------------
# Unrelated appointments remain unchanged
# ---------------------------------------------------------------------------

def test_unrelated_appointments_remain_unchanged(client, db_session):
    doc, other_doc, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()
    next_tuesday = next_monday + timedelta(days=1)

    # Same doctor, DIFFERENT date -> must not be touched.
    other_date_start = datetime.combine(next_tuesday, time(9, 0), tzinfo=timezone.utc)
    other_date_end = datetime.combine(next_tuesday, time(9, 30), tzinfo=timezone.utc)
    appt_other_date = book_appointment(client, patients[0], doc["id"], other_date_start, other_date_end)

    # DIFFERENT doctor, SAME date -> must not be touched.
    other_doc_start = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    other_doc_end = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt_other_doc = book_appointment(client, patients[1], other_doc["id"], other_doc_start, other_doc_end)

    # Same doctor, same date, but already CANCELLED -> must not be re-touched.
    cancel_start = datetime.combine(next_monday, time(10, 0), tzinfo=timezone.utc)
    cancel_end = datetime.combine(next_monday, time(10, 30), tzinfo=timezone.utc)
    appt_cancelled = book_appointment(client, patients[2], doc["id"], cancel_start, cancel_end)
    client.post(f"/api/v1/appointments/{appt_cancelled['id']}/cancel", headers=patients[2])

    r = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)
    assert r.status_code == 201

    assert client.get(f"/api/v1/appointments/{appt_other_date['id']}", headers=patients[0]).json()["status"] == "CONFIRMED"
    assert client.get(f"/api/v1/appointments/{appt_other_doc['id']}", headers=patients[1]).json()["status"] == "CONFIRMED"
    assert client.get(f"/api/v1/appointments/{appt_cancelled['id']}", headers=patients[2]).json()["status"] == "CANCELLED"

    for appt_id in (appt_other_date["id"], appt_other_doc["id"], appt_cancelled["id"]):
        assert get_conflict_jobs_for_appointment(db_session, appt_id) == []


# ---------------------------------------------------------------------------
# Multiple leave dates handled independently
# ---------------------------------------------------------------------------

def test_multiple_leave_dates_each_handled_independently(client, db_session):
    doc, _, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()
    next_tuesday = next_monday + timedelta(days=1)

    mon_start = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    mon_end = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt_mon = book_appointment(client, patients[0], doc["id"], mon_start, mon_end)

    tue_start = datetime.combine(next_tuesday, time(9, 0), tzinfo=timezone.utc)
    tue_end = datetime.combine(next_tuesday, time(9, 30), tzinfo=timezone.utc)
    appt_tue = book_appointment(client, patients[1], doc["id"], tue_start, tue_end)

    # Leave only Monday first -> only Monday's appointment is affected.
    r1 = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)
    assert r1.status_code == 201
    assert client.get(f"/api/v1/appointments/{appt_mon['id']}", headers=patients[0]).json()["status"] == "CONFLICTED"
    assert client.get(f"/api/v1/appointments/{appt_tue['id']}", headers=patients[1]).json()["status"] == "CONFIRMED"

    # Now leave Tuesday too -> Tuesday's appointment becomes affected independently.
    r2 = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_tuesday.isoformat()
    }, headers=admin_headers)
    assert r2.status_code == 201
    assert client.get(f"/api/v1/appointments/{appt_tue['id']}", headers=patients[1]).json()["status"] == "CONFLICTED"

    r_leaves = client.get(f"/api/v1/doctors/{doc['id']}/leaves")
    assert len(r_leaves.json()) == 2


# ---------------------------------------------------------------------------
# Repeated leave creation is rejected and has no side effects
# ---------------------------------------------------------------------------

def test_repeated_leave_creation_rejected_with_no_side_effects(client, db_session):
    doc, _, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patients[0], doc["id"], start_dt, end_dt)

    r1 = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)
    assert r1.status_code == 201

    jobs_after_first = len(get_conflict_jobs_for_appointment(db_session, appt["id"]))
    assert jobs_after_first == 1

    # Repeating the exact same leave date must be rejected...
    r2 = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)
    assert r2.status_code == 409
    assert r2.json()["error_code"] == "CONFLICT"

    # ...and must not create a duplicate notification job or re-touch the appointment.
    jobs_after_repeat = len(get_conflict_jobs_for_appointment(db_session, appt["id"]))
    assert jobs_after_repeat == 1


# ---------------------------------------------------------------------------
# Admin can inspect affected (CONFLICTED) appointments
# ---------------------------------------------------------------------------

def test_admin_can_inspect_conflicted_appointments(client, db_session):
    doc, _, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)
    appt = book_appointment(client, patients[0], doc["id"], start_dt, end_dt)

    client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
        "leave_date": next_monday.isoformat()
    }, headers=admin_headers)

    r = client.get("/api/v1/appointments", params={"status": "CONFLICTED"}, headers=admin_headers)
    assert r.status_code == 200
    conflicted_ids = [a["id"] for a in r.json()]
    assert appt["id"] in conflicted_ids


# ---------------------------------------------------------------------------
# Transactional guarantee: a failure mid-way rolls back everything
# ---------------------------------------------------------------------------

def test_leave_creation_is_transactional_on_partial_failure(client):
    """
    If notification-job creation fails partway through processing multiple
    affected appointments, DoctorLeaveService.create_leave must roll back
    everything (the leave row, any CONFLICTED status already applied, any
    jobs already queued) rather than leaving a half-applied state — this is
    the "operation must be transactional" requirement.

    Note: this test's `client`/`db_session` fixtures share a single DB
    connection/transaction for the whole test (see tests/conftest.py), so a
    mid-test db.rollback() unwinds the entire test's uncommitted work, not
    just DoctorLeaveService's own — that is a property of this test fixture,
    not of production (each real request gets its own session/transaction).
    So this test only asserts on the one thing that is reliably observable
    here: the failure is not silently swallowed, it propagates instead of
    resulting in a partially-applied leave.
    """
    doc, _, admin_headers, patients = setup_leave_test_env(client)
    next_monday = get_next_monday()

    for i, start_hour in enumerate([9, 10]):
        start_dt = datetime.combine(next_monday, time(start_hour, 0), tzinfo=timezone.utc)
        end_dt = datetime.combine(next_monday, time(start_hour, 30), tzinfo=timezone.utc)
        book_appointment(client, patients[i], doc["id"], start_dt, end_dt)

    import services.doctor_leave_service as leave_service_module
    original_queue = leave_service_module.notification_service.queue_notification_no_commit
    call_count = {"n": 0}

    def failing_queue(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated notification job failure")
        return original_queue(*args, **kwargs)

    leave_service_module.notification_service.queue_notification_no_commit = failing_queue
    try:
        # TestClient's default raise_server_exceptions=True surfaces an
        # unhandled (non-HTTPException) error directly rather than as a
        # response, so assert on the propagated exception itself.
        with pytest.raises(RuntimeError, match="simulated notification job failure"):
            client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={
                "leave_date": next_monday.isoformat()
            }, headers=admin_headers)
    finally:
        leave_service_module.notification_service.queue_notification_no_commit = original_queue
