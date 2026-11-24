from datetime import date, datetime, time, timedelta, timezone


def get_admin_headers(client):
    """Helper fixture creating an Admin user and returning Bearer auth header."""
    client.post("/api/v1/auth/register", json={
        "email": "admin_doc_test@example.com",
        "password": "adminpassword123",
        "full_name": "Admin Tester",
        "role": "ADMIN"
    })
    token = client.post("/api/v1/auth/login", json={
        "email": "admin_doc_test@example.com",
        "password": "adminpassword123"
    }).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def get_patient_headers(client):
    """Helper fixture creating a Patient user and returning Bearer auth header."""
    client.post("/api/v1/auth/register", json={
        "email": "patient_doc_test@example.com",
        "password": "patientpassword123",
        "full_name": "Patient Tester",
        "role": "PATIENT"
    })
    token = client.post("/api/v1/auth/login", json={
        "email": "patient_doc_test@example.com",
        "password": "patientpassword123"
    }).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_doctor_creation_and_permissions(client):
    """Test Admin can create a doctor profile, non-admin receives 403 Forbidden."""
    admin_headers = get_admin_headers(client)
    patient_headers = get_patient_headers(client)

    doc_payload = {
        "email": "cardio_doc@example.com",
        "password": "docpassword123",
        "full_name": "Dr. Hearts",
        "specialization": "Cardiology",
        "slot_duration_minutes": 30
    }

    # Patient attempting to create doctor -> 403 Forbidden
    r_patient = client.post("/api/v1/admin/doctors", json=doc_payload, headers=patient_headers)
    assert r_patient.status_code == 403

    # Admin creating doctor -> 201 Created
    r_admin = client.post("/api/v1/admin/doctors", json=doc_payload, headers=admin_headers)
    assert r_admin.status_code == 201
    data = r_admin.json()
    assert data["specialization"] == "Cardiology"
    assert data["slot_duration_minutes"] == 30
    assert data["is_active"] is True


def test_admin_doctor_update(client):
    """Test Admin updating doctor specialization and slot duration."""
    admin_headers = get_admin_headers(client)

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "update_doc@example.com",
        "password": "docpassword123",
        "full_name": "Dr. Update",
        "specialization": "General",
        "slot_duration_minutes": 15
    }, headers=admin_headers).json()

    update_payload = {
        "specialization": "Internal Medicine",
        "slot_duration_minutes": 45
    }
    r_update = client.put(f"/api/v1/admin/doctors/{doc['id']}", json=update_payload, headers=admin_headers)
    assert r_update.status_code == 200
    updated_data = r_update.json()
    assert updated_data["specialization"] == "Internal Medicine"
    assert updated_data["slot_duration_minutes"] == 45


def test_specialization_search_and_inactive_doctor_behavior(client):
    """Test doctor search by specialization and filtering out inactive doctors."""
    admin_headers = get_admin_headers(client)

    # Create 2 Cardiology doctors (1 active, 1 inactive) and 1 Dermatology doctor
    d1 = client.post("/api/v1/admin/doctors", json={
        "email": "c1@example.com", "password": "pass1234", "full_name": "Dr. Active Cardio",
        "specialization": "Cardiology"
    }, headers=admin_headers).json()

    d2 = client.post("/api/v1/admin/doctors", json={
        "email": "c2@example.com", "password": "pass1234", "full_name": "Dr. Inactive Cardio",
        "specialization": "Cardiology"
    }, headers=admin_headers).json()

    d3 = client.post("/api/v1/admin/doctors", json={
        "email": "derm1@example.com", "password": "pass1234", "full_name": "Dr. Derm",
        "specialization": "Dermatology"
    }, headers=admin_headers).json()

    # Deactivate d2
    client.patch(f"/api/v1/admin/doctors/{d2['id']}/status?is_active=false", headers=admin_headers)

    # Search Cardiology (public) — only active doctors should appear
    search_cardio = client.get("/api/v1/doctors?specialization=Cardiology").json()
    cardio_ids = [d["id"] for d in search_cardio]
    assert d1["id"] in cardio_ids, "Active Cardiology doctor should appear in search results"
    assert d2["id"] not in cardio_ids, "Inactive Cardiology doctor must NOT appear in search results"

    # Search Dermatology (public) — only d3 among our created doctors
    search_derm = client.get("/api/v1/doctors?specialization=Dermatology").json()
    derm_ids = [d["id"] for d in search_derm]
    assert d3["id"] in derm_ids, "Dermatology doctor should appear in search results"


def test_search_by_name_combines_with_specialization_and_hides_inactive(client):
    admin_headers = get_admin_headers(client)

    def make(email, name, spec):
        return client.post("/api/v1/admin/doctors", json={
            "email": email, "password": "pass1234", "full_name": name, "specialization": spec,
        }, headers=admin_headers).json()

    rao = make("rao@example.com", "Dr. Priya Rao", "Cardiology")
    rao_derm = make("rao2@example.com", "Dr. Arun Rao", "Dermatology")
    other = make("menon@example.com", "Dr. Kavya Menon", "Cardiology")
    gone = make("raoold@example.com", "Dr. Old Rao", "Cardiology")
    client.patch(f"/api/v1/admin/doctors/{gone['id']}/status?is_active=false", headers=admin_headers)

    def ids(params):
        r = client.get("/api/v1/doctors", params=params)
        assert r.status_code == 200, r.text
        return {d["id"] for d in r.json()}

    # Part of the name, any case; inactive doctors stay hidden from the public search.
    assert ids({"name": "rao"}) == {rao["id"], rao_derm["id"]}
    assert ids({"name": "  PRIYA "}) == {rao["id"]}
    # Name and specialization together.
    assert ids({"name": "rao", "specialization": "cardio"}) == {rao["id"]}
    assert other["id"] in ids({"specialization": "Cardiology"})


def test_search_treats_like_wildcards_literally(client):
    admin_headers = get_admin_headers(client)
    plain = client.post("/api/v1/admin/doctors", json={
        "email": "plain@example.com", "password": "pass1234", "full_name": "Dr. Plain",
        "specialization": "General Practice",
    }, headers=admin_headers).json()
    odd = client.post("/api/v1/admin/doctors", json={
        "email": "odd@example.com", "password": "pass1234", "full_name": "Dr. 100% Sure_Name",
        "specialization": "Odd_Spec",
    }, headers=admin_headers).json()

    def ids(params):
        return {d["id"] for d in client.get("/api/v1/doctors", params=params).json()}

    # "%" and "_" used to be wildcards, so they matched every doctor.
    assert ids({"name": "_"}) == {odd["id"]}
    assert ids({"name": "%"}) == {odd["id"]}
    assert ids({"specialization": "_"}) == {odd["id"]}
    assert ids({"name": "100%"}) == {odd["id"]}
    assert plain["id"] not in ids({"name": "\\"})
    # A blank search means no filter.
    assert {plain["id"], odd["id"]} <= ids({"name": "   "})


def test_working_hours_configuration_and_invalid_schedule_rejection(client):
    """Test configuring working hours and rejecting invalid schedules."""
    admin_headers = get_admin_headers(client)

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "sched_doc@example.com", "password": "pass1234", "full_name": "Dr. Sched",
        "specialization": "Pediatrics"
    }, headers=admin_headers).json()

    # Valid schedule
    valid_schedule = {
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "17:00:00", "is_active": True},
            {"day_of_week": 1, "start_time": "09:00:00", "end_time": "13:00:00", "is_active": True}
        ]
    }
    r_valid = client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json=valid_schedule, headers=admin_headers)
    assert r_valid.status_code == 200
    assert len(r_valid.json()) == 2

    # Invalid schedule: end_time before start_time -> 422 Unprocessable Entity
    invalid_times = {
        "working_hours": [
            {"day_of_week": 2, "start_time": "17:00:00", "end_time": "09:00:00", "is_active": True}
        ]
    }
    r_invalid = client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json=invalid_times, headers=admin_headers)
    assert r_invalid.status_code == 422

    # Duplicate day_of_week -> 422 Unprocessable Entity
    dup_days = {
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True},
            {"day_of_week": 0, "start_time": "13:00:00", "end_time": "17:00:00", "is_active": True}
        ]
    }
    r_dup = client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json=dup_days, headers=admin_headers)
    assert r_dup.status_code == 422


def test_slot_duration_validation(client):
    """Test validation bounds for doctor slot duration."""
    admin_headers = get_admin_headers(client)

    # Invalid slot duration (< 5 mins)
    r_low = client.post("/api/v1/admin/doctors", json={
        "email": "low_slot@example.com", "password": "pass1234", "full_name": "Dr. Low",
        "specialization": "GP", "slot_duration_minutes": 2
    }, headers=admin_headers)
    assert r_low.status_code == 422

    # Invalid slot duration (> 240 mins)
    r_high = client.post("/api/v1/admin/doctors", json={
        "email": "high_slot@example.com", "password": "pass1234", "full_name": "Dr. High",
        "specialization": "GP", "slot_duration_minutes": 300
    }, headers=admin_headers)
    assert r_high.status_code == 422


def test_leave_creation_retrieval_and_duplicate_prevention(client):
    """Test creating doctor leave dates, retrieving leave dates, and rejecting duplicate leave dates."""
    admin_headers = get_admin_headers(client)

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "leave_doc@example.com", "password": "pass1234", "full_name": "Dr. Leave",
        "specialization": "Orthopedics"
    }, headers=admin_headers).json()

    leave_payload = {
        "leave_date": "2026-10-15",
        "reason": "Attending Medical Conference"
    }

    # Admin creates leave
    r_leave = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json=leave_payload, headers=admin_headers)
    assert r_leave.status_code == 201
    assert r_leave.json()["leave_date"] == "2026-10-15"

    # Duplicate leave date returns 409 Conflict
    r_dup = client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json=leave_payload, headers=admin_headers)
    assert r_dup.status_code == 409
    assert r_dup.json()["error_code"] == "CONFLICT"

    # Patient retrieves leave dates (public)
    r_get = client.get(f"/api/v1/doctors/{doc['id']}/leaves")
    assert r_get.status_code == 200
    assert len(r_get.json()) == 1
    assert r_get.json()[0]["leave_date"] == "2026-10-15"


def test_doctor_login_email_and_account_id_are_for_admins_only(client):
    """The doctor endpoints need no sign-in, so they must not hand out staff login emails."""
    admin_headers = get_admin_headers(client)
    patient_headers = get_patient_headers(client)
    doc = client.post("/api/v1/admin/doctors", json={
        "email": "private_doc@example.com", "password": "pass1234", "full_name": "Dr. Private",
        "specialization": "Urology"
    }, headers=admin_headers).json()
    assert doc["email"] == "private_doc@example.com" and doc["user_id"]  # the admin who created it

    for headers in (None, patient_headers):
        listed = next(d for d in client.get("/api/v1/doctors", headers=headers).json() if d["id"] == doc["id"])
        single = client.get(f"/api/v1/doctors/{doc['id']}", headers=headers).json()
        for seen in (listed, single):
            assert seen["email"] is None and seen["user_id"] is None
            assert seen["full_name"] == "Dr. Private" and seen["specialization"] == "Urology"

    listed = next(d for d in client.get("/api/v1/doctors", headers=admin_headers).json() if d["id"] == doc["id"])
    single = client.get(f"/api/v1/doctors/{doc['id']}", headers=admin_headers).json()
    for seen in (listed, single):
        assert seen["email"] == "private_doc@example.com" and seen["user_id"] == doc["user_id"]


def test_admin_doctor_list_includes_deactivated_doctors(client):
    """Otherwise a deactivated doctor vanishes from the admin's list and cannot be found again."""
    admin_headers = get_admin_headers(client)
    doc = client.post("/api/v1/admin/doctors", json={
        "email": "hidden_doc@example.com", "password": "pass1234", "full_name": "Dr. Hidden",
        "specialization": "Oncology"
    }, headers=admin_headers).json()
    client.patch(f"/api/v1/admin/doctors/{doc['id']}/status?is_active=false", headers=admin_headers)

    public_ids = [d["id"] for d in client.get("/api/v1/doctors").json()]
    admin_view = {d["id"]: d for d in client.get("/api/v1/doctors", headers=admin_headers).json()}
    assert doc["id"] not in public_ids
    assert admin_view[doc["id"]]["is_active"] is False


def test_doctor_password_over_the_bcrypt_limit_is_rejected_not_a_500(client):
    admin_headers = get_admin_headers(client)
    r = client.post("/api/v1/admin/doctors", json={
        "email": "longpw_doc@example.com", "password": "x" * 73, "full_name": "Dr. Long",
        "specialization": "GP"
    }, headers=admin_headers)
    assert r.status_code == 422


def _doctor_with_one_booking(client, admin_headers, patient_headers, tag):
    """A doctor working Mondays 09:00-12:00 with one future appointment."""
    doc = client.post("/api/v1/admin/doctors", json={
        "email": f"{tag}@example.com", "password": "docpassword123", "full_name": "Dr. Leaving",
        "specialization": "Cardiology", "slot_duration_minutes": 30
    }, headers=admin_headers).json()
    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={"working_hours": [
        {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}
    ]}, headers=admin_headers)
    today = date.today()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7) + timedelta(days=49)
    start = datetime.combine(monday, time(9, 0), tzinfo=timezone.utc)
    booking = {"doctor_id": doc["id"], "start_time": start.isoformat(),
               "end_time": (start + timedelta(minutes=30)).isoformat()}
    r = client.post("/api/v1/appointments", json=booking, headers=patient_headers)
    assert r.status_code == 201, r.text
    return doc, r.json(), booking


def test_deactivating_a_doctor_blocks_sign_in_and_resolves_upcoming_appointments(client, db_session):
    """Deactivation is more than a search filter: the doctor can no longer sign in, and
    patients are not left holding a confirmed appointment nobody will attend."""
    from models.notification import NotificationJob, NotificationStatus, NotificationType
    from services.notification_service import notification_service

    admin_headers = get_admin_headers(client)
    patient_headers = get_patient_headers(client)
    doc, appt, booking = _doctor_with_one_booking(client, admin_headers, patient_headers, "leaving_doc")
    login = {"email": "leaving_doc@example.com", "password": "docpassword123"}
    doctor_headers = {"Authorization": f"Bearer {client.post('/api/v1/auth/login', json=login).json()['access_token']}"}
    assert client.get("/api/v1/appointments", headers=doctor_headers).status_code == 200

    r = client.patch(f"/api/v1/admin/doctors/{doc['id']}/status?is_active=false", headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is False

    # The doctor is signed out and cannot sign back in.
    assert client.get("/api/v1/appointments", headers=doctor_headers).status_code == 401
    assert client.post("/api/v1/auth/login", json=login).status_code == 401

    # The upcoming appointment is conflicted, and the patient is told.
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=patient_headers).json()["status"] == "CONFLICTED"
    jobs = db_session.query(NotificationJob).filter(NotificationJob.appointment_id == appt["id"]).all()
    conflict_jobs = [j for j in jobs if j.notification_type == NotificationType.DOCTOR_LEAVE_CONFLICT]
    assert len(conflict_jobs) == 1 and conflict_jobs[0].recipient_id == appt["patient_id"]
    body = notification_service._build_content(db_session, conflict_jobs[0]).text
    assert "no longer available" in body and "book a new appointment" in body
    # Nothing still queued says the appointment is going ahead.
    going_ahead = [j for j in jobs if j.notification_type in (
        NotificationType.APPOINTMENT_REMINDER, NotificationType.BOOKING_CONFIRMATION)]
    assert going_ahead and all(j.status == NotificationStatus.FAILED for j in going_ahead)

    # No new bookings while deactivated.
    assert client.post("/api/v1/appointments", json=booking, headers=patient_headers).status_code == 422

    # Reactivating restores sign-in and booking. The conflicted appointment stays
    # conflicted (the patient has been told), and its slot is free to book again.
    r = client.patch(f"/api/v1/admin/doctors/{doc['id']}/status?is_active=true", headers=admin_headers)
    assert r.status_code == 200 and r.json()["is_active"] is True
    assert client.post("/api/v1/auth/login", json=login).status_code == 200
    assert client.get("/api/v1/appointments", headers=doctor_headers).status_code == 401  # old session stays dead
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=patient_headers).json()["status"] == "CONFLICTED"
    assert client.post("/api/v1/appointments", json=booking, headers=patient_headers).status_code == 201


def test_deactivating_through_the_update_endpoint_behaves_the_same(client):
    admin_headers = get_admin_headers(client)
    patient_headers = get_patient_headers(client)
    doc, appt, _ = _doctor_with_one_booking(client, admin_headers, patient_headers, "put_doc")

    r = client.put(f"/api/v1/admin/doctors/{doc['id']}", json={"is_active": False, "specialization": "Neurology"},
                   headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is False and r.json()["specialization"] == "Neurology"
    assert client.post("/api/v1/auth/login", json={
        "email": "put_doc@example.com", "password": "docpassword123"}).status_code == 401
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=patient_headers).json()["status"] == "CONFLICTED"
