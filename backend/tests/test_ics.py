"""Appointment .ics download (#54): content, access rules and RFC 5545 escaping and folding."""
from datetime import datetime, time, timezone

from app.config import settings
from models.appointment import AppointmentStatus
from models.user import UserRole
from schemas.appointment import AppointmentResponse
from services.ics_service import build_appointment_ics, escape_text, fold_line
from tests.test_appointments import get_next_monday, setup_appointment_test_env


def _book(client, doc, headers):
    monday = get_next_monday()
    return client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": datetime.combine(monday, time(9, 0), tzinfo=timezone.utc).isoformat(),
        "end_time": datetime.combine(monday, time(9, 30), tzinfo=timezone.utc).isoformat(),
        "notes": "Severe headaches, private",
    }, headers=headers).json()


def _unfold(ics: str) -> list[str]:
    return ics.replace("\r\n ", "").split("\r\n")


def _doctor_headers(client):
    token = client.post("/api/v1/auth/login", json={"email": "doc_appt@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def test_patient_downloads_a_valid_calendar_file(client, monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "https://app.example.com")
    doc, _, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)

    r = client.get(f"/api/v1/appointments/{appt['id']}/calendar.ics", headers=patient)

    assert r.status_code == 200
    assert r.headers["content-type"] == "text/calendar; charset=utf-8"
    assert f'filename="appointment-{appt["id"]}.ics"' in r.headers["content-disposition"]
    assert "\r\n" in r.text and r.text.endswith("\r\n")
    lines = _unfold(r.text)
    assert lines[0] == "BEGIN:VCALENDAR" and "END:VCALENDAR" in lines
    assert lines.count("BEGIN:VEVENT") == 1
    assert f"UID:appointment-{appt['id']}@healthflow" in lines
    monday = get_next_monday().strftime("%Y%m%d")
    assert f"DTSTART:{monday}T090000Z" in lines
    assert f"DTEND:{monday}T093000Z" in lines
    assert "SUMMARY:Appointment with Dr. Appt" in lines
    assert f"URL:https://app.example.com/patient/appointments/{appt['id']}" in lines
    assert "STATUS:CONFIRMED" in lines
    # No clinical details: the booking notes never reach the file.
    assert "headaches" not in r.text.lower()


def test_doctor_sees_the_patient_and_admin_may_download(client):
    doc, admin, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)

    doctor_file = client.get(f"/api/v1/appointments/{appt['id']}/calendar.ics", headers=_doctor_headers(client))
    assert doctor_file.status_code == 200
    assert "SUMMARY:Appointment with Patient One" in _unfold(doctor_file.text)
    assert f"/doctor/appointments/{appt['id']}" in doctor_file.text.replace("\r\n ", "")

    assert client.get(f"/api/v1/appointments/{appt['id']}/calendar.ics", headers=admin).status_code == 200


def test_same_access_rule_as_viewing_the_appointment(client):
    doc, _, patient, other_patient = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)
    url = f"/api/v1/appointments/{appt['id']}"

    assert client.get(f"{url}/calendar.ics", headers=other_patient).status_code == \
        client.get(url, headers=other_patient).status_code == 403
    assert client.get(f"{url}/calendar.ics").status_code == 401
    assert client.get("/api/v1/appointments/no-such-id/calendar.ics", headers=patient).status_code == 404


def test_cancelled_appointment_is_marked_cancelled(client):
    doc, _, patient, _ = setup_appointment_test_env(client)
    appt = _book(client, doc, patient)
    client.post(f"/api/v1/appointments/{appt['id']}/cancel", headers=patient)

    r = client.get(f"/api/v1/appointments/{appt['id']}/calendar.ics", headers=patient)

    assert "STATUS:CANCELLED" in _unfold(r.text)


def test_text_is_escaped_per_rfc_5545():
    assert escape_text("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
    assert escape_text("line\r\nbreak") == "line\\nbreak"


def test_long_lines_are_folded_without_splitting_characters():
    line = "DESCRIPTION:" + "é" * 100  # 2 octets each
    folded = fold_line(line)

    parts = folded.split("\r\n")
    assert all(len(p.encode("utf-8")) <= 75 for p in parts)
    assert all(p.startswith(" ") for p in parts[1:])
    assert folded.replace("\r\n ", "") == line


def test_names_with_special_characters_are_escaped():
    appt = AppointmentResponse(
        id="a1", patient_id="p1", doctor_id="u1", doctor_profile_id="d1",
        start_time=datetime(2030, 1, 7, 9, tzinfo=timezone.utc), end_time=datetime(2030, 1, 7, 9, 30, tzinfo=timezone.utc),
        status=AppointmentStatus.CONFIRMED, created_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2030, 1, 1, tzinfo=timezone.utc), doctor_name="Dr Smith, Jr; MD", patient_name="Pat",
    )

    lines = _unfold(build_appointment_ics(appt, UserRole.PATIENT))

    assert "SUMMARY:Appointment with Dr Smith\\, Jr\\; MD" in lines
