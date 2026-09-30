from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict

from app.database import get_db
from app.main import app
from models.clinical import AISummaryStatus, AISummaryType
from providers.ai_provider import (
    AIProvider,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
    AIProviderMalformedResponseError,
)
from services.ai_service import AIService


def get_next_monday() -> date:
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def setup_ai_test_env(client):
    """Admin, one doctor with working hours, one confirmed appointment for Patient One."""
    client.post("/api/v1/auth/register", json={
        "email": "admin_ai@example.com", "password": "password123", "full_name": "Admin AI", "role": "ADMIN"
    })
    admin_token = client.post("/api/v1/auth/login", json={"email": "admin_ai@example.com", "password": "password123"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    doc = client.post("/api/v1/admin/doctors", json={
        "email": "doc_ai@example.com", "password": "password123", "full_name": "Dr. AI",
        "specialization": "General Medicine", "slot_duration_minutes": 30
    }, headers=admin_headers).json()

    client.post(f"/api/v1/admin/doctors/{doc['id']}/schedule", json={
        "working_hours": [
            {"day_of_week": 0, "start_time": "09:00:00", "end_time": "12:00:00", "is_active": True}
        ]
    }, headers=admin_headers)

    client.post("/api/v1/auth/register", json={
        "email": "patient1_ai@example.com", "password": "password123", "full_name": "Patient One", "role": "PATIENT"
    })
    token1 = client.post("/api/v1/auth/login", json={"email": "patient1_ai@example.com", "password": "password123"}).json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    client.post("/api/v1/auth/register", json={
        "email": "patient2_ai@example.com", "password": "password123", "full_name": "Patient Two", "role": "PATIENT"
    })
    token2 = client.post("/api/v1/auth/login", json={"email": "patient2_ai@example.com", "password": "password123"}).json()["access_token"]
    headers2 = {"Authorization": f"Bearer {token2}"}

    doc_user_token = client.post("/api/v1/auth/login", json={"email": "doc_ai@example.com", "password": "password123"}).json()["access_token"]
    doc_headers = {"Authorization": f"Bearer {doc_user_token}"}

    next_monday = get_next_monday()
    start_dt = datetime.combine(next_monday, time(9, 0), tzinfo=timezone.utc)
    end_dt = datetime.combine(next_monday, time(9, 30), tzinfo=timezone.utc)

    appt = client.post("/api/v1/appointments", json={
        "doctor_id": doc["id"],
        "start_time": start_dt.isoformat(),
        "end_time": end_dt.isoformat()
    }, headers=headers1).json()

    return appt, admin_headers, headers1, headers2, doc_headers


class _FixedProvider(AIProvider):
    """Test double returning a caller-supplied fixed payload for each call."""

    def __init__(self, pre_visit_output: Any = None, post_visit_output: Any = None):
        self._pre = pre_visit_output
        self._post = post_visit_output

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        return self._pre

    def generate_post_visit_summary(self, notes: str, **_: Any) -> Dict[str, Any]:
        return self._post


class _RaisingProvider(AIProvider):
    """Test double that always raises a given exception, simulating provider failure."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        raise self._exc

    def generate_post_visit_summary(self, notes: str, **_: Any) -> Dict[str, Any]:
        raise self._exc


def _override_ai_service(provider: AIProvider):
    """Swap the module-level ai_service used by app.api.ai with one bound to a test double provider."""
    import app.api.ai as ai_api_module
    ai_api_module.ai_service = AIService(provider=provider)


def _restore_ai_service():
    import app.api.ai as ai_api_module
    from services.ai_service import ai_service as default_ai_service
    ai_api_module.ai_service = default_ai_service


# ---------------------------------------------------------------------------
# Pre-visit: valid output (DEMO_MODE / MockAIProvider, the default in tests)
# ---------------------------------------------------------------------------

def test_valid_pre_visit_summary_output_and_persistence(client):
    appt, _, headers1, _, doc_headers = setup_ai_test_env(client)

    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "I have a mild headache since this morning."
    }, headers=headers1)

    r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == AISummaryType.PRE_VISIT.value
    assert data["status"] == AISummaryStatus.SUCCESS.value
    assert data["payload"]["urgency"] in ("Low", "Medium", "High")
    assert isinstance(data["payload"]["chief_complaint"], str) and data["payload"]["chief_complaint"]
    assert len(data["payload"]["suggested_questions"]) == 3

    # Output persistence: doctor retrieves the same summary without regenerating it.
    r_get = client.get(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=doc_headers)
    assert r_get.status_code == 200
    assert r_get.json()["id"] == data["id"]
    assert r_get.json()["payload"] == data["payload"]


def test_pre_visit_summary_requires_symptom_report_first(client):
    appt, _, headers1, _, _ = setup_ai_test_env(client)
    r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    assert r.status_code == 422


def test_pre_visit_summary_unauthorized_patient_cannot_view(client):
    appt, _, headers1, headers2, _ = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Persistent cough."
    }, headers=headers1)
    client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)

    r = client.get(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers2)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Pre-visit: graceful failure handling
# ---------------------------------------------------------------------------

def test_pre_visit_invalid_json_from_provider_marks_failed_and_appointment_stays_valid(client):
    appt, _, headers1, _, _ = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Sore throat."
    }, headers=headers1)

    _override_ai_service(_RaisingProvider(AIProviderMalformedResponseError("content is not valid JSON")))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    finally:
        _restore_ai_service()

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == AISummaryStatus.FAILED.value
    assert data["payload"] is None
    assert "not valid JSON" in data["error_message"]

    # Appointment must remain valid/untouched by the AI failure.
    r_appt = client.get(f"/api/v1/appointments/{appt['id']}", headers=headers1)
    assert r_appt.status_code == 200
    assert r_appt.json()["status"] == "CONFIRMED"


def test_pre_visit_invalid_urgency_value_marks_failed(client):
    appt, _, headers1, _, _ = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Fever."
    }, headers=headers1)

    bad_payload = {
        "urgency": "Extreme",  # not one of Low/Medium/High
        "chief_complaint": "Fever",
        "suggested_questions": ["Q1?", "Q2?", "Q3?"],
    }
    _override_ai_service(_FixedProvider(pre_visit_output=bad_payload))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    finally:
        _restore_ai_service()

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == AISummaryStatus.FAILED.value
    assert "Invalid AI response schema" in data["error_message"]


def test_pre_visit_wrong_number_of_questions_marks_failed(client):
    appt, _, headers1, _, _ = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Fatigue."
    }, headers=headers1)

    bad_payload = {
        "urgency": "Low",
        "chief_complaint": "Fatigue",
        "suggested_questions": ["Q1?", "Q2?"],  # only 2, not exactly 3
    }
    _override_ai_service(_FixedProvider(pre_visit_output=bad_payload))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    finally:
        _restore_ai_service()

    assert r.status_code == 200
    assert r.json()["status"] == AISummaryStatus.FAILED.value


def test_pre_visit_provider_timeout_marks_failed_and_appointment_stays_valid(client):
    appt, _, headers1, _, _ = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Dizziness."
    }, headers=headers1)

    _override_ai_service(_RaisingProvider(AIProviderTimeoutError("request timed out after 15s")))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    finally:
        _restore_ai_service()

    assert r.status_code == 200
    data = r.json()
    assert data["status"] == AISummaryStatus.FAILED.value
    assert "timed out" in data["error_message"]

    r_appt = client.get(f"/api/v1/appointments/{appt['id']}", headers=headers1)
    assert r_appt.json()["status"] == "CONFIRMED"


def test_pre_visit_provider_unavailable_marks_failed(client):
    appt, _, headers1, _, _ = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/symptom-report", json={
        "symptoms": "Nausea."
    }, headers=headers1)

    _override_ai_service(_RaisingProvider(AIProviderUnavailableError("service unreachable")))
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/pre-visit-summary", headers=headers1)
    finally:
        _restore_ai_service()

    assert r.status_code == 200
    assert r.json()["status"] == AISummaryStatus.FAILED.value


# ---------------------------------------------------------------------------
# Post-visit: valid output + persistence
# ---------------------------------------------------------------------------

def test_valid_post_visit_summary_output_and_persistence(client):
    appt, _, headers1, _, doc_headers = setup_ai_test_env(client)

    r_consult = client.post(f"/api/v1/appointments/{appt['id']}/consultation", json={
        "notes": "Patient presented with mild seasonal allergies. Prescribed antihistamine.",
        "prescription_instructions": "Take once daily after breakfast.",
        "medications": [
            {"name": "Cetirizine", "dosage": "10mg", "frequency": "Once daily", "duration_days": 7}
        ]
    }, headers=doc_headers)
    assert r_consult.status_code == 201

    r = client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doc_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == AISummaryType.POST_VISIT.value
    assert data["status"] == AISummaryStatus.SUCCESS.value
    assert data["payload"]["summary"]
    assert data["payload"]["medication_schedule"]
    assert data["payload"]["follow_up_steps"]

    # Patient (owner) retrieves the persisted summary.
    r_get = client.get(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=headers1)
    assert r_get.status_code == 200
    assert r_get.json()["id"] == data["id"]
    assert r_get.json()["payload"] == data["payload"]


def test_post_visit_summary_requires_consultation_first(client):
    appt, _, _, _, doc_headers = setup_ai_test_env(client)
    r = client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doc_headers)
    assert r.status_code == 422


def test_duplicate_consultation_submission_rejected(client):
    appt, _, _, _, doc_headers = setup_ai_test_env(client)
    payload = {"notes": "Initial notes.", "medications": []}
    r1 = client.post(f"/api/v1/appointments/{appt['id']}/consultation", json=payload, headers=doc_headers)
    assert r1.status_code == 201
    r2 = client.post(f"/api/v1/appointments/{appt['id']}/consultation", json=payload, headers=doc_headers)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Post-visit: the prescription reaches the AI, not just the free-text notes
# ---------------------------------------------------------------------------

_CONSULTATION_WITH_PRESCRIPTION = {
    "notes": "Acute sinusitis. Rest and fluids.",
    "prescription_instructions": "Take with food.",
    "medications": [
        {"name": "Amoxicillin", "dosage": "500mg", "frequency": "three times daily", "duration_days": 7},
        {"name": "Paracetamol", "dosage": "1g", "frequency": "every 6 hours as needed", "duration_days": None},
    ],
}


class _RecordingProvider(_FixedProvider):
    def __init__(self):
        super().__init__(post_visit_output={
            "summary": "s", "medication_schedule": "m", "follow_up_steps": "f",
        })
        self.post_visit_calls = []

    def generate_post_visit_summary(self, notes, medications=(), prescription_instructions=None):
        self.post_visit_calls.append((notes, list(medications), prescription_instructions))
        return self._post


def test_post_visit_summary_receives_prescription(client):
    appt, _, _, _, doc_headers = setup_ai_test_env(client)
    r = client.post(f"/api/v1/appointments/{appt['id']}/consultation",
                    json=_CONSULTATION_WITH_PRESCRIPTION, headers=doc_headers)
    assert r.status_code == 201

    provider = _RecordingProvider()
    _override_ai_service(provider)
    try:
        r = client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doc_headers)
    finally:
        _restore_ai_service()
    assert r.status_code == 200 and r.json()["status"] == AISummaryStatus.SUCCESS.value

    notes, meds, instructions = provider.post_visit_calls[0]
    assert notes == "Acute sinusitis. Rest and fluids."
    assert instructions == "Take with food."
    assert {(m.name, m.dosage, m.frequency, m.duration_days) for m in meds} == {
        ("Amoxicillin", "500mg", "three times daily", 7),
        ("Paracetamol", "1g", "every 6 hours as needed", None),
    }


def test_mock_post_visit_schedule_lists_prescribed_medications(client):
    appt, _, _, _, doc_headers = setup_ai_test_env(client)
    client.post(f"/api/v1/appointments/{appt['id']}/consultation",
                json=_CONSULTATION_WITH_PRESCRIPTION, headers=doc_headers)
    r = client.post(f"/api/v1/appointments/{appt['id']}/ai/post-visit-summary", headers=doc_headers)
    schedule = r.json()["payload"]["medication_schedule"]
    assert "Amoxicillin 500mg, three times daily, for 7 days" in schedule
    assert "Paracetamol 1g, every 6 hours as needed" in schedule
    assert "Take with food." in schedule


def test_real_provider_prompt_includes_prescription(monkeypatch):
    import json as _json
    from app.config import settings
    from providers.ai_provider import PrescribedMedication, RealAIProvider

    monkeypatch.setattr(settings, "AI_PROVIDER_API_KEY", "test-key")
    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": _json.dumps(
                {"summary": "s", "medication_schedule": "m", "follow_up_steps": "f"})}}]}

    def fake_post(url, headers, json, timeout):
        captured["messages"] = json["messages"]
        return _Resp()

    monkeypatch.setattr("providers.ai_provider.httpx.post", fake_post)
    RealAIProvider().generate_post_visit_summary(
        "Acute sinusitis.",
        medications=[PrescribedMedication("Amoxicillin", "500mg", "three times daily", 7)],
        prescription_instructions="Take with food.",
    )
    user_prompt = captured["messages"][1]["content"]
    assert "Acute sinusitis." in user_prompt
    assert "- Amoxicillin 500mg, three times daily, for 7 days" in user_prompt
    assert "Instructions: Take with food." in user_prompt
    assert "Prescription section" in captured["messages"][0]["content"]
