"""Admin CSV export of appointments (#57)."""
import csv
import io
from datetime import datetime, time, timezone

import services.export_service as export_service
from models.audit import AuditLog
from services.export_service import COLUMNS, neutralise
from tests.test_appointments import get_next_monday, setup_appointment_test_env

URL = "/api/v1/admin/appointments/export.csv"


def _book(client, doc, headers, hour, notes="Severe headaches, private"):
    monday = get_next_monday()
    return client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": datetime.combine(monday, time(hour, 0), tzinfo=timezone.utc).isoformat(),
        "end_time": datetime.combine(monday, time(hour, 30), tzinfo=timezone.utc).isoformat(),
        "notes": notes,
    }, headers=headers).json()


def _rows(response):
    return list(csv.DictReader(io.StringIO(response.text)))


def test_only_admins_can_export(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    doctor = client.post("/api/v1/auth/login", json={"email": "doc_appt@example.com", "password": "password123"})
    doctor_headers = {"Authorization": f"Bearer {doctor.json()['access_token']}"}

    assert client.get(URL).status_code == 401
    assert client.get(URL, headers=patient).status_code == 403
    assert client.get(URL, headers=doctor_headers).status_code == 403
    assert client.get(URL, headers=admin).status_code == 200


def test_export_has_the_columns_and_no_clinical_content(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient, 9)

    r = client.get(URL, headers=admin)

    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert f'filename="appointments-{datetime.now(timezone.utc):%Y-%m-%d}.csv"' in r.headers["content-disposition"]
    assert r.text.splitlines()[0].split(",") == COLUMNS
    [row] = _rows(r)
    monday = get_next_monday().isoformat()
    assert row["appointment_id"] == appt["id"]
    assert row["start_utc"] == f"{monday}T09:00:00Z"
    assert row["end_utc"] == f"{monday}T09:30:00Z"
    assert row["start_doctor_local"].startswith(f"{monday}T09:00:00")
    assert row["status"] == "CONFIRMED"
    assert row["doctor_name"] == "Dr. Appt" and row["specialization"] == "Neurology"
    assert row["patient_name"] == "Patient One" and row["patient_email"] == "patient1_appt@example.com"
    assert row["booked_at_utc"].endswith("Z")
    assert row["cancelled_at_utc"] == "" and row["cancellation_reason"] == ""
    assert "headaches" not in r.text.lower()


def test_cancelled_rows_carry_when_and_why(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient, 9)
    client.post(f"/api/v1/appointments/{appt['id']}/cancel", json={"cancellation_reason": "Feeling better"}, headers=patient)

    [row] = _rows(client.get(URL, headers=admin))

    assert row["status"] == "CANCELLED"
    assert row["cancelled_at_utc"].endswith("Z")
    assert row["cancellation_reason"] == "Feeling better"


def test_filters_status_and_time_window(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    early = _book(client, doc, patient, 9)
    late = _book(client, doc, patient, 11)
    client.post(f"/api/v1/appointments/{early['id']}/cancel", headers=patient)
    monday = get_next_monday()
    ten = datetime.combine(monday, time(10, 0), tzinfo=timezone.utc).isoformat()

    by_status = _rows(client.get(URL, params={"status": "CANCELLED"}, headers=admin))
    assert [r["appointment_id"] for r in by_status] == [early["id"]]

    after_ten = _rows(client.get(URL, params={"from": ten}, headers=admin))
    assert [r["appointment_id"] for r in after_ten] == [late["id"]]

    before_ten = _rows(client.get(URL, params={"until": ten}, headers=admin))
    assert [r["appointment_id"] for r in before_ten] == [early["id"]]

    by_doctor = _rows(client.get(URL, params={"doctor_id": doc["id"]}, headers=admin))
    assert len(by_doctor) == 2
    assert _rows(client.get(URL, params={"doctor_id": "someone-else"}, headers=admin)) == []


def test_every_export_is_audited_with_filters_and_row_count(client, db_session):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    _book(client, doc, patient, 9)

    client.get(URL, params={"status": "CONFIRMED"}, headers=admin)

    entries = db_session.query(AuditLog).filter(AuditLog.action == "admin.appointments.export").all()
    assert len(entries) == 1
    assert entries[0].actor_role == "ADMIN"
    assert '"status": "CONFIRMED"' in entries[0].detail and '"rows": 1' in entries[0].detail


def test_formula_cells_are_neutralised():
    for dangerous in ("=HYPERLINK(\"x\")", "+1+1", "-2", "@SUM(A1)", "\tx"):
        assert neutralise(dangerous) == "'" + dangerous
    assert neutralise("Dr Ada") == "Dr Ada"
    assert neutralise(None) == ""


def test_a_formula_in_a_name_is_exported_as_text(client):
    doc, admin, _, _ = setup_appointment_test_env(client)
    client.post("/api/v1/auth/register", json={
        "email": "evil@example.com", "password": "password123", "full_name": "=cmd|' /C calc'!A0", "role": "PATIENT"})
    token = client.post("/api/v1/auth/login", json={"email": "evil@example.com", "password": "password123"}).json()["access_token"]
    _book(client, doc, {"Authorization": f"Bearer {token}"}, 9)

    [row] = _rows(client.get(URL, headers=admin))

    assert row["patient_name"] == "'=cmd|' /C calc'!A0"


def test_too_many_rows_is_a_clear_400(client, monkeypatch):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    _book(client, doc, patient, 9)
    _book(client, doc, patient, 10)
    monkeypatch.setattr(export_service, "MAX_EXPORT_ROWS", 1)

    r = client.get(URL, headers=admin)

    assert r.status_code == 400
    assert "Narrow the date range" in r.text
    assert client.get(URL, params={"until": (datetime.combine(get_next_monday(), time(9, 30), tzinfo=timezone.utc)).isoformat()},
                      headers=admin).status_code == 200  # a narrower window fits under the cap
