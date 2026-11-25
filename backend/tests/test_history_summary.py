"""AI summary of a patient's previous visits, for their doctor (#73)."""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest

from app.config import settings
from app.core.datetime_utils import get_zone
from models.appointment import Appointment, AppointmentStatus
from models.audit import AuditLog
from models.clinical import AISummary, AISummaryType, Consultation, Medication, Prescription
from providers.ai_provider import (
    AIProvider,
    HISTORY_SYSTEM_PROMPT,
    PastVisit,
    PrescribedMedication,
    RealAIProvider,
)
from services.ai_service import HISTORY_MAX_NOTES_CHARS, HISTORY_MAX_VISITS
from tests.test_ai import _restore_ai_service, _override_ai_service, setup_ai_test_env


def URL(appointment_id):
    return f"/api/v1/appointments/{appointment_id}/ai/history-summary"


def _visit(db, appt, days_ago, notes="Persistent cough for a week.", meds=(("Amoxicillin", "500mg"),),
           status=AppointmentStatus.COMPLETED, patient_id=None, consultation=True):
    start = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    row = Appointment(patient_id=patient_id or appt["patient_id"], doctor_id=appt["doctor_id"],
                      doctor_profile_id=appt["doctor_profile_id"], start_time=start,
                      end_time=start + timedelta(minutes=30), status=status)
    db.add(row)
    db.flush()
    if consultation:
        c = Consultation(appointment_id=row.id, notes=notes)
        db.add(c)
        db.flush()
        p = Prescription(consultation_id=c.id, instructions="After meals")
        db.add(p)
        db.flush()
        for name, dose in meds:
            db.add(Medication(prescription_id=p.id, name=name, dosage=dose, frequency="twice daily", duration_days=5))
    db.commit()
    return start.astimezone(get_zone(appt.get("doctor_timezone"))).date().isoformat()


class _CapturingProvider(AIProvider):
    """Returns `output` (or a summary echoing the input) and records what it was given."""

    def __init__(self, output: Any = None):
        self.output = output
        self.calls = []

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        raise AssertionError("not used")

    def generate_post_visit_summary(self, notes: str, **_: Any) -> Dict[str, Any]:
        raise AssertionError("not used")

    def generate_history_summary(self, visits):
        self.calls.append(list(visits))
        if self.output is not None:
            return self.output
        return {"recent_visits": [{"date": v.date, "complaint": "c", "medications": []} for v in visits],
                "recurring_issues": [], "notes_for_doctor": "n"}


@pytest.fixture
def provider():
    p = _CapturingProvider()
    _override_ai_service(p)
    yield p
    _restore_ai_service()


def test_doctor_gets_earlier_completed_visits_newest_first(client, db_session):
    appt, admin, patient, other_patient, doc = setup_ai_test_env(client)
    older = _visit(db_session, appt, 60, notes="Migraine, two episodes a week.", meds=(("Sumatriptan", "50mg"), ("Amoxicillin", "250mg")))
    newer = _visit(db_session, appt, 10, notes="Persistent cough.\nNo fever.")
    _visit(db_session, appt, 5, status=AppointmentStatus.CANCELLED)       # not completed
    _visit(db_session, appt, 4, consultation=False)                       # no notes recorded
    other_id = client.get("/api/v1/auth/me", headers=other_patient).json()["id"]
    _visit(db_session, appt, 3, patient_id=other_id)                      # someone else

    r = client.post(URL(appt["id"]), headers=doc)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "HISTORY" and body["status"] == "SUCCESS"
    visits = body["payload"]["recent_visits"]
    assert [v["date"] for v in visits] == [newer, older]
    assert visits[0]["complaint"] == "Persistent cough."
    assert visits[0]["medications"] == ["Amoxicillin 500mg, twice daily, for 5 days"]
    # Amoxicillin was prescribed at both visits (at different doses), so it recurs.
    assert body["payload"]["recurring_issues"] == ["Amoxicillin prescribed at 2 visits"]

    fetched = client.get(URL(appt["id"]), headers=doc)
    assert fetched.status_code == 200 and fetched.json()["id"] == body["id"]


def test_later_visits_and_the_appointment_itself_are_left_out(client, db_session, provider):
    appt, admin, patient, _, doc = setup_ai_test_env(client)
    earlier = _visit(db_session, appt, 30)
    _visit(db_session, appt, -30)  # completed, but after this appointment

    client.post(URL(appt["id"]), headers=doc)

    assert [v.date for v in provider.calls[0]] == [earlier]


def test_patient_with_no_history_gets_an_empty_summary_without_calling_the_model(client, provider):
    appt, admin, patient, _, doc = setup_ai_test_env(client)

    r = client.post(URL(appt["id"]), headers=doc)

    assert r.status_code == 200
    assert r.json()["status"] == "SUCCESS"
    assert r.json()["payload"] == {"recent_visits": [], "recurring_issues": [],
                                   "notes_for_doctor": "No previous completed visits with this clinic."}
    assert provider.calls == []


def test_only_the_appointments_doctor_and_admins_can_use_it(client):
    appt, admin, patient, other_patient, doc = setup_ai_test_env(client)
    client.post("/api/v1/admin/doctors", json={
        "email": "doc2_hist@example.com", "password": "password123", "full_name": "Dr. Other",
        "specialization": "Dermatology", "slot_duration_minutes": 30}, headers=admin)
    token = client.post("/api/v1/auth/login", json={"email": "doc2_hist@example.com", "password": "password123"}).json()["access_token"]
    other_doc = {"Authorization": f"Bearer {token}"}

    for headers in (patient, other_patient, other_doc):
        assert client.post(URL(appt["id"]), headers=headers).status_code == 403
        assert client.get(URL(appt["id"]), headers=headers).status_code == 403

    assert client.get(URL(appt["id"]), headers=doc).status_code == 404  # nothing generated yet
    assert client.post(URL(appt["id"]), headers=admin).status_code == 200
    assert client.get(URL(appt["id"]), headers=doc).status_code == 200
    assert client.post(URL("no-such-appointment"), headers=doc).status_code == 404


@pytest.mark.parametrize("output, reason", [
    ({"recent_visits": [], "recurring_issues": []}, "Invalid AI response schema"),                     # no notes_for_doctor
    ({"recent_visits": [{"date": "last week", "complaint": "c"}], "recurring_issues": [],
      "notes_for_doctor": "n"}, "Invalid AI response schema"),                                          # not a date
    ("not a JSON object", "Invalid AI response schema"),
    ({"recent_visits": [{"date": "2001-01-01", "complaint": "c", "medications": []}],
      "recurring_issues": [], "notes_for_doctor": "n"}, "not in the records"),                          # invented visit
])
def test_invalid_output_is_stored_as_failed_and_the_appointment_is_untouched(client, db_session, provider, output, reason):
    appt, admin, patient, _, doc = setup_ai_test_env(client)
    _visit(db_session, appt, 30)
    provider.output = output

    r = client.post(URL(appt["id"]), headers=doc)

    assert r.status_code == 200
    assert r.json()["status"] == "FAILED"
    assert reason in r.json()["error_message"]
    assert r.json()["payload"] is None
    assert client.get(f"/api/v1/appointments/{appt['id']}", headers=patient).json()["status"] == appt["status"]


def test_a_provider_without_history_support_fails_gracefully(client, db_session):
    class OldProvider(AIProvider):
        def generate_pre_visit_summary(self, symptoms):
            return {}

        def generate_post_visit_summary(self, notes, **_):
            return {}

    appt, admin, patient, _, doc = setup_ai_test_env(client)
    _visit(db_session, appt, 30)
    _override_ai_service(OldProvider())
    try:
        r = client.post(URL(appt["id"]), headers=doc)
    finally:
        _restore_ai_service()

    assert r.json()["status"] == "FAILED"
    assert "does not support history summaries" in r.json()["error_message"]


def test_input_is_capped_in_visits_and_note_length(client, db_session, provider):
    appt, admin, patient, _, doc = setup_ai_test_env(client)
    for days in range(1, HISTORY_MAX_VISITS + 4):
        _visit(db_session, appt, days, notes="x" * (HISTORY_MAX_NOTES_CHARS + 500))

    client.post(URL(appt["id"]), headers=doc)

    visits = provider.calls[0]
    assert len(visits) == HISTORY_MAX_VISITS
    assert all(len(v.notes) == HISTORY_MAX_NOTES_CHARS for v in visits)
    assert visits == sorted(visits, key=lambda v: v.date, reverse=True)


def test_counts_towards_the_per_appointment_cap(client, monkeypatch):
    appt, admin, patient, _, doc = setup_ai_test_env(client)
    monkeypatch.setattr(settings, "AI_MAX_SUMMARIES_PER_APPOINTMENT", 1)

    assert client.post(URL(appt["id"]), headers=doc).status_code == 200
    assert client.post(URL(appt["id"]), headers=doc).status_code == 429


def test_counts_towards_the_hourly_ai_rate_limit(client, monkeypatch):
    appt, admin, patient, _, doc = setup_ai_test_env(client)
    monkeypatch.setattr(settings, "RATE_LIMITING_ENABLED", True)
    monkeypatch.setattr(settings, "AI_RATE_LIMIT_PER_HOUR", 2)

    assert client.post(URL(appt["id"]), headers=doc).status_code == 200
    assert client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doc).status_code != 429
    # The same "ai-generate" bucket as the other summaries: the third request is refused.
    assert client.post(URL(appt["id"]), headers=doc).status_code == 429


def test_generating_and_viewing_are_audited_with_the_patient(client, db_session):
    appt, admin, patient, _, doc = setup_ai_test_env(client)

    client.post(URL(appt["id"]), headers=doc)
    client.get(URL(appt["id"]), headers=admin)

    db_session.expire_all()
    rows = db_session.query(AuditLog).filter(AuditLog.action.like("ai.history.%")).order_by(AuditLog.occurred_at).all()
    assert [r.action for r in rows] == ["ai.history.generate", "ai.history.view"]
    assert {r.patient_id for r in rows} == {appt["patient_id"]}
    assert [r.actor_role for r in rows] == ["DOCTOR", "ADMIN"]


def test_payload_is_stored_with_json_dates(client, db_session):
    appt, admin, patient, _, doc = setup_ai_test_env(client)
    date = _visit(db_session, appt, 30)

    client.post(URL(appt["id"]), headers=doc)

    db_session.expire_all()
    row = db_session.query(AISummary).filter(AISummary.type == AISummaryType.HISTORY).one()
    assert row.payload["recent_visits"][0]["date"] == date


def test_real_provider_prompt_contains_the_visits_and_forbids_diagnosis(monkeypatch):
    sent = {}

    def fake(self, system_prompt, user_prompt):
        sent.update(system=system_prompt, user=user_prompt)
        return {}

    monkeypatch.setattr(RealAIProvider, "_chat_completion", fake)
    RealAIProvider().generate_history_summary([
        PastVisit(date="2026-10-01", notes="Back pain after lifting.",
                  medications=(PrescribedMedication("Ibuprofen", "400mg", "three times daily", 5),),
                  instructions="With food"),
        PastVisit(date="2026-08-12", notes="Routine check."),
    ])

    assert sent["system"] == HISTORY_SYSTEM_PROMPT
    assert "do not diagnose" in sent["system"] and "do not suggest new treatment" in sent["system"]
    user = sent["user"]
    assert user.index("Visit on 2026-10-01") < user.index("Visit on 2026-08-12")
    assert "Back pain after lifting." in user
    assert "Ibuprofen 400mg, three times daily, for 5 days" in user
    assert "Instructions: With food" in user
    assert "Medications: None" in user
