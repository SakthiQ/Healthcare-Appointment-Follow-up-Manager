"""The doctor's own profile and leave reasons, for the My schedule page (#69)."""
from tests.test_appointments import get_next_monday, setup_appointment_test_env


def _login(client, email):
    token = client.post("/api/v1/auth/login", json={"email": email, "password": "password123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _second_doctor(client, admin):
    return client.post("/api/v1/admin/doctors", json={
        "email": "other_doc@example.com", "password": "password123", "full_name": "Dr. Other",
        "specialization": "Cardiology", "slot_duration_minutes": 30,
    }, headers=admin).json()


def test_a_doctor_gets_their_own_profile(client):
    doc, _, _, _ = setup_appointment_test_env(client)

    r = client.get("/api/v1/doctors/me", headers=_login(client, "doc_appt@example.com"))

    assert r.status_code == 200
    assert r.json()["id"] == doc["id"]
    assert r.json()["full_name"] == "Dr. Appt"


def test_only_doctors_have_a_me_profile(client):
    _, admin, patient, _ = setup_appointment_test_env(client)

    assert client.get("/api/v1/doctors/me").status_code == 401
    assert client.get("/api/v1/doctors/me", headers=patient).status_code == 403
    assert client.get("/api/v1/doctors/me", headers=admin).status_code == 403


def test_a_doctor_sees_their_own_leave_reasons_but_not_anyone_elses(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    other = _second_doctor(client, admin)
    day = get_next_monday().isoformat()
    client.post(f"/api/v1/admin/doctors/{doc['id']}/leaves", json={"leave_date": day, "reason": "Conference"}, headers=admin)
    client.post(f"/api/v1/admin/doctors/{other['id']}/leaves", json={"leave_date": day, "reason": "Surgery"}, headers=admin)
    me = _login(client, "doc_appt@example.com")

    own = client.get(f"/api/v1/doctors/{doc['id']}/leaves", headers=me).json()
    assert [(leave["leave_date"], leave["reason"]) for leave in own] == [(day, "Conference")]

    theirs = client.get(f"/api/v1/doctors/{other['id']}/leaves", headers=me).json()
    assert [leave["reason"] for leave in theirs] == [None]

    as_patient = client.get(f"/api/v1/doctors/{doc['id']}/leaves", headers=patient).json()
    assert [leave["reason"] for leave in as_patient] == [None]
