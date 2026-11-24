"""Patient health profile: own edits, validation, and tight, audited doctor access (#67)."""
from datetime import date, datetime, time, timedelta, timezone

from models.audit import AuditLog
from services.patient_profile_service import age_on
from tests.test_appointments import get_next_monday, setup_appointment_test_env

ME = "/api/v1/patients/me/profile"


def _login(client, email):
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _book(client, doc, headers):
    monday = get_next_monday()
    return client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": datetime.combine(monday, time(9, 0), tzinfo=timezone.utc).isoformat(),
        "end_time": datetime.combine(monday, time(9, 30), tzinfo=timezone.utc).isoformat(),
    }, headers=headers).json()


def test_a_patient_reads_and_updates_their_own_profile(client):
    _, _, patient, _ = setup_appointment_test_env(client)

    assert client.get(ME, headers=patient).json() == {"date_of_birth": None, "phone": None, "allergies": None, "updated_at": None}
    r = client.put(ME, json={"date_of_birth": "1990-05-17", "phone": " +91 98765 43210 ", "allergies": "Penicillin"},
                   headers=patient)

    assert r.status_code == 200
    body = client.get(ME, headers=patient).json()
    assert body["date_of_birth"] == "1990-05-17" and body["phone"] == "+91 98765 43210" and body["allergies"] == "Penicillin"
    # Every field is optional, and null clears it.
    client.put(ME, json={"allergies": None}, headers=patient)
    assert client.get(ME, headers=patient).json()["allergies"] is None


def test_validation(client):
    _, _, patient, _ = setup_appointment_test_env(client)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    assert client.put(ME, json={"date_of_birth": tomorrow}, headers=patient).status_code == 422
    assert client.put(ME, json={"phone": "1" * 33}, headers=patient).status_code == 422
    assert client.put(ME, json={"allergies": "x" * 1001}, headers=patient).status_code == 422


def test_only_patients_have_a_profile(client):
    _, admin, _, _ = setup_appointment_test_env(client)
    assert client.get(ME, headers=admin).status_code == 403
    assert client.get(ME).status_code == 401


def test_the_appointments_doctor_sees_age_and_allergies_and_it_is_audited(client, db_session):
    doc, _, patient, _ = setup_appointment_test_env(client)
    client.put(ME, json={"date_of_birth": "1990-05-17", "allergies": "Penicillin"}, headers=patient)
    appt = _book(client, doc, patient)

    r = client.get(f"/api/v1/appointments/{appt['id']}/patient-health", headers=_login(client, "doc_appt@example.com"))

    assert r.status_code == 200
    assert r.json() == {"age": age_on(date(1990, 5, 17), date.today()), "allergies": "Penicillin"}
    assert "1990" not in r.text  # the age, never the date of birth
    entries = db_session.query(AuditLog).filter(AuditLog.action == "patient.health.view").all()
    assert len(entries) == 1 and entries[0].patient_id == appt["patient_id"]


def test_another_doctor_and_the_patient_get_nothing(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    client.post("/api/v1/admin/doctors", json={
        "email": "other_doc@example.com", "password": "password123", "full_name": "Dr. Other",
        "specialization": "Cardiology", "slot_duration_minutes": 30}, headers=admin)
    appt = _book(client, doc, patient)
    url = f"/api/v1/appointments/{appt['id']}/patient-health"

    assert client.get(url, headers=_login(client, "other_doc@example.com")).status_code == 403
    assert client.get(url, headers=patient).status_code == 403
    assert client.get(url, headers=admin).status_code == 200


def test_no_profile_means_nothing_recorded(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)

    r = client.get(f"/api/v1/appointments/{appt['id']}/patient-health", headers=admin)

    assert r.json() == {"age": None, "allergies": None}


def test_age_counts_birthdays():
    assert age_on(date(2000, 6, 15), date(2030, 6, 14)) == 29
    assert age_on(date(2000, 6, 15), date(2030, 6, 15)) == 30
    assert age_on(None, date(2030, 1, 1)) is None
