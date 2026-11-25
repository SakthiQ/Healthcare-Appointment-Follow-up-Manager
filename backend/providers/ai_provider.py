"""
AI provider abstraction for pre-visit, post-visit and history summary generation.

Prompt templates are taken verbatim from the LLM Usage Guidance in the original
project brief. They are reproduced in the README and docs/ai-design.md, so the
documented contract and the implementation stay in step. See docs/ai-design.md
for the full write-up.
"""
import abc
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Exact prompt templates from the project brief's "LLM Usage Guidance".
PRE_VISIT_PROMPT_TEMPLATE = (
    "Analyse these symptoms and return: urgency level (Low / Medium / High), "
    "chief complaint, and three suggested questions for the doctor. "
    "Symptoms: {symptoms}"
)

POST_VISIT_PROMPT_TEMPLATE = (
    "Convert these clinical notes into a patient-friendly summary with "
    "medication schedule and follow-up steps: {notes}"
)

# Appended to the spec's post-visit prompt so the medication schedule is built
# from what the doctor actually prescribed, not guessed from free-text notes.
POST_VISIT_PRESCRIPTION_TEMPLATE = "\n\nPrescription:\n{prescription}"

PRE_VISIT_SYSTEM_PROMPT = (
    "You are a clinical intake assistant. Given a patient's free-text "
    "symptom description, respond with ONLY a JSON object of the exact "
    "shape: "
    '{"urgency": "Low|Medium|High", "chief_complaint": "string", '
    '"suggested_questions": ["string", "string", "string"]}. '
    "Do not include any text outside the JSON object. Do not provide a "
    "diagnosis or medical advice."
)

POST_VISIT_SYSTEM_PROMPT = (
    "You are a patient-communication assistant. Given a doctor's clinical "
    "notes, respond with ONLY a JSON object of the exact shape: "
    '{"summary": "string", "medication_schedule": "string", '
    '"follow_up_steps": "string"}. '
    "Write in plain, patient-friendly language. Do not include any text "
    "outside the JSON object. Do not provide a new diagnosis. Build the "
    "medication schedule only from the Prescription section, keeping every "
    "medication's name, dosage, frequency and duration exactly as given; "
    "never add, remove or change a medication. If no medications are "
    "prescribed, say so."
)

# The history summary (#73) is not in the original brief, so its prompt is our own. It is
# reproduced in docs/ai-design.md.
HISTORY_PROMPT_TEMPLATE = (
    "Summarise this patient's previous visits to the clinic for their doctor: for each "
    "visit, the date, the complaint and the medications prescribed; then any issues that "
    "come up at more than one visit. Use only what is written below.\n\n"
    "Previous visits, newest first:\n{visits}"
)

HISTORY_SYSTEM_PROMPT = (
    "You are a clinical records assistant helping a doctor prepare for a visit. Given notes "
    "from a patient's previous visits, respond with ONLY a JSON object of the exact shape: "
    '{"recent_visits": [{"date": "YYYY-MM-DD", "complaint": "string", '
    '"medications": ["string"]}], "recurring_issues": ["string"], '
    '"notes_for_doctor": "string"}. '
    "List the visits newest first, with each date exactly as given. Summarise only what is "
    "written in the notes: do not diagnose, do not suggest new treatment or advice, and do "
    "not add anything the notes do not say. List medications exactly as prescribed. If there "
    "are no recurring issues, return an empty list. Do not include any text outside the "
    "JSON object."
)


@dataclass(frozen=True)
class PrescribedMedication:
    name: str
    dosage: str
    frequency: str
    duration_days: Optional[int] = None

    def describe(self) -> str:
        text = f"{self.name} {self.dosage}, {self.frequency}"
        if self.duration_days:
            text += f", for {self.duration_days} day{'s' if self.duration_days != 1 else ''}"
        return text


def format_prescription(
    medications: Sequence[PrescribedMedication], instructions: Optional[str]
) -> str:
    """Plain-text prescription block given to the LLM."""
    lines = [f"- {m.describe()}" for m in medications] or ["- No medications prescribed."]
    if instructions and instructions.strip():
        lines.append(f"Instructions: {instructions.strip()}")
    return "\n".join(lines)


@dataclass(frozen=True)
class PastVisit:
    """One earlier completed visit, as given to the history summary."""
    date: str  # ISO date (YYYY-MM-DD) in the clinic's local time
    notes: str
    medications: Sequence[PrescribedMedication] = ()
    instructions: Optional[str] = None


def format_visits(visits: Sequence[PastVisit]) -> str:
    """Plain-text list of previous visits given to the LLM."""
    blocks = []
    for visit in visits:
        meds = "; ".join(m.describe() for m in visit.medications) or "None"
        block = f"Visit on {visit.date}\nNotes: {visit.notes.strip()}\nMedications: {meds}"
        if visit.instructions and visit.instructions.strip():
            block += f"\nInstructions: {visit.instructions.strip()}"
        blocks.append(block)
    return "\n\n".join(blocks)


class AIProviderError(Exception):
    """Base class for AI provider failures. Never allowed to touch appointment state."""


class AIProviderTimeoutError(AIProviderError):
    pass


class AIProviderUnavailableError(AIProviderError):
    pass


class AIProviderMalformedResponseError(AIProviderError):
    """Raised when the provider's response cannot even be parsed as JSON."""


class AIProvider(abc.ABC):
    """Abstraction over any LLM backend. Returns raw (unvalidated) dicts —
    schema validation is the caller's (AIService's) responsibility."""

    @abc.abstractmethod
    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        ...

    @abc.abstractmethod
    def generate_post_visit_summary(
        self,
        notes: str,
        medications: Sequence[PrescribedMedication] = (),
        prescription_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        ...

    def generate_history_summary(self, visits: Sequence[PastVisit]) -> Dict[str, Any]:
        """Not abstract, so providers written before #73 keep working: they simply record
        a FAILED history summary."""
        raise AIProviderUnavailableError("This AI provider does not support history summaries.")


class MockAIProvider(AIProvider):
    """Deterministic, offline provider used when DEMO_MODE is enabled.
    Never calls out to a network and always returns schema-shaped output."""

    _HIGH_URGENCY_KEYWORDS = (
        "chest pain", "severe", "unbearable", "difficulty breathing",
        "shortness of breath", "unconscious", "bleeding", "stroke"
    )
    _LOW_URGENCY_KEYWORDS = ("mild", "slight", "minor", "occasional")

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        text = (symptoms or "").lower()
        if any(kw in text for kw in self._HIGH_URGENCY_KEYWORDS):
            urgency = "High"
        elif any(kw in text for kw in self._LOW_URGENCY_KEYWORDS):
            urgency = "Low"
        else:
            urgency = "Medium"

        chief_complaint = (symptoms or "").strip()[:200] or "Not specified"

        return {
            "urgency": urgency,
            "chief_complaint": chief_complaint,
            "suggested_questions": [
                "When did these symptoms first start?",
                "Have the symptoms been getting better, worse, or staying the same?",
                "Are you currently taking any medications for this?",
            ],
        }

    def generate_post_visit_summary(
        self,
        notes: str,
        medications: Sequence[PrescribedMedication] = (),
        prescription_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        notes_text = (notes or "").strip() or "No additional notes provided."
        if medications:
            schedule = " ".join(f"{m.describe()}." for m in medications)
        else:
            schedule = "No medications were prescribed at this visit."
        if prescription_instructions and prescription_instructions.strip():
            schedule += f" {prescription_instructions.strip()}"
        return {
            "summary": f"Here is a summary of your visit: {notes_text}",
            "medication_schedule": schedule,
            "follow_up_steps": "Follow up with your doctor if symptoms persist or worsen. Attend any scheduled follow-up appointment.",
        }

    def generate_history_summary(self, visits: Sequence[PastVisit]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for visit in visits:
            for name in {m.name.strip().lower(): m.name.strip() for m in visit.medications}.values():
                counts[name] = counts.get(name, 0) + 1
        return {
            "recent_visits": [
                {
                    "date": visit.date,
                    "complaint": (visit.notes or "").strip().splitlines()[0][:200] if (visit.notes or "").strip() else "Not recorded",
                    "medications": [m.describe() for m in visit.medications],
                }
                for visit in visits
            ],
            "recurring_issues": [f"{name} prescribed at {n} visits" for name, n in counts.items() if n > 1],
            "notes_for_doctor": f"{len(visits)} previous visit{'s' if len(visits) != 1 else ''} summarised from the clinic's records.",
        }


class RealAIProvider(AIProvider):
    """Calls an OpenAI-compatible Chat Completions endpoint over HTTP.

    Any LLM provider exposing an OpenAI-compatible /chat/completions API can
    be used by pointing AI_PROVIDER_BASE_URL at it. Credentials and endpoint
    come exclusively from environment variables (see app/config.py) — never
    hardcoded.
    """

    def __init__(self):
        self._base_url = settings.AI_PROVIDER_BASE_URL
        self._api_key = settings.AI_PROVIDER_API_KEY
        self._model = settings.AI_PROVIDER_MODEL
        self._timeout = settings.AI_PROVIDER_TIMEOUT_SECONDS

    def _chat_completion(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        if not self._api_key:
            raise AIProviderUnavailableError("AI_PROVIDER_API_KEY is not configured.")

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2,
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderTimeoutError(f"AI provider request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise AIProviderUnavailableError(f"AI provider request failed: {exc}") from exc

        if response.status_code >= 500:
            raise AIProviderUnavailableError(f"AI provider returned server error {response.status_code}")
        if response.status_code >= 400:
            # The body goes to the logs only: this message is stored and shown in the UI.
            logger.warning("AI provider returned error %s: %s", response.status_code, response.text)
            raise AIProviderUnavailableError(f"AI provider returned error {response.status_code}")

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise AIProviderMalformedResponseError(f"Unexpected AI provider response shape: {exc}") from exc

        import json as _json
        try:
            return _json.loads(content)
        except (ValueError, TypeError) as exc:
            raise AIProviderMalformedResponseError(f"AI provider content is not valid JSON: {exc}") from exc

    def generate_pre_visit_summary(self, symptoms: str) -> Dict[str, Any]:
        prompt = PRE_VISIT_PROMPT_TEMPLATE.format(symptoms=symptoms)
        return self._chat_completion(PRE_VISIT_SYSTEM_PROMPT, prompt)

    def generate_post_visit_summary(
        self,
        notes: str,
        medications: Sequence[PrescribedMedication] = (),
        prescription_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt = POST_VISIT_PROMPT_TEMPLATE.format(notes=notes) + POST_VISIT_PRESCRIPTION_TEMPLATE.format(
            prescription=format_prescription(medications, prescription_instructions)
        )
        return self._chat_completion(POST_VISIT_SYSTEM_PROMPT, prompt)

    def generate_history_summary(self, visits: Sequence[PastVisit]) -> Dict[str, Any]:
        prompt = HISTORY_PROMPT_TEMPLATE.format(visits=format_visits(visits))
        return self._chat_completion(HISTORY_SYSTEM_PROMPT, prompt)


def get_ai_provider() -> AIProvider:
    """Resolve the active provider based on current settings (read live, not cached,
    so DEMO_MODE toggles and test overrides take effect immediately).
    AI_DEMO_MODE, when set, overrides DEMO_MODE for this integration only."""
    if settings.ai_demo_mode:
        return MockAIProvider()
    return RealAIProvider()
