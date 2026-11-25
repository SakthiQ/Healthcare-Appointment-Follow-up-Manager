"""Departments (#70): admin management, public listing and the doctor search filter."""
from models.audit import AuditLog
from tests.test_appointments import setup_appointment_test_env

ADMIN_URL = "/api/v1/admin/departments"


def _dept(client, admin, name, description=None):
    r = client.post(ADMIN_URL, json={"name": name, "description": description}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def _doctor(client, admin, email, name, department_id=None, specialization="Cardiology"):
    r = client.post("/api/v1/admin/doctors", json={
        "email": email, "password": "password123", "full_name": name,
        "specialization": specialization, "slot_duration_minutes": 30, "department_id": department_id,
    }, headers=admin)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_admin_creates_renames_and_deactivates_departments_and_it_is_audited(client, db_session):
    _, admin, _, _ = setup_appointment_test_env(client)

    cardio = _dept(client, admin, "  Cardiology  ", "Heart care")
    assert cardio["name"] == "Cardiology" and cardio["is_active"] is True and cardio["active_doctor_count"] == 0

    renamed = client.patch(f"{ADMIN_URL}/{cardio['id']}", json={"name": "Cardiology & Vascular"}, headers=admin).json()
    assert renamed["name"] == "Cardiology & Vascular" and renamed["description"] == "Heart care"

    off = client.patch(f"{ADMIN_URL}/{cardio['id']}", json={"is_active": False}, headers=admin).json()
    assert off["is_active"] is False

    actions = [a for (a,) in db_session.query(AuditLog.action).filter(AuditLog.action.like("department.%")).all()]
    assert actions.count("department.create") == 1 and actions.count("department.update") == 2


def test_names_are_unique_regardless_of_case(client):
    _, admin, _, _ = setup_appointment_test_env(client)
    _dept(client, admin, "Cardiology")
    paeds = _dept(client, admin, "Paediatrics")

    assert client.post(ADMIN_URL, json={"name": "cardiology"}, headers=admin).status_code == 409
    assert client.patch(f"{ADMIN_URL}/{paeds['id']}", json={"name": "CARDIOLOGY"}, headers=admin).status_code == 409
    assert client.post(ADMIN_URL, json={"name": "x"}, headers=admin).status_code == 422


def test_only_admins_manage_departments(client):
    _, admin, patient, _ = setup_appointment_test_env(client)
    dept = _dept(client, admin, "Cardiology")

    assert client.post(ADMIN_URL, json={"name": "Neurology"}, headers=patient).status_code == 403
    assert client.patch(f"{ADMIN_URL}/{dept['id']}", json={"is_active": False}, headers=patient).status_code == 403
    assert client.get(ADMIN_URL, headers=patient).status_code == 403
    assert client.post(ADMIN_URL, json={"name": "Neurology"}).status_code == 401


def test_public_list_shows_active_departments_with_active_doctor_counts(client):
    doc, admin, _, _ = setup_appointment_test_env(client)
    cardio = _dept(client, admin, "Cardiology")
    paeds = _dept(client, admin, "Paediatrics")
    closed = _dept(client, admin, "Closed Ward")
    _doctor(client, admin, "c1@example.com", "Dr. One", cardio["id"])
    gone = _doctor(client, admin, "c2@example.com", "Dr. Two", cardio["id"])
    client.patch(f"/api/v1/admin/doctors/{gone['id']}/status", params={"is_active": False}, headers=admin)
    client.patch(f"{ADMIN_URL}/{closed['id']}", json={"is_active": False}, headers=admin)

    public = client.get("/api/v1/departments").json()

    assert [(d["name"], d["active_doctor_count"]) for d in public] == [("Cardiology", 1), ("Paediatrics", 0)]
    every = client.get(ADMIN_URL, headers=admin).json()
    assert {d["name"] for d in every} == {"Cardiology", "Paediatrics", "Closed Ward"}
    assert paeds["id"] in {d["id"] for d in every}


def test_doctor_search_filters_by_department_and_combines_with_other_filters(client):
    doc, admin, _, _ = setup_appointment_test_env(client)  # Dr. Appt: Neurology, no department
    cardio = _dept(client, admin, "Cardiology")
    _doctor(client, admin, "ada@example.com", "Dr. Ada", cardio["id"], specialization="Cardiology")
    _doctor(client, admin, "bea@example.com", "Dr. Bea", cardio["id"], specialization="Electrophysiology")

    names = lambda params: [d["full_name"] for d in client.get("/api/v1/doctors", params=params).json()]  # noqa: E731
    assert names({"department_id": cardio["id"]}) == ["Dr. Ada", "Dr. Bea"]
    assert names({"department_id": cardio["id"], "name": "bea"}) == ["Dr. Bea"]
    assert names({"department_id": cardio["id"], "specialization": "electro"}) == ["Dr. Bea"]
    # A doctor with no department still shows up without the filter.
    assert "Dr. Appt" in names({})
    listed = {d["full_name"]: d for d in client.get("/api/v1/doctors").json()}
    assert listed["Dr. Ada"]["department_name"] == "Cardiology" and listed["Dr. Appt"]["department_id"] is None


def test_setting_and_clearing_a_doctors_department(client):
    doc, admin, _, _ = setup_appointment_test_env(client)
    cardio = _dept(client, admin, "Cardiology")
    url = f"/api/v1/admin/doctors/{doc['id']}"

    set_ = client.put(url, json={"department_id": cardio["id"]}, headers=admin).json()
    assert set_["department_id"] == cardio["id"] and set_["department_name"] == "Cardiology"
    # Leaving department_id out keeps it; sending null clears it.
    assert client.put(url, json={"slot_duration_minutes": 20}, headers=admin).json()["department_id"] == cardio["id"]
    assert client.put(url, json={"department_id": None}, headers=admin).json()["department_id"] is None


def test_cannot_join_a_missing_or_deactivated_department(client):
    doc, admin, _, _ = setup_appointment_test_env(client)
    closed = _dept(client, admin, "Closed Ward")
    client.patch(f"{ADMIN_URL}/{closed['id']}", json={"is_active": False}, headers=admin)
    url = f"/api/v1/admin/doctors/{doc['id']}"

    assert client.put(url, json={"department_id": "no-such-id"}, headers=admin).status_code == 404
    assert client.put(url, json={"department_id": closed["id"]}, headers=admin).status_code == 422
