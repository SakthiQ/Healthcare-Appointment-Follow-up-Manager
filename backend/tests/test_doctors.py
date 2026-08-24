from datetime import date, time
import pytest


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
