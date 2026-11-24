"""A patient's own health history (#66)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from models.appointment import Appointment, AppointmentStatus
from models.audit import AuditLog
from models.clinical import AISummary, AISummaryStatus, AISummaryType, Consultation, Medication, Prescription
from tests.conftest import test_engine
from tests.test_appointments import setup_appointment_test_env

URL = "/api/v1/patients/me/history"


def _me(client, headers):
    return client.get("/api/v1/auth/me", headers=headers).json()["id"]


def _visit(db, doc, patient_id, days_ago, status=AppointmentStatus.COMPLETED, meds=("Amoxicillin",), follow_up="Rest"):
    start = datetime.now(timezone.utc) - timedelta(days=days_ago)
    appt = Appointment(patient_id=patient_id, doctor_id=doc["user_id"], doctor_profile_id=doc["id"],
                       start_time=start, end_time=start + timedelta(minutes=30), status=status)
    db.add(appt)
    db.flush()
    consultation = Consultation(appointment_id=appt.id, notes="Private clinical notes")
    db.add(consultation)
    db.flush()
    prescription = Prescription(consultation_id=consultation.id, instructions="After meals")
    db.add(prescription)
    db.flush()
    for name in meds:
        db.add(Medication(prescription_id=prescription.id, name=name, dosage="500mg", frequency="3x daily", duration_days=5))
    if follow_up:
        db.add(AISummary(appointment_id=appt.id, type=AISummaryType.POST_VISIT, status=AISummaryStatus.SUCCESS,
                         payload={"summary": "s", "medication_schedule": "m", "follow_up_steps": follow_up}))
    db.commit()
    return appt.id


def test_lists_only_completed_visits_newest_first_with_prescriptions(client, db_session):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    doc = client.get(f"/api/v1/doctors/{doc['id']}", headers=admin).json()
    me = _me(client, patient)
    older = _visit(db_session, doc, me, days_ago=60, follow_up="Come back in a month")
    newer = _visit(db_session, doc, me, days_ago=5, meds=("Ibuprofen", "Paracetamol"))
    _visit(db_session, doc, me, days_ago=2, status=AppointmentStatus.CANCELLED)

    r = client.get(URL, headers=patient)

    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "2"
    items = r.json()
    assert [i["appointment_id"] for i in items] == [newer, older]
    assert items[0]["doctor_name"] == "Dr. Appt" and items[0]["doctor_specialization"] == "Neurology"
    assert [m["name"] for m in items[0]["medications"]] == ["Ibuprofen", "Paracetamol"]
    assert items[0]["instructions"] == "After meals"
    assert items[1]["follow_up_steps"] == "Come back in a month"
    assert "Private clinical notes" not in r.text  # consultation notes are not part of the history


def test_never_shows_another_patients_visits(client, db_session):
    doc, admin, patient, other = setup_appointment_test_env(client)
    doc = client.get(f"/api/v1/doctors/{doc['id']}", headers=admin).json()
    _visit(db_session, doc, _me(client, other), days_ago=3)

    r = client.get(URL, headers=patient)

    assert r.json() == [] and r.headers["X-Total-Count"] == "0"


def test_pages_through_the_history(client, db_session):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    doc = client.get(f"/api/v1/doctors/{doc['id']}", headers=admin).json()
    me = _me(client, patient)
    ids = [_visit(db_session, doc, me, days_ago=d) for d in (1, 2, 3, 4, 5)]  # ids[0] is newest

    first = client.get(URL, params={"limit": 2, "offset": 0}, headers=patient)
    last = client.get(URL, params={"limit": 2, "offset": 4}, headers=patient)

    assert [i["appointment_id"] for i in first.json()] == ids[:2]
    assert [i["appointment_id"] for i in last.json()] == ids[4:]
    assert first.headers["X-Total-Count"] == last.headers["X-Total-Count"] == "5"


def test_other_roles_get_403(client):
    _, admin, _, _ = setup_appointment_test_env(client)
    doctor = client.post("/api/v1/auth/login", json={"email": "doc_appt@example.com", "password": "password123"}).json()
    assert client.get(URL, headers=admin).status_code == 403
    assert client.get(URL, headers={"Authorization": f"Bearer {doctor['access_token']}"}).status_code == 403
    assert client.get(URL).status_code == 401


def test_each_call_is_audited(client, db_session):
    _, _, patient, _ = setup_appointment_test_env(client)
    me = _me(client, patient)

    client.get(URL, headers=patient)

    entries = db_session.query(AuditLog).filter(AuditLog.action == "patient.history.view").all()
    assert len(entries) == 1 and entries[0].patient_id == me


def test_query_count_does_not_grow_with_the_page(client, db_session):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    doc = client.get(f"/api/v1/doctors/{doc['id']}", headers=admin).json()
    me = _me(client, patient)
    statements = []

    def count(*_args, **_kwargs):
        statements.append(1)

    _visit(db_session, doc, me, days_ago=1)
    event.listen(test_engine, "before_cursor_execute", count)
    try:
        client.get(URL, headers=patient)
        one = len(statements)
        for d in range(2, 12):
            _visit(db_session, doc, me, days_ago=d, meds=("A", "B", "C"))
        statements.clear()
        client.get(URL, headers=patient)
        eleven = len(statements)
    finally:
        event.remove(test_engine, "before_cursor_execute", count)

    assert one > 0  # the listener really sees the app's queries
    assert eleven == one, f"{one} queries for 1 visit but {eleven} for 11"
